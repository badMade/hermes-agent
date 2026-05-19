"""
OpenAI-compatible API server platform adapter.

Exposes an HTTP server with endpoints:
- POST /v1/chat/completions        — OpenAI Chat Completions format (stateless; opt-in session continuity via X-Hermes-Session-Id header; opt-in long-term memory scoping via X-Hermes-Session-Key header)
- POST /v1/responses               — OpenAI Responses API format (stateful via previous_response_id; X-Hermes-Session-Key supported)
- GET  /v1/responses/{response_id} — Retrieve a stored response
- DELETE /v1/responses/{response_id} — Delete a stored response
- GET  /v1/models                  — lists hermes-agent as an available model
- GET  /v1/capabilities            — machine-readable API capabilities for external UIs
- POST /v1/runs                    — start a run, returns run_id immediately (202)
- GET  /v1/runs/{run_id}           — retrieve current run status
- GET  /v1/runs/{run_id}/events    — SSE stream of structured lifecycle events
- POST /v1/runs/{run_id}/approval — resolve a pending run approval
- POST /v1/runs/{run_id}/stop       — interrupt a running agent
- GET  /health                     — health check
- GET  /health/detailed            — rich status for cross-container dashboard probing

Any OpenAI-compatible frontend (Open WebUI, LobeChat, LibreChat,
AnythingLLM, NextChat, ChatBox, etc.) can connect to hermes-agent
through this adapter by pointing at http://localhost:8642/v1.

Requires:
- aiohttp (already available in the gateway)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket as _socket
import re
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None  # type: ignore[assignment]

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    SendResult,
    is_network_accessible,
)
from hermes_cli.auth import has_usable_secret

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642
MAX_STORED_RESPONSES = 100
MAX_REQUEST_BYTES = 10_000_000  # 10 MB — accommodates long agent conversations with tool calls
CHAT_COMPLETIONS_SSE_KEEPALIVE_SECONDS = 30.0
MAX_NORMALIZED_TEXT_LENGTH = 65_536  # 64 KB cap for normalized content parts
MAX_CONTENT_LIST_SIZE = 1_000  # Max items when content is an array


def _coerce_port(value: Any, default: int = DEFAULT_PORT) -> int:
    """Parse a listen port without letting malformed env/config values crash startup."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_chat_content(
    content: Any, *, _max_depth: int = 10, _depth: int = 0,
) -> str:
    """Normalize OpenAI chat message content into a plain text string.

    Some clients (Open WebUI, LobeChat, etc.) send content as an array of
    typed parts instead of a plain string::

        [{"type": "text", "text": "hello"}, {"type": "input_text", "text": "..."}]

    This function flattens those into a single string so the agent pipeline
    (which expects strings) doesn't choke.

    Defensive limits prevent abuse: recursion depth, list size, and output
    length are all bounded.
    """
    if _depth > _max_depth:
        return ""
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:MAX_NORMALIZED_TEXT_LENGTH] if len(content) > MAX_NORMALIZED_TEXT_LENGTH else content

    if isinstance(content, list):
        parts: List[str] = []
        items = content[:MAX_CONTENT_LIST_SIZE] if len(content) > MAX_CONTENT_LIST_SIZE else content
        for item in items:
            if isinstance(item, str):
                if item:
                    parts.append(item[:MAX_NORMALIZED_TEXT_LENGTH])
            elif isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type in {"text", "input_text", "output_text"}:
                    text = item.get("text", "")
                    if text:
                        try:
                            parts.append(str(text)[:MAX_NORMALIZED_TEXT_LENGTH])
                        except Exception:
                            pass
                # Silently skip image_url / other non-text parts
            elif isinstance(item, list):
                nested = _normalize_chat_content(item, _max_depth=_max_depth, _depth=_depth + 1)
                if nested:
                    parts.append(nested)
            # Check accumulated size
            if sum(len(p) for p in parts) >= MAX_NORMALIZED_TEXT_LENGTH:
                break
        result = "\n".join(parts)
        return result[:MAX_NORMALIZED_TEXT_LENGTH] if len(result) > MAX_NORMALIZED_TEXT_LENGTH else result

    # Fallback for unexpected types (int, float, bool, etc.)
    try:
        result = str(content)
        return result[:MAX_NORMALIZED_TEXT_LENGTH] if len(result) > MAX_NORMALIZED_TEXT_LENGTH else result
    except Exception:
        return ""


# Content part type aliases used by the OpenAI Chat Completions and Responses
# APIs.  We accept both spellings on input and emit a single canonical internal
# shape (``{"type": "text", ...}`` / ``{"type": "image_url", ...}``) that the
# rest of the agent pipeline already understands.
_TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
_IMAGE_PART_TYPES = frozenset({"image_url", "input_image"})
_FILE_PART_TYPES = frozenset({"file", "input_file"})


def _normalize_multimodal_content(content: Any) -> Any:
    """Validate and normalize multimodal content for the API server.

    Returns a plain string when the content is text-only, or a list of
    ``{"type": "text"|"image_url", ...}`` parts when images are present.
    The output shape is the native OpenAI Chat Completions vision format,
    which the agent pipeline accepts verbatim (OpenAI-wire providers) or
    converts (``_preprocess_anthropic_content`` for Anthropic).

    Raises ``ValueError`` with an OpenAI-style code on invalid input:
      * ``unsupported_content_type`` — file/input_file/file_id parts, or
        non-image ``data:`` URLs.
      * ``invalid_image_url`` — missing URL or unsupported scheme.
      * ``invalid_content_part`` — malformed text/image objects.

    Callers translate the ValueError into a 400 response.
    """
    # Scalar passthrough mirrors ``_normalize_chat_content``.
    if content is None:
        return ""
    if isinstance(content, str):
        return content[:MAX_NORMALIZED_TEXT_LENGTH] if len(content) > MAX_NORMALIZED_TEXT_LENGTH else content
    if not isinstance(content, list):
        # Mirror the legacy text-normalizer's fallback so callers that
        # pre-existed image support still get a string back.
        return _normalize_chat_content(content)

    items = content[:MAX_CONTENT_LIST_SIZE] if len(content) > MAX_CONTENT_LIST_SIZE else content
    normalized_parts: List[Dict[str, Any]] = []
    text_accum_len = 0

    for part in items:
        if isinstance(part, str):
            if part:
                trimmed = part[:MAX_NORMALIZED_TEXT_LENGTH]
                normalized_parts.append({"type": "text", "text": trimmed})
                text_accum_len += len(trimmed)
            continue

        if not isinstance(part, dict):
            continue

        raw_type = part.get("type")
        part_type = str(raw_type or "").strip().lower()

        if part_type in _TEXT_PART_TYPES:
            text = part.get("text")
            if text is None:
                continue
            if not isinstance(text, str):
                text = str(text)
            if text:
                trimmed = text[:MAX_NORMALIZED_TEXT_LENGTH]
                normalized_parts.append({"type": "text", "text": trimmed})
                text_accum_len += len(trimmed)
            continue

        if part_type in _IMAGE_PART_TYPES:
            detail = part.get("detail")
            image_ref = part.get("image_url")
            if isinstance(image_ref, dict):
                url_value = image_ref.get("url")
                detail = image_ref.get("detail", detail)
            else:
                url_value = image_ref
            if not isinstance(url_value, str) or not url_value.strip():
                raise ValueError("invalid_image_url:Image parts must include a non-empty image URL.")
            url_value = url_value.strip()
            lowered = url_value.lower()
            if lowered.startswith("data:"):
                if not lowered.startswith("data:image/") or "," not in url_value:
                    raise ValueError(
                        "unsupported_content_type:Only image data URLs are supported. "
                        "Non-image data payloads are not supported."
                    )
            elif not (lowered.startswith("http://") or lowered.startswith("https://")):
                raise ValueError(
                    "invalid_image_url:Image inputs must use http(s) URLs or data:image/... URLs."
                )
            image_part: Dict[str, Any] = {"type": "image_url", "image_url": {"url": url_value}}
            if detail is not None:
                if not isinstance(detail, str) or not detail.strip():
                    raise ValueError("invalid_content_part:Image detail must be a non-empty string when provided.")
                image_part["image_url"]["detail"] = detail.strip()
            normalized_parts.append(image_part)
            continue

        if part_type in _FILE_PART_TYPES:
            raise ValueError(
                "unsupported_content_type:Inline image inputs are supported, "
                "but uploaded files and document inputs are not supported on this endpoint."
            )

        raise ValueError(
            f"unsupported_content_type:Unsupported content part type {raw_type!r}. "
            "Only text and image_url/input_image parts are supported."
        )

    if not normalized_parts:
        return ""

    if all(p.get("type") == "text" for p in normalized_parts):
        return "\n".join(p["text"] for p in normalized_parts if p.get("text"))

    return normalized_parts


def _content_has_visible_payload(content: Any) -> bool:
    """True when content has any text or image attachment.  Used to reject empty turns."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                ptype = str(part.get("type") or "").strip().lower()
                if ptype in _TEXT_PART_TYPES and str(part.get("text") or "").strip():
                    return True
                if ptype in _IMAGE_PART_TYPES:
                    return True
    return False


def _multimodal_validation_error(exc: ValueError, *, param: str) -> "web.Response":
    """Translate a ``_normalize_multimodal_content`` ValueError into a 400 response."""
    raw = str(exc)
    code, _, message = raw.partition(":")
    if not message:
        code, message = "invalid_content_part", raw
    return web.json_response(
        _openai_error(message, code=code, param=param),
        status=400,
    )


def check_api_server_requirements() -> bool:
    """Check if API server dependencies are available."""
    return AIOHTTP_AVAILABLE


class ResponseStore:
    """
    SQLite-backed LRU store for Responses API state.

    Each stored response includes the full internal conversation history
    (with tool calls and results) so it can be reconstructed on subsequent
    requests via previous_response_id.

    Persists across gateway restarts.  Falls back to in-memory SQLite
    if the on-disk path is unavailable.
    """

    def __init__(self, max_size: int = MAX_STORED_RESPONSES, db_path: str = None):
        self._max_size = max_size
        if db_path is None:
            try:
                from hermes_cli.config import get_hermes_home
                db_path = str(get_hermes_home() / "response_store.db")
            except Exception:
                db_path = ":memory:"
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
        except Exception:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        from hermes_state import apply_wal_with_fallback
        apply_wal_with_fallback(self._conn, db_label="response_store.db")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS responses (
                response_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                accessed_at REAL NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                name TEXT PRIMARY KEY,
                response_id TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def get(self, response_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a stored response by ID (updates access time for LRU)."""
        row = self._conn.execute(
            "SELECT data FROM responses WHERE response_id = ?", (response_id,)
        ).fetchone()
        if row is None:
            return None
        self._conn.execute(
            "UPDATE responses SET accessed_at = ? WHERE response_id = ?",
            (time.time(), response_id),
        )
        self._conn.commit()
        return json.loads(row[0])

    def put(self, response_id: str, data: Dict[str, Any]) -> None:
        """Store a response, evicting the oldest if at capacity."""
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (response_id, data, accessed_at) VALUES (?, ?, ?)",
            (response_id, json.dumps(data, default=str), time.time()),
        )
        count = self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        if count > self._max_size:
            self._conn.execute(
                "DELETE FROM responses WHERE response_id IN "
                "(SELECT response_id FROM responses ORDER BY accessed_at ASC LIMIT ?)",
                (count - self._max_size,),
            )
        self._conn.commit()

    def delete(self, response_id: str) -> bool:
        """Remove a response from the store. Returns True if found and deleted."""
        cursor = self._conn.execute(
            "DELETE FROM responses WHERE response_id = ?", (response_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_conversation(self, name: str) -> Optional[str]:
        """Get the latest response_id for a conversation name."""
        row = self._conn.execute(
            "SELECT response_id FROM conversations WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def set_conversation(self, name: str, response_id: str) -> None:
        """Map a conversation name to its latest response_id."""
        self._conn.execute(
            "INSERT OR REPLACE INTO conversations (name, response_id) VALUES (?, ?)",
            (name, response_id),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    def __len__(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

_CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Idempotency-Key",
}


if AIOHTTP_AVAILABLE:
    @web.middleware
    async def cors_middleware(request, handler):
        """Add CORS headers for explicitly allowed origins; handle OPTIONS preflight."""
        adapter = request.app.get("api_server_adapter")
        origin = request.headers.get("Origin", "")
        cors_headers = None
        if adapter is not None:
            if not adapter._origin_allowed(origin):
                return web.Response(status=403)
            cors_headers = adapter._cors_headers_for_origin(origin)

        if request.method == "OPTIONS":
            if cors_headers is None:
                return web.Response(status=403)
            return web.Response(status=200, headers=cors_headers)

        response = await handler(request)
        if cors_headers is not None:
            response.headers.update(cors_headers)
        return response
else:
    cors_middleware = None  # type: ignore[assignment]


def _openai_error(message: str, err_type: str = "invalid_request_error", param: str = None, code: str = None) -> Dict[str, Any]:
    """OpenAI-style error envelope."""
    return {
        "error": {
            "message": message,
            "type": err_type,
            "param": param,
            "code": code,
        }
    }


if AIOHTTP_AVAILABLE:
    @web.middleware
    async def body_limit_middleware(request, handler):
        """Reject overly large request bodies early based on Content-Length."""
        if request.method in {"POST", "PUT", "PATCH"}:
            cl = request.headers.get("Content-Length")
            if cl is not None:
                try:
                    if int(cl) > MAX_REQUEST_BYTES:
                        return web.json_response(_openai_error("Request body too large.", code="body_too_large"), status=413)
                except ValueError:
                    return web.json_response(_openai_error("Invalid Content-Length header.", code="invalid_content_length"), status=400)
        return await handler(request)
else:
    body_limit_middleware = None  # type: ignore[assignment]

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


if AIOHTTP_AVAILABLE:
    @web.middleware
    async def security_headers_middleware(request, handler):
        """Add security headers to all responses (including errors)."""
        response = await handler(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
else:
    security_headers_middleware = None  # type: ignore[assignment]


class _IdempotencyCache:
    """In-memory idempotency cache with TTL and basic LRU semantics."""
    def __init__(self, max_items: int = 1000, ttl_seconds: int = 300):
        from collections import OrderedDict
        self._store = OrderedDict()
        self._inflight: Dict[tuple[str, str], "asyncio.Task[Any]"] = {}
        self._ttl = ttl_seconds
        self._max = max_items

    def _purge(self):
        now = time.time()
        expired = [k for k, v in self._store.items() if now - v["ts"] > self._ttl]
        for k in expired:
            self._store.pop(k, None)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    async def get_or_set(self, key: str, fingerprint: str, compute_coro):
        self._purge()
        item = self._store.get(key)
        if item and item["fp"] == fingerprint:
            return item["resp"]

        inflight_key = (key, fingerprint)
        task = self._inflight.get(inflight_key)
        if task is None:
            async def _compute_and_store():
                resp = await compute_coro()
                import time as _t
                self._store[key] = {"resp": resp, "fp": fingerprint, "ts": _t.time()}
                self._purge()
                return resp

            task = asyncio.create_task(_compute_and_store())
            self._inflight[inflight_key] = task

            def _clear_inflight(done_task: "asyncio.Task[Any]") -> None:
                if self._inflight.get(inflight_key) is done_task:
                    self._inflight.pop(inflight_key, None)

            task.add_done_callback(_clear_inflight)

        return await asyncio.shield(task)


_idem_cache = _IdempotencyCache()


def _make_request_fingerprint(body: Dict[str, Any], keys: List[str]) -> str:
    from hashlib import sha256
    subset = {k: body.get(k) for k in keys}
    return sha256(repr(subset).encode("utf-8")).hexdigest()


def _new_chat_session_id() -> str:
    """Return an unguessable API chat session ID for a new transcript."""
    return f"api-{uuid.uuid4().hex}"


_CRON_AVAILABLE = False
try:
    from cron.jobs import (
        list_jobs as _cron_list,
        get_job as _cron_get,
        create_job as _cron_create,
        update_job as _cron_update,
        remove_job as _cron_remove,
        pause_job as _cron_pause,
        resume_job as _cron_resume,
        trigger_job as _cron_trigger,
    )
    _CRON_AVAILABLE = True
except ImportError:
    _cron_list = None
    _cron_get = None
    _cron_create = None
    _cron_update = None
    _cron_remove = None
    _cron_pause = None
    _cron_resume = None
    _cron_trigger = None


class APIServerAdapter(BasePlatformAdapter):
    """
    OpenAI-compatible HTTP API server adapter.

    Runs an aiohttp web server that accepts OpenAI-format requests
    and routes them through hermes-agent's AIAgent.
    """

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.API_SERVER)
        extra = config.extra or {}
        self._host: str = extra.get("host", os.getenv("API_SERVER_HOST", DEFAULT_HOST))
        raw_port = extra.get("port")
        if raw_port is None:
            raw_port = os.getenv("API_SERVER_PORT", str(DEFAULT_PORT))
        self._port: int = _coerce_port(raw_port, DEFAULT_PORT)
        self._api_key: str = extra.get("key", os.getenv("API_SERVER_KEY", ""))
        self._api_key_usable: bool = has_usable_secret(self._api_key, min_length=1)
        self._cors_origins: tuple[str, ...] = self._parse_cors_origins(
            extra.get("cors_origins", os.getenv("API_SERVER_CORS_ORIGINS", "")),
        )
        self._model_name: str = self._resolve_model_name(
            extra.get("model_name", os.getenv("API_SERVER_MODEL_NAME", "")),
        )
        self._app: Optional["web.Application"] = None
        self._runner: Optional["web.AppRunner"] = None
        self._site: Optional["web.TCPSite"] = None
        self._response_store = ResponseStore()
        self._run_streams: Dict[str, "asyncio.Queue[Optional[Dict]]"] = {}
        self._run_streams_created: Dict[str, float] = {}
        self._active_run_agents: Dict[str, Any] = {}
        self._active_run_tasks: Dict[str, "asyncio.Task"] = {}
        self._run_statuses: Dict[str, Dict[str, Any]] = {}
        self._run_approval_sessions: Dict[str, str] = {}
        self._session_db: Optional[Any] = None

    @staticmethod
    def _parse_cors_origins(value: Any) -> tuple[str, ...]:
        """Normalize configured CORS origins into a stable tuple."""
        if not value:
            return ()
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = [str(value)]
        return tuple(str(item).strip() for item in items if str(item).strip())

    @staticmethod
    def _resolve_model_name(explicit: str) -> str:
        """Derive the advertised model name for /v1/models."""
        if explicit and explicit.strip():
            return explicit.strip()
        try:
            from hermes_cli.profiles import get_active_profile_name
            profile = get_active_profile_name()
            if profile and profile not in {"default", "custom"}:
                return profile
        except Exception:
            pass
        return "hermes-agent"

    def _cors_headers_for_origin(self, origin: str) -> Optional[Dict[str, str]]:
        """Return CORS headers for an allowed browser origin."""
        if not origin or not self._cors_origins:
            return None
        if "*" in self._cors_origins:
            headers = dict(_CORS_HEADERS)
            headers["Access-Control-Allow-Origin"] = "*"
            headers["Access-Control-Max-Age"] = "600"
            return headers
        if origin not in self._cors_origins:
            return None
        headers = dict(_CORS_HEADERS)
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
        headers["Access-Control-Max-Age"] = "600"
        return headers

    def _origin_allowed(self, origin: str) -> bool:
        """Allow non-browser clients and explicitly configured browser origins."""
        if not origin:
            return True
        if not self._cors_origins:
            return False
        return "*" in self._cors_origins or origin in self._cors_origins

    def _check_auth(self, request: "web.Request") -> Optional["web.Response"]:
        """
        Validate Bearer token from Authorization header.

        Returns None if auth is OK, or a 401 web.Response on failure.
        If no API key is configured, all requests are allowed (only when API
        server is local).
        """
        if not self._api_key:
            return None
        if not self._api_key_usable:
            logger.warning("[%s] Rejecting request: configured API key is a placeholder", self.name)
            return web.json_response(
                {"error": {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}},
                status=401,
            )
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if hmac.compare_digest(token, self._api_key):
                return None
        return web.json_response(
            {"error": {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}},
            status=401,
        )

    _MAX_SESSION_HEADER_LEN = 256
    _API_SESSION_KEY_PREFIX = "api-server"

    def _api_session_scope_key(self, raw: str) -> str:
        """Return a deterministic API-server-only memory scope key."""
        scope_digest = hmac.new(
            self._api_key.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{self._API_SESSION_KEY_PREFIX}-{scope_digest}"

    def _parse_session_key_header(
        self, request: "web.Request"
    ) -> tuple[Optional[str], Optional["web.Response"]]:
        """Extract and validate the ``X-Hermes-Session-Key`` header."""
        raw = request.headers.get("X-Hermes-Session-Key", "").strip()
        if not raw:
            return None, None
        if not self._api_key:
            logger.warning("X-Hermes-Session-Key rejected: no API key configured. Set API_SERVER_KEY to enable long-term memory scoping.")
            return None, web.json_response(
                _openai_error("X-Hermes-Session-Key requires API key authentication. Configure API_SERVER_KEY to enable this feature."),
                status=403,
            )
        if re.search(r'[\r\n\x00]', raw):
            return None, web.json_response(
                {"error": {"message": "Invalid session key", "type": "invalid_request_error"}},
                status=400,
            )
        if len(raw) > self._MAX_SESSION_HEADER_LEN:
            return None, web.json_response(
                {"error": {"message": "Session key too long", "type": "invalid_request_error"}},
                status=400,
            )
        return self._api_session_scope_key(raw), None

    def _ensure_session_db(self):
        """Lazily initialise and return the shared SessionDB instance."""
        if self._session_db is None:
            try:
                from hermes_state import SessionDB
                self._session_db = SessionDB()
            except Exception as e:
                logger.debug("SessionDB unavailable for API server: %s", e)
        return self._session_db

    def _create_agent(
        self,
        ephemeral_system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        stream_delta_callback=None,
        tool_progress_callback=None,
        tool_start_callback=None,
        tool_complete_callback=None,
        gateway_session_key: Optional[str] = None,
        origin_platform: Optional[str] = None,
        enabled_toolsets_override: Optional[List[str]] = None,
    ) -> Any:
        """
        Create an AIAgent instance using the gateway's runtime config.
        """
        from run_agent import AIAgent
        from gateway.run import _resolve_runtime_agent_kwargs, _resolve_gateway_model, _load_gateway_config, GatewayRunner
        from hermes_cli.tools_config import _get_platform_tools

        runtime_kwargs = _resolve_runtime_agent_kwargs()
        reasoning_config = GatewayRunner._load_reasoning_config()
        model = _resolve_gateway_model()

        user_config = _load_gateway_config()
        if enabled_toolsets_override is None:
            platform_key = origin_platform or "api_server"
            enabled_toolsets = sorted(_get_platform_tools(user_config, platform_key))
        else:
            enabled_toolsets = sorted(str(ts) for ts in enabled_toolsets_override)

        max_iterations = int(os.getenv("HERMES_MAX_ITERATIONS", "90"))
        fallback_model = GatewayRunner._load_fallback_model()
        effective_gateway_session_key = gateway_session_key or session_id

        agent = AIAgent(
            model=model,
            **runtime_kwargs,
            max_iterations=max_iterations,
            quiet_mode=True,
            verbose_logging=False,
            ephemeral_system_prompt=ephemeral_system_prompt or None,
            enabled_toolsets=enabled_toolsets,
            session_id=session_id,
            platform=origin_platform or "api_server",
            stream_delta_callback=stream_delta_callback,
            tool_progress_callback=tool_progress_callback,
            tool_start_callback=tool_start_callback,
            tool_complete_callback=tool_complete_callback,
            session_db=self._ensure_session_db(),
            fallback_model=fallback_model,
            reasoning_config=reasoning_config,
            gateway_session_key=effective_gateway_session_key,
        )
        return agent

    async def _handle_health(self, request: "web.Request") -> "web.Response":
        """GET /health — simple health check."""
        return web.json_response({"status": "ok", "platform": "hermes-agent"})

    async def _handle_health_detailed(self, request: "web.Request") -> "web.Response":
        """GET /health/detailed — rich status for cross-container dashboard probing."""
        from gateway.status import read_runtime_status
        runtime = read_runtime_status() or {}
        return web.json_response({
            "status": "ok",
            "platform": "hermes-agent",
            "gateway_state": runtime.get("gateway_state"),
            "platforms": runtime.get("platforms", {}),
            "active_agents": runtime.get("active_agents", 0),
            "exit_reason": runtime.get("exit_reason"),
            "updated_at": runtime.get("updated_at"),
            "pid": os.getpid(),
        })

    async def _handle_models(self, request: "web.Request") -> "web.Response":
        """GET /v1/models — return hermes-agent as an available model."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        return web.json_response({
            "object": "list",
            "data": [{"id": self._model_name, "object": "model", "created": int(time.time()), "owned_by": "hermes", "permission": [], "root": self._model_name, "parent": None}],
        })

    async def _handle_capabilities(self, request: "web.Request") -> "web.Response":
        """GET /v1/capabilities — advertise the stable API surface."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        return web.json_response({
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "model": self._model_name,
            "auth": {"type": "bearer", "required": bool(self._api_key)},
            "runtime": {"mode": "server_agent", "tool_execution": "server", "split_runtime": False, "description": "The API server creates a server-side Hermes AIAgent; tools execute on the API-server host unless a future explicit split-runtime mode is enabled."},
            "features": {"chat_completions": True, "chat_completions_streaming": True, "responses_api": True, "responses_streaming": True, "run_submission": True, "run_status": True, "run_events_sse": True, "run_stop": True, "run_approval_response": True, "tool_progress_events": True, "approval_events": True, "session_continuity_header": "X-Hermes-Session-Id", "session_key_header": "X-Hermes-Session-Key", "cors": bool(self._cors_origins)},
            "endpoints": {"health": {"method": "GET", "path": "/health"}, "health_detailed": {"method": "GET", "path": "/health/detailed"}, "models": {"method": "GET", "path": "/v1/models"}, "chat_completions": {"method": "POST", "path": "/v1/chat/completions"}, "responses": {"method": "POST", "path": "/v1/responses"}, "runs": {"method": "POST", "path": "/v1/runs"}, "run_status": {"method": "GET", "path": "/v1/runs/{run_id}"}, "run_events": {"method": "GET", "path": "/v1/runs/{run_id}/events"}, "run_approval": {"method": "POST", "path": "/v1/runs/{run_id}/approval"}, "run_stop": {"method": "POST", "path": "/v1/runs/{run_id}/stop"}},
        })

    async def _handle_chat_completions(self, request: "web.Request") -> "web.Response":
        """POST /v1/chat/completions — OpenAI Chat Completions format."""
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(_openai_error("Invalid JSON in request body"), status=400)
        messages = body.get("messages")
        if not messages or not isinstance(messages, list):
            return web.json_response({"error": {"message": "Missing or invalid 'messages' field", "type": "invalid_request_error"}}, status=400)
        stream = body.get("stream", False)
        proxy_scope = body.get("hermes_proxy_scope")
        origin_platform = None
        enabled_toolsets_override = None
        if proxy_scope is not None:
            if not isinstance(proxy_scope, dict):
                return web.json_response(_openai_error("Invalid hermes_proxy_scope"), status=400)
            raw_platform = proxy_scope.get("origin_platform")
            if raw_platform is not None:
                origin_platform = str(raw_platform).strip()
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", origin_platform):
                    return web.json_response(_openai_error("Invalid hermes_proxy_scope.origin_platform"), status=400)
            raw_toolsets = proxy_scope.get("enabled_toolsets")
            if raw_toolsets is not None:
                if not isinstance(raw_toolsets, list) or not all(isinstance(ts, str) for ts in raw_toolsets):
                    return web.json_response(_openai_error("Invalid hermes_proxy_scope.enabled_toolsets"), status=400)
                enabled_toolsets_override = [ts for ts in raw_toolsets if ts]
        system_prompt = None
        conversation_messages: List[Dict[str, str]] = []
        for idx, msg in enumerate(messages):
            role = msg.get("role", "")
            raw_content = msg.get("content", "")
            if role == "system":
                content = _normalize_chat_content(raw_content)
                if system_prompt is None:
                    system_prompt = content
                else:
                    system_prompt = system_prompt + "\n" + content
            elif role in {"user", "assistant"}:
                try:
                    content = _normalize_multimodal_content(raw_content)
                except ValueError as exc:
                    return _multimodal_validation_error(exc, param=f"messages[{idx}].content")
                conversation_messages.append({"role": role, "content": content})
        user_message: Any = ""
        history = []
        if conversation_messages:
            user_message = conversation_messages[-1].get("content", "")
            history = conversation_messages[:-1]
        if not _content_has_visible_payload(user_message):
            return web.json_response({"error": {"message": "No user message found in messages", "type": "invalid_request_error"}}, status=400)
        gateway_session_key, key_err = self._parse_session_key_header(request)
        if key_err is not None:
            return key_err
        provided_session_id = request.headers.get("X-Hermes-Session-Id", "").strip()
        if provided_session_id:
            if not self._api_key:
                logger.warning("Session continuation via X-Hermes-Session-Id rejected: no API key configured.  Set API_SERVER_KEY to enable session continuity.")
                return web.json_response(_openai_error("Session continuation requires API key authentication. Configure API_SERVER_KEY to enable this feature."), status=403)
            if re.search(r'[\r\n\x00]', provided_session_id):
                return web.json_response({"error": {"message": "Invalid session ID", "type": "invalid_request_error"}}, status=400)
            session_id = provided_session_id
            try:
                db = self._ensure_session_db()
                if db is not None:
                    history = db.get_messages_as_conversation(session_id)
            except Exception as e:
                logger.warning("Failed to load session history for %s: %s", session_id, e)
                history = []
        else:
            session_id = _new_chat_session_id()
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
        model_name = body.get("model", self._model_name)
        created = int(time.time())
        if stream:
            import queue as _q
            _stream_q: _q.Queue = _q.Queue()
            def _on_delta(delta):
                if delta is not None:
                    _stream_q.put(delta)
            _started_tool_call_ids: set[str] = set()
            def _on_tool_start(tool_call_id, function_name, function_args):
                if not tool_call_id or function_name.startswith("_"):
                    return
                _started_tool_call_ids.add(tool_call_id)
                from agent.display import build_tool_preview, get_tool_emoji
                label = build_tool_preview(function_name, function_args) or function_name
                _stream_q.put(("__tool_progress__", {"tool": function_name, "emoji": get_tool_emoji(function_name), "label": label, "toolCallId": tool_call_id, "status": "running"}))
            def _on_tool_complete(tool_call_id, function_name, function_args, function_result):
                if not tool_call_id or tool_call_id not in _started_tool_call_ids:
                    return
                _started_tool_call_ids.discard(tool_call_id)
                _stream_q.put(("__tool_progress__", {"tool": function_name, "toolCallId": tool_call_id, "status": "completed"}))
            agent_ref = [None]
            agent_task = asyncio.ensure_future(self._run_agent(
                user_message=user_message,
                conversation_history=history,
                ephemeral_system_prompt=system_prompt,
                session_id=session_id,
                stream_delta_callback=_on_delta,
                tool_start_callback=_on_tool_start,
                tool_complete_callback=_on_tool_complete,
                agent_ref=agent_ref,
                gateway_session_key=gateway_session_key,
                origin_platform=origin_platform,
                enabled_toolsets_override=enabled_toolsets_override,
            ))
            return await self._write_sse_chat_completion(
                request, completion_id, model_name, created, _stream_q,
                agent_task, agent_ref, session_id=session_id,
                gateway_session_key=gateway_session_key,
            )
        async def _compute_completion():
            return await self._run_agent(
                user_message=user_message,
                conversation_history=history,
                ephemeral_system_prompt=system_prompt,
                session_id=session_id,
                gateway_session_key=gateway_session_key,
                origin_platform=origin_platform,
                enabled_toolsets_override=enabled_toolsets_override,
            )
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key:
            fp = _make_request_fingerprint(body, keys=["model", "messages", "tools", "tool_choice", "stream"])
            try:
                result, usage = await _idem_cache.get_or_set(idempotency_key, fp, _compute_completion)
            except Exception as e:
                logger.error("Error running agent for chat completions: %s", e, exc_info=True)
                return web.json_response(_openai_error(f"Internal server error: {e}", err_type="server_error"), status=500)
        else:
            try:
                result, usage = await _compute_completion()
            except Exception as e:
                logger.error("Error running agent for chat completions: %s", e, exc_info=True)
                return web.json_response(_openai_error(f"Internal server error: {e}", err_type="server_error"), status=500)
        final_response = result.get("final_response") or ""
        is_partial = bool(result.get("partial"))
        is_failed = bool(result.get("failed"))
        completed = bool(result.get("completed", True))
        err_msg = result.get("error")
        if is_partial and err_msg and "truncat" in err_msg.lower():
            finish_reason = "length"
        elif is_failed or (not completed and err_msg):
            finish_reason = "error"
        else:
            finish_reason = "stop"
        response_headers = {"X-Hermes-Session-Id": result.get("session_id", session_id)}
        if gateway_session_key:
            response_headers["X-Hermes-Session-Key"] = gateway_session_key
        if not final_response and (is_failed or is_partial):
            err_body = _openai_error(err_msg or "Agent run did not produce a response.", err_type="server_error", code="agent_incomplete")
            err_body["error"]["hermes"] = {"completed": completed, "partial": is_partial, "failed": is_failed}
            response_headers["X-Hermes-Completed"] = "false"
            response_headers["X-Hermes-Partial"] = "true" if is_partial else "false"
            return web.json_response(err_body, status=502, headers=response_headers)
        response_data = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": final_response}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("total_tokens", 0)},
        }
        if is_partial or is_failed or not completed:
            response_data["hermes"] = {"completed": completed, "partial": is_partial, "failed": is_failed, "error": err_msg, "error_code": "output_truncated" if finish_reason == "length" else "agent_error"}
            response_headers["X-Hermes-Completed"] = "false"
            response_headers["X-Hermes-Partial"] = "true" if is_partial else "false"
            if err_msg:
                response_headers["X-Hermes-Error"] = err_msg[:200]
        return web.json_response(response_data, headers=response_headers)

    async def _write_sse_chat_completion(
        self, request: "web.Request", completion_id: str, model: str,
        created: int, stream_q, agent_task, agent_ref=None, session_id: str = None,
        gateway_session_key: str = None,
    ) -> "web.StreamResponse":
        """Write real streaming SSE from agent's stream_delta_callback queue."""
        import queue as _q
        sse_headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        origin = request.headers.get("Origin", "")
        cors = self._cors_headers_for_origin(origin) if origin else None
        if cors:
            sse_headers.update(cors)
        if session_id:
            sse_headers["X-Hermes-Session-Id"] = session_id
        if gateway_session_key:
            sse_headers["X-Hermes-Session-Key"] = gateway_session_key
        response = web.StreamResponse(status=200, headers=sse_headers)
        await response.prepare(request)
        try:
            last_activity = time.monotonic()
            role_chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            await response.write(f"data: {json.dumps(role_chunk)}\n\n".encode())
            last_activity = time.monotonic()
            async def _emit(item):
                if isinstance(item, tuple) and len(item) == 2 and item[0] == "__tool_progress__":
                    event_data = json.dumps(item[1])
                    await response.write(f"event: hermes.tool.progress\ndata: {event_data}\n\n".encode())
                else:
                    content_chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"content": item}, "finish_reason": None}]}
                    await response.write(f"data: {json.dumps(content_chunk)}\n\n".encode())
                return time.monotonic()
            loop = asyncio.get_running_loop()
            while True:
                try:
                    delta = await loop.run_in_executor(None, lambda: stream_q.get(timeout=0.5))
                except _q.Empty:
                    if agent_task.done():
                        while True:
                            try:
                                delta = stream_q.get_nowait()
                                if delta is None:
                                    break
                                last_activity = await _emit(delta)
                            except _q.Empty:
                                break
                        break
                    if time.monotonic() - last_activity >= CHAT_COMPLETIONS_SSE_KEEPALIVE_SECONDS:
                        await response.write(b": keepalive\n\n")
                        last_activity = time.monotonic()
                    continue
                if delta is None:
                    break
                last_activity = await _emit(delta)
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            try:
                result, agent_usage = await agent_task
                usage = agent_usage or usage
            except Exception as exc:
                logger.warning("Agent task %s failed, usage data lost: %s", completion_id, exc)
            finish_chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}}
            await response.write(f"data: {json.dumps(finish_chunk)}\n\n".encode())
            await response.write(b"data: [DONE]\n\n")
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            agent = agent_ref[0] if agent_ref else None
            if agent is not None:
                try:
                    agent.interrupt("SSE client disconnected")
                except Exception:
                    pass
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            logger.info("SSE client disconnected; interrupted agent task %s", completion_id)
        except Exception as _exc:
            import traceback as _tb
            logger.error("Agent crashed mid-stream for %s: %s", completion_id, _tb.format_exc()[:300])
            try:
                error_chunk = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}]}
                await response.write(f"data: {json.dumps(error_chunk)}\n\n".encode())
                await response.write(b"data: [DONE]\n\n")
            except Exception:
                pass
        return response

    async def _write_sse_responses(
        self,
        request: "web.Request",
        response_id: str,
        model: str,
        created_at: int,
        stream_q,
        agent_task,
        agent_ref,
        conversation_history: List[Dict[str, str]],
        user_message: str,
        instructions: Optional[str],
        conversation: Optional[str],
        store: bool,
        session_id: str,
        gateway_session_key: Optional[str] = None,
    ) -> "web.StreamResponse":
        """Write an SSE stream for POST /v1/responses (OpenAI Responses API)."""
        import queue as _q
        sse_headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        origin = request.headers.get("Origin", "")
        cors = self._cors_headers_for_origin(origin) if origin else None
        if cors:
            sse_headers.update(cors)
        if session_id:
            sse_headers["X-Hermes-Session-Id"] = session_id
        if gateway_session_key:
            sse_headers["X-Hermes-Session-Key"] = gateway_session_key
        response = web.StreamResponse(status=200, headers=sse_headers)
        await response.prepare(request)
        final_text_parts: List[str] = []
        pending_tool_calls: List[Dict[str, Any]] = []
        emitted_items: List[Dict[str, Any]] = []
        output_index = 0
        call_counter = 0
        sequence_number = 0
        message_item_id = f"msg_{uuid.uuid4().hex[:24]}"
        message_output_index: Optional[int] = None
        message_opened = False
        async def _write_event(event_type: str, data: Dict[str, Any]) -> None:
            nonlocal sequence_number
            if "sequence_number" not in data:
                data["sequence_number"] = sequence_number
            sequence_number += 1
            payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            await response.write(payload.encode())
        def _envelope(status: str) -> Dict[str, Any]:
            env: Dict[str, Any] = {"id": response_id, "object": "response", "status": status, "created_at": created_at, "model": model}
            return env
        final_response_text = ""
        agent_error: Optional[str] = None
        usage: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        terminal_snapshot_persisted = False
        def _persist_response_snapshot(response_env, *, conversation_history_snapshot=None):
            if not store:
                return
            if conversation_history_snapshot is None:
                conversation_history_snapshot = list(conversation_history)
                conversation_history_snapshot.append({"role": "user", "content": user_message})
            self._response_store.put(response_id, {"response": response_env, "conversation_history": conversation_history_snapshot, "instructions": instructions, "session_id": session_id})
            if conversation:
                self._response_store.set_conversation(conversation, response_id)
        def _persist_incomplete_if_needed():
            if not store or terminal_snapshot_persisted:
                return
            incomplete_text = "".join(final_text_parts) or final_response_text
            incomplete_items = list(emitted_items)
            if incomplete_text:
                incomplete_items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": incomplete_text}]})
            incomplete_env = _envelope("incomplete")
            incomplete_env["output"] = incomplete_items
            incomplete_env["usage"] = {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
            incomplete_history = list(conversation_history)
            incomplete_history.append({"role": "user", "content": user_message})
            if incomplete_text:
                incomplete_history.append({"role": "assistant", "content": incomplete_text})
            _persist_response_snapshot(incomplete_env, conversation_history_snapshot=incomplete_history)
        try:
            created_env = _envelope("in_progress")
            created_env["output"] = []
            await _write_event("response.created", {"type": "response.created", "response": created_env})
            _persist_response_snapshot(created_env)
            last_activity = time.monotonic()
            async def _open_message_item():
                nonlocal message_opened, message_output_index, output_index
                if message_opened:
                    return
                message_opened = True
                message_output_index = output_index
                output_index += 1
                item = {"id": message_item_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}
                await _write_event("response.output_item.added", {"type": "response.output_item.added", "output_index": message_output_index, "item": item})
            async def _emit_text_delta(delta_text: str) -> None:
                await _open_message_item()
                final_text_parts.append(delta_text)
                await _write_event("response.output_text.delta", {"type": "response.output_text.delta", "item_id": message_item_id, "output_index": message_output_index, "content_index": 0, "delta": delta_text, "logprobs": []})
            async def _emit_tool_started(payload) -> str:
                nonlocal output_index, call_counter
                call_counter += 1
                call_id = payload.get("tool_call_id") or f"call_{response_id[5:]}_{call_counter}"
                args = payload.get("arguments", {})
                arguments_str = json.dumps(args) if isinstance(args, dict) else str(args)
                item = {"id": f"fc_{uuid.uuid4().hex[:24]}", "type": "function_call", "status": "in_progress", "name": payload.get("name", ""), "call_id": call_id, "arguments": arguments_str}
                idx = output_index
                output_index += 1
                pending_tool_calls.append({"call_id": call_id, "name": payload.get("name", ""), "arguments": arguments_str, "item_id": item["id"], "output_index": idx})
                emitted_items.append({"type": "function_call", "name": payload.get("name", ""), "arguments": arguments_str, "call_id": call_id})
                await _write_event("response.output_item.added", {"type": "response.output_item.added", "output_index": idx, "item": item})
                return call_id
            async def _emit_tool_completed(payload) -> None:
                nonlocal output_index
                call_id = payload.get("tool_call_id")
                result = payload.get("result", "")
                pending = None
                if call_id:
                    for i, p in enumerate(pending_tool_calls):
                        if p["call_id"] == call_id:
                            pending = pending_tool_calls.pop(i)
                            break
                if pending is None:
                    return
                done_item = {"id": pending["item_id"], "type": "function_call", "status": "completed", "name": pending["name"], "call_id": pending["call_id"], "arguments": pending["arguments"]}
                await _write_event("response.output_item.done", {"type": "response.output_item.done", "output_index": pending["output_index"], "item": done_item})
                result_str = result if isinstance(result, str) else json.dumps(result)
                output_parts = [{"type": "input_text", "text": result_str}]
                output_item = {"id": f"fco_{uuid.uuid4().hex[:24]}", "type": "function_call_output", "call_id": pending["call_id"], "output": output_parts, "status": "completed"}
                idx = output_index
                output_index += 1
                emitted_items.append({"type": "function_call_output", "call_id": pending["call_id"], "output": output_parts})
                await _write_event("response.output_item.added", {"type": "response.output_item.added", "output_index": idx, "item": output_item})
                await _write_event("response.output_item.done", {"type": "response.output_item.done", "output_index": idx, "item": output_item})
            async def _dispatch(it) -> None:
                nonlocal _batch_timer
                if isinstance(it, tuple) and len(it) == 2 and isinstance(it[0], str):
                    tag, payload = it
                    if _batch_buf:
                        await _flush_batch()
                    if tag == "__tool_started__":
                        await _emit_tool_started(payload)
                    elif tag == "__tool_completed__":
                        await _emit_tool_completed(payload)
                elif isinstance(it, str):
                    _batch_buf.append(it)
                    if _batch_timer is None:
                        _batch_timer = asyncio.create_task(_batch_flush_after(0.05))
            _batch_buf: List[str] = []
            _batch_timer: Optional[asyncio.Task] = None
            _batch_lock = asyncio.Lock()
            async def _batch_flush_after(delay: float) -> None:
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                nonlocal _batch_buf, _batch_timer
                _batch_timer = None
                await _flush_batch()
            async def _flush_batch() -> None:
                nonlocal _batch_buf
                async with _batch_lock:
                    if _batch_buf:
                        combined = "".join(_batch_buf)
                        _batch_buf = []
                        await _emit_text_delta(combined)
            loop = asyncio.get_running_loop()
            while True:
                try:
                    item = await loop.run_in_executor(None, lambda: stream_q.get(timeout=0.5))
                except _q.Empty:
                    if agent_task.done():
                        while True:
                            try:
                                item = stream_q.get_nowait()
                                if item is None:
                                    break
                                await _dispatch(item)
                                last_activity = time.monotonic()
                            except _q.Empty:
                                break
                        break
                    if time.monotonic() - last_activity >= CHAT_COMPLETIONS_SSE_KEEPALIVE_SECONDS:
                        await response.write(b": keepalive\n\n")
                        last_activity = time.monotonic()
                    continue
                if item is None:
                    if _batch_timer and not _batch_timer.done():
                        _batch_timer.cancel()
                        _batch_timer = None
                    if _batch_buf:
                        await _flush_batch()
                    break
                await _dispatch(item)
                last_activity = time.monotonic()
            if _batch_buf:
                await _flush_batch()
            try:
                result, agent_usage = await agent_task
                usage = agent_usage or usage
                agent_final = result.get("final_response", "") if isinstance(result, dict) else ""
                if agent_final and not final_text_parts:
                    await _emit_text_delta(agent_final)
                if agent_final and not final_response_text:
                    final_response_text = agent_final
                if isinstance(result, dict) and result.get("error") and not final_response_text:
                    agent_error = result["error"]
            except Exception as e:
                logger.error("Error running agent for streaming responses: %s", e, exc_info=True)
                agent_error = str(e)
            final_response_text = "".join(final_text_parts) or final_response_text
            if message_opened:
                await _write_event("response.output_text.done", {"type": "response.output_text.done", "item_id": message_item_id, "output_index": message_output_index, "content_index": 0, "text": final_response_text, "logprobs": []})
                msg_done_item = {"id": message_item_id, "type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": final_response_text}]}
                await _write_event("response.output_item.done", {"type": "response.output_item.done", "output_index": message_output_index, "item": msg_done_item})
            final_items: List[Dict[str, Any]] = list(emitted_items)
            for _item in final_items:
                if _item.get("type") == "function_call":
                    try:
                        _args = json.loads(_item.get("arguments", "{}")) if isinstance(_item.get("arguments"), str) else _item.get("arguments", {})
                        if isinstance(_args, dict):
                            for _k in ("content", "query", "pattern", "old_string", "new_string"):
                                if isinstance(_args.get(_k), str) and len(_args[_k]) > 500:
                                    _args[_k] = "[" + str(len(_args[_k])) + " chars — truncated for response.completed]"
                            _item["arguments"] = json.dumps(_args)
                    except Exception:
                        pass
                elif _item.get("type") == "function_call_output":
                    _output = _item.get("output", [])
                    if isinstance(_output, list) and _output:
                        _first = _output[0]
                        if isinstance(_first, dict) and _first.get("type") == "input_text":
                            _text = _first.get("text", "")
                            if len(_text) > 1000:
                                _first["text"] = _text[:500] + "...[" + str(len(_text) - 500) + " more chars]"
                                _item["output"] = [_first]
            final_items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": final_response_text or (agent_error or "")}]})
            if agent_error:
                failed_env = _envelope("failed")
                failed_env["output"] = final_items
                failed_env["error"] = {"message": agent_error, "type": "server_error"}
                failed_env["usage"] = {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
                _failed_history = list(conversation_history)
                _failed_history.append({"role": "user", "content": user_message})
                if final_response_text or agent_error:
                    _failed_history.append({"role": "assistant", "content": final_response_text or agent_error})
                _persist_response_snapshot(failed_env, conversation_history_snapshot=_failed_history)
                terminal_snapshot_persisted = True
                await _write_event("response.failed", {"type": "response.failed", "response": failed_env})
            else:
                completed_env = _envelope("completed")
                completed_env["output"] = final_items
                completed_env["usage"] = {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
                full_history = self._build_response_conversation_history(conversation_history, user_message, result, final_response_text)
                _persist_response_snapshot(completed_env, conversation_history_snapshot=full_history)
                terminal_snapshot_persisted = True
                await _write_event("response.completed", {"type": "response.completed", "response": completed_env})
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            _persist_incomplete_if_needed()
            agent = agent_ref[0] if agent_ref else None
            if agent is not None:
                try:
                    agent.interrupt("SSE client disconnected")
                except Exception:
                    pass
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            logger.info("SSE client disconnected; interrupted agent task %s", response_id)
        except asyncio.CancelledError:
            _persist_incomplete_if_needed()
            agent = agent_ref[0] if agent_ref else None
            if agent is not None:
                try:
                    agent.interrupt("SSE task cancelled")
                except Exception:
                    pass
            if not agent_task.done():
                agent_task.cancel()
            logger.info("SSE task cancelled; persisted incomplete snapshot for %s", response_id)
            raise
        except Exception as _exc:
            import traceback as _tb
            _persist_incomplete_if_needed()
            agent_error = _tb.format_exc()
            try:
                failed_env = _envelope("failed")
                failed_env["output"] = list(emitted_items)
                failed_env["error"] = {"message": str(_exc)[:500], "type": "server_error"}
                failed_env["usage"] = {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}
                await _write_event("response.failed", {"type": "response.failed", "response": failed_env})
            except Exception:
                pass
            logger.error("Agent crashed mid-stream for %s: %s", response_id, str(agent_error)[:300])
        return response

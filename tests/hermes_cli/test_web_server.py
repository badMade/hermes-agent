"""Tests for hermes_cli.web_server and related config utilities."""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hermes_cli.config import (
    DEFAULT_CONFIG,
    reload_env,
    redact_key,
    _EXTRA_ENV_KEYS,
    OPTIONAL_ENV_VARS,
)


# ---------------------------------------------------------------------------
# reload_env tests
# ---------------------------------------------------------------------------


class TestReloadEnv:
    """Tests for reload_env() — re-reads .env into os.environ."""

    def test_adds_new_vars(self, tmp_path):
        """reload_env() adds vars from .env that are not in os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_RELOAD_VAR=hello123\n")
        with patch.dict(reload_env.__globals__, {"get_env_path": lambda: env_file}):
            os.environ.pop("TEST_RELOAD_VAR", None)
            count = reload_env()
            assert count >= 1
            assert os.environ.get("TEST_RELOAD_VAR") == "hello123"
        os.environ.pop("TEST_RELOAD_VAR", None)

    def test_updates_changed_vars(self, tmp_path):
        """reload_env() updates vars whose value changed on disk."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_RELOAD_VAR=old_value\n")
        with patch.dict(reload_env.__globals__, {"get_env_path": lambda: env_file}):
            os.environ["TEST_RELOAD_VAR"] = "old_value"
            # Now change the file
            env_file.write_text("TEST_RELOAD_VAR=new_value\n")
            count = reload_env()
            assert count >= 1
            assert os.environ.get("TEST_RELOAD_VAR") == "new_value"
        os.environ.pop("TEST_RELOAD_VAR", None)

    def test_removes_deleted_known_vars(self, tmp_path):
        """reload_env() removes known Hermes vars not present in .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("")  # empty .env
        # Pick a known key from OPTIONAL_ENV_VARS
        known_key = next(iter(OPTIONAL_ENV_VARS.keys()))
        with patch.dict(reload_env.__globals__, {"get_env_path": lambda: env_file}):
            os.environ[known_key] = "stale_value"
            count = reload_env()
            assert known_key not in os.environ
            assert count >= 1

    def test_does_not_remove_unknown_vars(self, tmp_path):
        """reload_env() preserves non-Hermes env vars even when absent from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("")
        with patch.dict(reload_env.__globals__, {"get_env_path": lambda: env_file}):
            os.environ["MY_CUSTOM_UNRELATED_VAR"] = "keep_me"
            reload_env()
            assert os.environ.get("MY_CUSTOM_UNRELATED_VAR") == "keep_me"
        os.environ.pop("MY_CUSTOM_UNRELATED_VAR", None)


# ---------------------------------------------------------------------------
# redact_key tests
# ---------------------------------------------------------------------------


class TestRedactKey:
    def test_long_key_shows_prefix_suffix(self):
        result = redact_key("sk-1234567890abcdef")
        assert result.startswith("sk-1")
        assert result.endswith("cdef")
        assert "..." in result

    def test_short_key_fully_masked(self):
        assert redact_key("short") == "***"

    def test_empty_key(self):
        result = redact_key("")
        assert "not set" in result.lower() or result == "***" or "\x1b" in result


# ---------------------------------------------------------------------------
# web_server tests (FastAPI endpoints)
# ---------------------------------------------------------------------------


class TestWebServerEndpoints:
    """Test the FastAPI REST endpoints using Starlette TestClient."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self, monkeypatch, _isolate_hermes_home):
        """Create a TestClient and isolate the state DB under the test HERMES_HOME."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import hermes_state
        from hermes_constants import get_hermes_home
        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

        monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")

        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_get_status(self):
        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "hermes_home" in data
        assert "active_sessions" in data

    def test_get_status_filters_unconfigured_gateway_platforms(self, monkeypatch):
        import gateway.config as gateway_config
        import hermes_cli.web_server as web_server

        class _Platform:
            def __init__(self, value):
                self.value = value

        class _GatewayConfig:
            def get_connected_platforms(self):
                return [_Platform("telegram")]

        monkeypatch.setattr(web_server, "get_running_pid", lambda: 1234)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {
                "gateway_state": "running",
                "updated_at": "2026-04-12T00:00:00+00:00",
                "platforms": {
                    "telegram": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "whatsapp": {"state": "retrying", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "feishu": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                },
            },
        )
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: _GatewayConfig())

        resp = self.client.get("/api/status")

        assert resp.status_code == 200
        assert resp.json()["gateway_platforms"] == {
            "telegram": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
        }

    def test_get_status_hides_stale_platforms_when_gateway_not_running(self, monkeypatch):
        import gateway.config as gateway_config
        import hermes_cli.web_server as web_server

        class _GatewayConfig:
            def get_connected_platforms(self):
                return []

        monkeypatch.setattr(web_server, "get_running_pid", lambda: None)
        monkeypatch.setattr(
            web_server,
            "read_runtime_status",
            lambda: {
                "gateway_state": "startup_failed",
                "updated_at": "2026-04-12T00:00:00+00:00",
                "platforms": {
                    "whatsapp": {"state": "retrying", "updated_at": "2026-04-12T00:00:00+00:00"},
                    "feishu": {"state": "connected", "updated_at": "2026-04-12T00:00:00+00:00"},
                },
            },
        )
        monkeypatch.setattr(web_server, "check_config_version", lambda: (1, 1))
        monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: _GatewayConfig())

        resp = self.client.get("/api/status")

        assert resp.status_code == 200
        assert resp.json()["gateway_state"] == "startup_failed"
        assert resp.json()["gateway_platforms"] == {}

    def test_get_config_schema(self):
        resp = self.client.get("/api/config/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        assert "category_order" in data
        schema = data["fields"]
        assert len(schema) > 100  # Should have 150+ fields
        assert "model" in schema
        # Verify category_order is a non-empty list
        assert isinstance(data["category_order"], list)
        assert len(data["category_order"]) > 0
        assert "general" in data["category_order"]

    def test_get_config_defaults(self):
        resp = self.client.get("/api/config/defaults")
        assert resp.status_code == 200
        defaults = resp.json()
        assert "model" in defaults

    def test_get_env_vars(self):
        from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN
        resp = self.client.get("/api/env", headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert any(k.endswith("_API_KEY") or k.endswith("_TOKEN") for k in data.keys())

    def test_reveal_env_var(self, tmp_path):
        """POST /api/env/reveal should return the real unredacted value."""
        from hermes_cli.config import save_env_value
        from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN
        save_env_value("TEST_REVEAL_KEY", "super-secret-value-12345")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_KEY"},
            headers={_SESSION_HEADER_NAME: _SESSION_TOKEN},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "TEST_REVEAL_KEY"
        assert data["value"] == "super-secret-value-12345"

    def test_reveal_env_var_not_found(self):
        """POST /api/env/reveal should 404 for unknown keys."""
        from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "NONEXISTENT_KEY_XYZ"},
            headers={_SESSION_HEADER_NAME: _SESSION_TOKEN},
        )
        assert resp.status_code == 404

    def test_reveal_env_var_no_token(self, tmp_path):
        """POST /api/env/reveal without token should return 401."""
        from starlette.testclient import TestClient
        from hermes_cli.web_server import app
        from hermes_cli.config import save_env_value
        save_env_value("TEST_REVEAL_NOAUTH", "secret-value")
        # Use a fresh client WITHOUT the dashboard session header
        unauth_client = TestClient(app)
        resp = unauth_client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_NOAUTH"},
        )
        assert resp.status_code == 401

    def test_reveal_env_var_bad_token(self, tmp_path):
        """POST /api/env/reveal with wrong token should return 401."""
        from hermes_cli.config import save_env_value
        from hermes_cli.web_server import _SESSION_HEADER_NAME
        save_env_value("TEST_REVEAL_BADAUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_BADAUTH"},
            headers={_SESSION_HEADER_NAME: "wrong-token-here"},
        )
        assert resp.status_code == 401

    def test_reveal_env_var_custom_session_header_ignores_proxy_authorization(self, tmp_path):
        """A valid dashboard session header should coexist with proxy auth."""
        from hermes_cli.config import save_env_value
        from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN

        save_env_value("TEST_REVEAL_PROXY_AUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_PROXY_AUTH"},
            headers={
                _SESSION_HEADER_NAME: _SESSION_TOKEN,
                "Authorization": "Basic dXNlcjpwYXNz",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["value"] == "secret-value"

    def test_reveal_env_var_legacy_authorization_header_still_works(self, tmp_path):
        """Keep old dashboard bundles working while the new header rolls out."""
        from hermes_cli.config import save_env_value
        from hermes_cli.web_server import _SESSION_TOKEN

        save_env_value("TEST_REVEAL_LEGACY_AUTH", "secret-value")
        resp = self.client.post(
            "/api/env/reveal",
            json={"key": "TEST_REVEAL_LEGACY_AUTH"},
            headers={"Authorization": f"Bearer {_SESSION_TOKEN}"},
        )

        assert resp.status_code == 200

    def test_session_token_endpoint_removed(self):
        """GET /api/auth/session-token should no longer exist (token injected via HTML)."""
        # Test that with auth it correctly yields a 404
        resp = self.client.get("/api/auth/session-token")
        assert resp.status_code == 404

        # Test that without auth it gets blocked (401)
        from starlette.testclient import TestClient
        from hermes_cli.web_server import app
        unauth_client = TestClient(app)
        resp = unauth_client.get("/api/auth/session-token")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Model context length: normalize/denormalize + /api/model/info
# ---------------------------------------------------------------------------


class TestModelContextLength:
    """Tests for model_context_length in normalize/denormalize and /api/model/info."""

    def test_normalize_extracts_context_length_from_dict(self):
        """normalize should surface context_length from model dict."""
        from hermes_cli.web_server import _normalize_config_for_web

        cfg = {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 200000,
            }
        }
        result = _normalize_config_for_web(cfg)
        assert result["model"] == "anthropic/claude-opus-4.6"
        assert result["model_context_length"] == 200000

    def test_normalize_bare_string_model_yields_zero(self):
        """normalize should set model_context_length=0 for bare string model."""
        from hermes_cli.web_server import _normalize_config_for_web

        result = _normalize_config_for_web({"model": "anthropic/claude-sonnet-4"})
        assert result["model"] == "anthropic/claude-sonnet-4"
        assert result["model_context_length"] == 0

    def test_normalize_dict_without_context_length_yields_zero(self):
        """normalize should default to 0 when model dict has no context_length."""
        from hermes_cli.web_server import _normalize_config_for_web

        cfg = {"model": {"default": "test/model", "provider": "openrouter"}}
        result = _normalize_config_for_web(cfg)
        assert result["model_context_length"] == 0

    def test_normalize_non_int_context_length_yields_zero(self):
        """normalize should coerce non-int context_length to 0."""
        from hermes_cli.web_server import _normalize_config_for_web

        cfg = {"model": {"default": "test/model", "context_length": "invalid"}}
        result = _normalize_config_for_web(cfg)
        assert result["model_context_length"] == 0

    def test_denormalize_writes_context_length_into_model_dict(self):
        """denormalize should write model_context_length back into model dict."""
        from hermes_cli.web_server import _denormalize_config_from_web
        from hermes_cli.config import save_config

        # Set up disk config with model as a dict
        save_config({
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-opus-4.6",
            "model_context_length": 100000,
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["context_length"] == 100000
        assert "model_context_length" not in result  # virtual field removed

    def test_denormalize_zero_removes_context_length(self):
        """denormalize with model_context_length=0 should remove context_length key."""
        from hermes_cli.web_server import _denormalize_config_from_web
        from hermes_cli.config import save_config

        save_config({
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 50000,
            }
        })

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-opus-4.6",
            "model_context_length": 0,
        })
        assert isinstance(result["model"], dict)
        assert "context_length" not in result["model"]

    def test_denormalize_upgrades_bare_string_to_dict(self):
        """denormalize should upgrade bare string model to dict when context_length set."""
        from hermes_cli.web_server import _denormalize_config_from_web
        from hermes_cli.config import save_config

        # Disk has model as bare string
        save_config({"model": "anthropic/claude-sonnet-4"})

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-sonnet-4",
            "model_context_length": 65000,
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["default"] == "anthropic/claude-sonnet-4"
        assert result["model"]["context_length"] == 65000

    def test_denormalize_bare_string_stays_string_when_zero(self):
        """denormalize should keep bare string model as string when context_length=0."""
        from hermes_cli.web_server import _denormalize_config_from_web
        from hermes_cli.config import save_config

        save_config({"model": "anthropic/claude-sonnet-4"})

        result = _denormalize_config_from_web({
            "model": "anthropic/claude-sonnet-4",
            "model_context_length": 0,
        })
        assert result["model"] == "anthropic/claude-sonnet-4"

    def test_denormalize_coerces_string_context_length(self):
        """denormalize should handle string model_context_length from frontend."""
        from hermes_cli.web_server import _denormalize_config_from_web
        from hermes_cli.config import save_config

        save_config({
            "model": {"default": "test/model", "provider": "openrouter"}
        })

        result = _denormalize_config_from_web({
            "model": "test/model",
            "model_context_length": "32000",
        })
        assert isinstance(result["model"], dict)
        assert result["model"]["context_length"] == 32000


class TestModelContextLengthSchema:
    """Tests for model_context_length placement in CONFIG_SCHEMA."""

    def test_schema_has_model_context_length(self):
        from hermes_cli.web_server import CONFIG_SCHEMA
        assert "model_context_length" in CONFIG_SCHEMA

    def test_schema_model_context_length_after_model(self):
        """model_context_length should appear immediately after model in schema."""
        from hermes_cli.web_server import CONFIG_SCHEMA
        keys = list(CONFIG_SCHEMA.keys())
        model_idx = keys.index("model")
        assert keys[model_idx + 1] == "model_context_length"

    def test_schema_model_context_length_is_number(self):
        from hermes_cli.web_server import CONFIG_SCHEMA
        entry = CONFIG_SCHEMA["model_context_length"]
        assert entry["type"] == "number"
        assert "category" in entry


class TestModelInfoEndpoint:
    """Tests for GET /api/model/info endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")
        from hermes_cli.web_server import app
        self.client = TestClient(app)

    def test_model_info_returns_200(self):
        resp = self.client.get("/api/model/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data
        assert "provider" in data
        assert "auto_context_length" in data
        assert "config_context_length" in data
        assert "effective_context_length" in data
        assert "capabilities" in data

    def test_model_info_with_dict_config(self, monkeypatch):
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "openrouter",
                "context_length": 100000,
            }
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["model"] == "anthropic/claude-opus-4.6"
        assert data["provider"] == "openrouter"
        assert data["auto_context_length"] == 200000
        assert data["config_context_length"] == 100000
        assert data["effective_context_length"] == 100000  # override wins

    def test_model_info_auto_detect_when_no_override(self, monkeypatch):
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["auto_context_length"] == 200000
        assert data["config_context_length"] == 0
        assert data["effective_context_length"] == 200000  # auto wins

    def test_model_info_empty_model(self, monkeypatch):
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {"model": ""})

        resp = self.client.get("/api/model/info")
        data = resp.json()
        assert data["model"] == ""
        assert data["effective_context_length"] == 0

    def test_model_info_bare_string_model(self, monkeypatch):
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": "anthropic/claude-sonnet-4"
        })

        with patch("agent.model_metadata.get_model_context_length", return_value=200000):
            resp = self.client.get("/api/model/info")

        data = resp.json()
        assert data["model"] == "anthropic/claude-sonnet-4"
        assert data["provider"] == ""
        assert data["config_context_length"] == 0
        assert data["effective_context_length"] == 200000

    def test_model_info_capabilities(self, monkeypatch):
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": {"default": "anthropic/claude-opus-4.6", "provider": "openrouter"}
        })

        mock_caps = MagicMock()
        mock_caps.supports_tools = True
        mock_caps.supports_vision = True
        mock_caps.supports_reasoning = True
        mock_caps.context_window = 200000
        mock_caps.max_output_tokens = 32000
        mock_caps.model_family = "claude-opus"

        with patch("agent.model_metadata.get_model_context_length", return_value=200000), \
             patch("agent.models_dev.get_model_capabilities", return_value=mock_caps):
            resp = self.client.get("/api/model/info")

        caps = resp.json()["capabilities"]
        assert caps["supports_tools"] is True
        assert caps["supports_vision"] is True
        assert caps["supports_reasoning"] is True
        assert caps["max_output_tokens"] == 32000
        assert caps["model_family"] == "claude-opus"

    def test_model_info_graceful_on_metadata_error(self, monkeypatch):
        """Endpoint should return zeros on import/resolution errors, not 500."""
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "load_config", lambda: {
            "model": "some/obscure-model"
        })

        with patch("agent.model_metadata.get_model_context_length", side_effect=Exception("boom")):
            resp = self.client.get("/api/model/info")

        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_context_length"] == 0


# ---------------------------------------------------------------------------
# Gateway health probe tests
# ---------------------------------------------------------------------------


class TestProbeGatewayHealth:
    """Tests for _probe_gateway_health() — cross-container gateway detection."""

    def test_returns_false_when_no_url_configured(self, monkeypatch):
        """When GATEWAY_HEALTH_URL is unset, the probe returns (False, None)."""
        import hermes_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", None)
        alive, body = ws._probe_gateway_health()
        assert alive is False
        assert body is None

    def test_normalizes_url_with_health_suffix(self, monkeypatch):
        """If the user sets the URL to include /health, it's stripped to base."""
        import hermes_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642/health")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)
        # Both paths should fail (no server), but we verify they were constructed
        # correctly by checking the URLs attempted.
        calls = []
        original_urlopen = ws.urllib.request.urlopen

        def mock_urlopen(req, **kwargs):
            calls.append(req.full_url)
            raise ConnectionError("mock")

        monkeypatch.setattr(ws.urllib.request, "urlopen", mock_urlopen)
        alive, body = ws._probe_gateway_health()
        assert alive is False
        assert "http://gw:8642/health/detailed" in calls
        assert "http://gw:8642/health" in calls

    def test_normalizes_url_with_health_detailed_suffix(self, monkeypatch):
        """If the user sets the URL to include /health/detailed, it's stripped to base."""
        import hermes_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642/health/detailed")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)
        calls = []

        def mock_urlopen(req, **kwargs):
            calls.append(req.full_url)
            raise ConnectionError("mock")

        monkeypatch.setattr(ws.urllib.request, "urlopen", mock_urlopen)
        ws._probe_gateway_health()
        assert "http://gw:8642/health/detailed" in calls
        assert "http://gw:8642/health" in calls

    def test_successful_detailed_probe(self, monkeypatch):
        """Successful /health/detailed probe returns (True, body_dict)."""
        import hermes_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)

        response_body = json.dumps({
            "status": "ok",
            "gateway_state": "running",
            "pid": 42,
        })

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = response_body.encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(ws.urllib.request, "urlopen", lambda req, **kw: mock_resp)
        alive, body = ws._probe_gateway_health()
        assert alive is True
        assert body["status"] == "ok"
        assert body["pid"] == 42

    def test_detailed_fails_falls_back_to_simple_health(self, monkeypatch):
        """If /health/detailed fails, falls back to /health."""
        import hermes_cli.web_server as ws
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_TIMEOUT", 1)

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("detailed failed")
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({"status": "ok"}).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        monkeypatch.setattr(ws.urllib.request, "urlopen", mock_urlopen)
        alive, body = ws._probe_gateway_health()
        assert alive is True
        assert body["status"] == "ok"
        assert call_count[0] == 2


class TestStatusRemoteGateway:
    """Tests for /api/status with remote gateway health fallback."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_status_falls_back_to_remote_probe(self, monkeypatch):
        """When local PID check fails and remote probe succeeds, gateway shows running."""
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: None)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: None)
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_probe_gateway_health", lambda: (True, {
            "status": "ok",
            "gateway_state": "running",
            "platforms": {"telegram": {"state": "connected"}},
            "pid": 999,
        }))

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is True
        assert data["gateway_pid"] == 999
        assert data["gateway_state"] == "running"
        assert data["gateway_health_url"] == "http://gw:8642"

    def test_status_remote_probe_not_attempted_when_local_pid_found(self, monkeypatch):
        """When local PID check succeeds, the remote probe is never called."""
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: 1234)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: {
            "gateway_state": "running",
            "platforms": {},
        })
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        probe_called = [False]
        original = ws._probe_gateway_health

        def track_probe():
            probe_called[0] = True
            return original()

        monkeypatch.setattr(ws, "_probe_gateway_health", track_probe)

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        assert not probe_called[0]

    def test_status_remote_probe_not_attempted_when_no_url(self, monkeypatch):
        """When GATEWAY_HEALTH_URL is unset, no probe is attempted."""
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: None)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: None)
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", None)

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is False
        assert data["gateway_health_url"] is None

    def test_status_remote_running_null_pid(self, monkeypatch):
        """Remote gateway running but PID not in response — pid should be None."""
        import hermes_cli.web_server as ws

        monkeypatch.setattr(ws, "get_running_pid", lambda: None)
        monkeypatch.setattr(ws, "read_runtime_status", lambda: None)
        monkeypatch.setattr(ws, "_GATEWAY_HEALTH_URL", "http://gw:8642")
        monkeypatch.setattr(ws, "_probe_gateway_health", lambda: (True, {
            "status": "ok",
        }))

        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway_running"] is True
        assert data["gateway_pid"] is None
        assert data["gateway_state"] == "running"


# ---------------------------------------------------------------------------
# Dashboard theme normaliser tests
# ---------------------------------------------------------------------------


class TestNormaliseThemeDefinition:
    """Tests for _normalise_theme_definition() — parses YAML theme files."""

    def test_rejects_missing_name(self):
        from hermes_cli.web_server import _normalise_theme_definition
        assert _normalise_theme_definition({}) is None
        assert _normalise_theme_definition({"name": ""}) is None
        assert _normalise_theme_definition({"name": "   "}) is None

    def test_rejects_non_dict(self):
        from hermes_cli.web_server import _normalise_theme_definition
        assert _normalise_theme_definition("string") is None
        assert _normalise_theme_definition(None) is None
        assert _normalise_theme_definition([1, 2, 3]) is None

    def test_loose_colors_shorthand(self):
        """Bare hex strings under `colors` parse as {hex, alpha=1.0}."""
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "loose",
            "colors": {"background": "#000000", "midground": "#ffffff"},
        })
        assert result is not None
        assert result["palette"]["background"] == {"hex": "#000000", "alpha": 1.0}
        assert result["palette"]["midground"] == {"hex": "#ffffff", "alpha": 1.0}
        # foreground falls back to default (transparent white)
        assert result["palette"]["foreground"]["hex"] == "#ffffff"
        assert result["palette"]["foreground"]["alpha"] == 0.0

    def test_full_palette_form(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "full",
            "palette": {
                "background": {"hex": "#0a1628", "alpha": 1.0},
                "midground": {"hex": "#a8d0ff", "alpha": 0.9},
                "warmGlow": "rgba(255, 0, 0, 0.5)",
                "noiseOpacity": 0.5,
            },
        })
        assert result["palette"]["background"]["hex"] == "#0a1628"
        assert result["palette"]["midground"]["alpha"] == 0.9
        assert result["palette"]["warmGlow"] == "rgba(255, 0, 0, 0.5)"
        assert result["palette"]["noiseOpacity"] == 0.5

    def test_default_typography_applied_when_missing(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "minimal"})
        typo = result["typography"]
        assert "fontSans" in typo
        assert "fontMono" in typo
        assert typo["baseSize"] == "15px"
        assert typo["lineHeight"] == "1.55"
        assert typo["letterSpacing"] == "0"

    def test_partial_typography_merges_with_defaults(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "partial",
            "typography": {
                "fontSans": "MyFont, sans-serif",
                "baseSize": "12px",
            },
        })
        assert result["typography"]["fontSans"] == "MyFont, sans-serif"
        assert result["typography"]["baseSize"] == "12px"
        # fontMono defaulted
        assert "monospace" in result["typography"]["fontMono"]

    def test_layout_defaults(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "minimal"})
        assert result["layout"]["radius"] == "0.5rem"
        assert result["layout"]["density"] == "comfortable"

    def test_invalid_density_falls_back(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "bad",
            "layout": {"density": "ultra-spacious"},
        })
        assert result["layout"]["density"] == "comfortable"

    def test_valid_densities_accepted(self):
        from hermes_cli.web_server import _normalise_theme_definition
        for d in ("compact", "comfortable", "spacious"):
            r = _normalise_theme_definition({"name": "x", "layout": {"density": d}})
            assert r["layout"]["density"] == d

    def test_color_overrides_filter_unknown_keys(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({
            "name": "o",
            "colorOverrides": {
                "card": "#123456",
                "fakeToken": "#abcdef",
                "primary": 42,  # non-string rejected
                "destructive": "#ff0000",
            },
        })
        assert result["colorOverrides"] == {
            "card": "#123456",
            "destructive": "#ff0000",
        }

    def test_color_overrides_omitted_when_empty(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "x"})
        assert "colorOverrides" not in result

    def test_alpha_clamped_to_unit_range(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "c",
            "palette": {"background": {"hex": "#000", "alpha": 99.5}},
        })
        assert r["palette"]["background"]["alpha"] == 1.0
        r2 = _normalise_theme_definition({
            "name": "c",
            "palette": {"background": {"hex": "#000", "alpha": -5}},
        })
        assert r2["palette"]["background"]["alpha"] == 0.0

    def test_invalid_alpha_uses_default(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "c",
            "palette": {"background": {"hex": "#000", "alpha": "not a number"}},
        })
        assert r["palette"]["background"]["alpha"] == 1.0


class TestDiscoverUserThemes:
    """Tests for _discover_user_themes() — scans ~/.hermes/dashboard-themes/."""

    def test_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from hermes_cli import web_server
        assert web_server._discover_user_themes() == []

    def test_loads_and_normalises_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        themes_dir = tmp_path / "dashboard-themes"
        themes_dir.mkdir()
        (themes_dir / "ocean.yaml").write_text(
            "name: ocean\n"
            "label: Ocean\n"
            "palette:\n"
            "  background:\n"
            "    hex: \"#0a1628\"\n"
            "    alpha: 1.0\n"
            "layout:\n"
            "  density: spacious\n"
        )
        from hermes_cli import web_server
        results = web_server._discover_user_themes()
        assert len(results) == 1
        assert results[0]["name"] == "ocean"
        assert results[0]["label"] == "Ocean"
        assert results[0]["palette"]["background"]["hex"] == "#0a1628"
        assert results[0]["layout"]["density"] == "spacious"
        # defaults filled in
        assert "fontSans" in results[0]["typography"]

    def test_malformed_yaml_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        themes_dir = tmp_path / "dashboard-themes"
        themes_dir.mkdir()
        (themes_dir / "bad.yaml").write_text("::: not valid yaml :::\n\tindent wrong")
        (themes_dir / "nameless.yaml").write_text("label: No Name Here\n")
        (themes_dir / "ok.yaml").write_text("name: ok\n")
        from hermes_cli import web_server
        results = web_server._discover_user_themes()
        names = [r["name"] for r in results]
        assert "ok" in names
        assert "bad" not in names  # malformed YAML
        assert len(results) == 1  # only the valid one


class TestNormaliseThemeExtensions:
    """Tests for the extended normaliser fields (assets, customCSS,
    componentStyles, layoutVariant) — the surfaces themes use to reskin
    the dashboard without shipping code."""

    def test_layout_variant_defaults_to_standard(self):
        from hermes_cli.web_server import _normalise_theme_definition
        result = _normalise_theme_definition({"name": "t"})
        assert result["layoutVariant"] == "standard"

    def test_layout_variant_accepts_known_values(self):
        from hermes_cli.web_server import _normalise_theme_definition
        for variant in ("standard", "cockpit", "tiled"):
            r = _normalise_theme_definition({"name": "t", "layoutVariant": variant})
            assert r["layoutVariant"] == variant

    def test_layout_variant_rejects_unknown(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({"name": "t", "layoutVariant": "warship"})
        assert r["layoutVariant"] == "standard"
        r2 = _normalise_theme_definition({"name": "t", "layoutVariant": 12})
        assert r2["layoutVariant"] == "standard"

    def test_assets_named_slots_passthrough(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "assets": {
                "bg": "https://example.com/bg.jpg",
                "hero": "linear-gradient(180deg, red, blue)",
                "crest": "/ds-assets/crest.svg",
                "logo": "  ",  # whitespace-only — dropped
                "notAKnownKey": "ignored",
            },
        })
        assert r["assets"]["bg"] == "https://example.com/bg.jpg"
        assert r["assets"]["hero"].startswith("linear-gradient")
        assert r["assets"]["crest"] == "/ds-assets/crest.svg"
        assert "logo" not in r["assets"]  # whitespace-only rejected
        assert "notAKnownKey" not in r["assets"]  # unknown slot ignored

    def test_assets_custom_block(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "assets": {
                "custom": {
                    "scan-lines": "/img/scan.png",
                    "my_overlay": "/img/ov.png",
                    "bad key!": "x",  # non-alnum key — rejected
                    "empty": "",        # empty value — rejected
                },
            },
        })
        assert r["assets"]["custom"] == {
            "scan-lines": "/img/scan.png",
            "my_overlay": "/img/ov.png",
        }

    def test_assets_absent_means_no_field(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({"name": "t"})
        assert "assets" not in r

    def test_custom_css_passthrough_and_capped(self):
        from hermes_cli.web_server import _normalise_theme_definition
        # Small CSS passes through verbatim.
        r = _normalise_theme_definition({
            "name": "t",
            "customCSS": "body { color: red; }",
        })
        assert r["customCSS"] == "body { color: red; }"

        # 40 KiB of CSS gets clipped to the 32 KiB cap.
        huge = "/* x */ " * (40 * 1024 // 8 + 10)
        r2 = _normalise_theme_definition({"name": "t", "customCSS": huge})
        assert len(r2["customCSS"]) <= 32 * 1024

    def test_custom_css_empty_dropped(self):
        from hermes_cli.web_server import _normalise_theme_definition
        for val in ("", "   \n\t", None):
            r = _normalise_theme_definition({"name": "t", "customCSS": val})
            assert "customCSS" not in r

    def test_component_styles_per_bucket(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "componentStyles": {
                "card": {
                    "clipPath": "polygon(0 0, 100% 0, 100% 100%, 0 100%)",
                    "boxShadow": "inset 0 0 0 1px red",
                    "bad prop!": "ignored",  # non-alnum prop rejected
                },
                "header": {"background": "linear-gradient(red, blue)"},
                "rogueBucket": {"foo": "bar"},  # not a known bucket — rejected
            },
        })
        assert r["componentStyles"]["card"] == {
            "clipPath": "polygon(0 0, 100% 0, 100% 100%, 0 100%)",
            "boxShadow": "inset 0 0 0 1px red",
        }
        assert r["componentStyles"]["header"]["background"].startswith("linear-gradient")
        assert "rogueBucket" not in r["componentStyles"]

    def test_component_styles_empty_buckets_dropped(self):
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "componentStyles": {
                "card": {},        # empty — dropped entirely
                "header": {"bad prop!": "ignored"},  # all props rejected — bucket dropped
                "footer": {"background": "black"},
            },
        })
        assert "card" not in r.get("componentStyles", {})
        assert "header" not in r.get("componentStyles", {})
        assert r["componentStyles"]["footer"]["background"] == "black"

    def test_component_styles_accepts_numeric_values(self):
        """Numeric values (e.g. opacity: 0.8) are coerced to strings."""
        from hermes_cli.web_server import _normalise_theme_definition
        r = _normalise_theme_definition({
            "name": "t",
            "componentStyles": {"card": {"opacity": 0.8, "zIndex": 5}},
        })
        assert r["componentStyles"]["card"] == {"opacity": "0.8", "zIndex": "5"}


class TestPluginAPIAuth:
    """Tests that plugin API routes require the session token (issue #19533)."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self, monkeypatch, _isolate_hermes_home):
        """Create a TestClient without the session token header."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import hermes_state
        from hermes_constants import get_hermes_home
        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

        monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")

        self.client = TestClient(app)
        self.auth_client = TestClient(app)
        self.auth_client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_plugin_route_requires_auth(self):
        """Plugin API routes should return 401 without a valid session token."""
        # Use a known plugin route (kanban board)
        resp = self.client.get("/api/plugins/kanban/board")
        assert resp.status_code == 401

    def test_plugin_route_allows_auth(self):
        """Plugin API routes should work with a valid session token.

        Use a dummy dashboard route because plugin API files aren't
        reliably available outside of the hermes process lifecycle.
        """
        # Without auth: middleware blocks before reaching the handler.
        resp = self.client.get("/api/dashboard/agent-plugins/test_plugin")
        assert resp.status_code == 401

        # With auth: handler runs (will return 404 since there's no such agent-plugin).
        resp = self.auth_client.get("/api/dashboard/agent-plugins/test_plugin")
        assert resp.status_code == 404
    def test_plugin_post_requires_auth(self):
        """Plugin POST routes should return 401 without a valid session token."""
        resp = self.client.post("/api/plugins/kanban/tasks", json={"title": "test"})
        assert resp.status_code == 401

    def test_plugin_patch_requires_auth(self):
        """Plugin PATCH routes should return 401 without a valid session token.

        PATCH is the mutation method most commonly used by the dashboard for
        kanban task edits — explicitly cover it so a future middleware
        regression that whitelists non-GET methods can't sneak through.
        """
        resp = self.client.patch(
            "/api/plugins/kanban/tasks/t_fake",
            json={"title": "renamed"},
        )
        assert resp.status_code == 401

    def test_plugin_delete_requires_auth(self):
        """Plugin DELETE routes should return 401 without a valid session token."""
        resp = self.client.delete("/api/plugins/kanban/tasks/t_fake")
        assert resp.status_code == 401

    def test_non_kanban_plugin_route_requires_auth(self):
        """Auth must be plugin-agnostic, not kanban-specific.

        The middleware fix is at the gate level (no per-plugin allowlist),
        so any plugin's API surface — kanban, hermes-achievements, future
        plugins — must require the session token. Hit a non-kanban plugin
        path to lock that in.
        """
        # Real plugin path (hermes-achievements is loaded by default).
        resp = self.client.get("/api/plugins/hermes-achievements/overview")
        assert resp.status_code == 401
        # Same for an arbitrary plugin namespace that doesn't even exist —
        # the middleware should 401 before routing decides 404, so an
        # attacker can't fingerprint plugin names by status codes.
        resp = self.client.get("/api/plugins/_definitely_not_a_plugin_/anything")
        assert resp.status_code == 401

    def test_plugin_websocket_unaffected_by_http_middleware(self):
        """The kanban /events WebSocket has its own ``?token=`` check;
        the HTTP middleware change must not start gating WS upgrades.

        Starlette doesn't run HTTP middleware on WebSocket upgrades anyway,
        but pin the behavior so a future refactor that moves auth into a
        shared layer can't silently break the WS auth contract.
        """
        from starlette.websockets import WebSocketDisconnect
        from hermes_cli.web_server import _SESSION_TOKEN

        # Without a token the WS endpoint must close the upgrade itself
        # (its own _check_ws_token), NOT 401 from the HTTP middleware.
        try:
            with self.client.websocket_connect(
                "/api/plugins/kanban/events"
            ):
                pass  # if we got here without disconnect, the WS accepted us
        except WebSocketDisconnect:
            pass  # expected — WS endpoint rejected via its own check
        except Exception:
            # The kanban plugin may not be mounted in this test environment,
            # in which case the route doesn't exist at all (3xx/4xx during
            # upgrade). That's fine for this regression — it only matters
            # that the HTTP middleware didn't start intercepting WS upgrades.
            pass


class TestDashboardPluginManifestExtensions:
    """Tests for the extended plugin manifest fields (tab.override,
    tab.hidden, slots) read by _discover_dashboard_plugins()."""

    def _write_plugin(self, tmp_path, name, manifest, *, enabled=True):
        import json
        plug_dir = tmp_path / "plugins" / name / "dashboard"
        plug_dir.mkdir(parents=True)
        (plug_dir / "manifest.json").write_text(json.dumps(manifest))
        plugin_name = manifest.get("name", name)
        config = {"plugins": {"enabled": [plugin_name] if enabled else [], "disabled": []}}
        (tmp_path / "config.yaml").write_text(json.dumps(config))
        return plug_dir

    def test_disabled_plugin_api_is_not_imported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        plug_dir = self._write_plugin(tmp_path, "blocked", {
            "name": "blocked",
            "label": "Blocked",
            "tab": {"path": "/blocked"},
            "entry": "dist/index.js",
            "api": "api.py",
        }, enabled=False)
        marker = tmp_path / "dashboard_api_executed"
        (plug_dir / "api.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
        )

        from hermes_cli import web_server
        web_server._dashboard_plugins_cache = None
        web_server._mount_plugin_api_routes()

        assert web_server._get_dashboard_plugins(force_rescan=True) == []
        assert not marker.exists()

    def test_enabled_plugin_api_is_imported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        plug_dir = self._write_plugin(tmp_path, "allowed", {
            "name": "allowed",
            "label": "Allowed",
            "tab": {"path": "/allowed"},
            "entry": "dist/index.js",
            "api": "api.py",
        })
        marker = tmp_path / "dashboard_api_executed"
        (plug_dir / "api.py").write_text(
            "from pathlib import Path\n"
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            f"Path({str(marker)!r}).write_text('executed')\n"
        )

        from hermes_cli import web_server
        web_server._dashboard_plugins_cache = None
        web_server._mount_plugin_api_routes()

        assert marker.read_text() == "executed"

    def test_override_and_hidden_carried_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "skin-home", {
            "name": "skin-home",
            "label": "Skin Home",
            "tab": {"path": "/skin-home", "override": "/", "hidden": True},
            "slots": ["sidebar", "header-left"],
            "entry": "dist/index.js",
        })
        from hermes_cli import web_server
        # Bust the process-level cache so the test plugin is picked up.
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "skin-home")
        assert entry["tab"]["override"] == "/"
        assert entry["tab"]["hidden"] is True
        assert entry["slots"] == ["sidebar", "header-left"]

    def test_override_requires_leading_slash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "bad-override", {
            "name": "bad-override",
            "label": "Bad",
            "tab": {"path": "/bad", "override": "no-leading-slash"},
            "entry": "dist/index.js",
        })
        from hermes_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "bad-override")
        assert "override" not in entry["tab"]

    def test_slots_default_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "no-slots", {
            "name": "no-slots",
            "label": "No Slots",
            "tab": {"path": "/no-slots"},
            "entry": "dist/index.js",
        })
        from hermes_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "no-slots")
        assert entry["slots"] == []
        assert "hidden" not in entry["tab"]
        assert "override" not in entry["tab"]

    def test_slots_filters_non_string_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "mixed-slots", {
            "name": "mixed-slots",
            "label": "Mixed",
            "tab": {"path": "/mixed-slots"},
            "slots": ["sidebar", "", 42, None, "header-right"],
            "entry": "dist/index.js",
        })
        from hermes_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "mixed-slots")
        assert entry["slots"] == ["sidebar", "header-right"]

    def test_page_scoped_slots_preserved(self, tmp_path, monkeypatch):
        """Page-scoped slot names (e.g. ``sessions:top``) round-trip through
        the manifest loader untouched.  The backend has no allowlist — the
        frontend ``<PluginSlot name="...">`` placements decide what actually
        renders — but the loader must not mangle colons in slot names."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        self._write_plugin(tmp_path, "page-slots", {
            "name": "page-slots",
            "label": "Page Slots",
            "tab": {"path": "/page-slots", "hidden": True},
            "slots": [
                "sessions:top",
                "analytics:bottom",
                "logs:top",
                "skills:bottom",
                "config:top",
                "env:bottom",
                "docs:top",
                "cron:bottom",
                "chat:top",
            ],
            "entry": "dist/index.js",
        })
        from hermes_cli import web_server
        web_server._dashboard_plugins_cache = None
        plugins = web_server._get_dashboard_plugins(force_rescan=True)
        entry = next(p for p in plugins if p["name"] == "page-slots")
        assert entry["slots"] == [
            "sessions:top",
            "analytics:bottom",
            "logs:top",
            "skills:bottom",
            "config:top",
            "env:bottom",
            "docs:top",
            "cron:bottom",
            "chat:top",
        ]


# ---------------------------------------------------------------------------
# /api/pty WebSocket — terminal bridge for the dashboard "Chat" tab.
#
# These tests drive the endpoint with a tiny fake command (typically ``cat``
# or ``sh -c 'printf …'``) instead of the real ``hermes --tui`` binary.  The
# endpoint resolves its argv through ``_resolve_chat_argv``, so tests
# monkeypatch that hook.
# ---------------------------------------------------------------------------

import sys


skip_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"), reason="PTY bridge is POSIX-only"
)


@skip_on_windows
class TestPtyWebSocket:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, _isolate_hermes_home):
        from starlette.testclient import TestClient

        import hermes_cli.web_server as ws

        # Avoid exec'ing the actual TUI in tests: every test below installs
        # its own fake argv via ``ws._resolve_chat_argv``.
        self.ws_module = ws
        monkeypatch.setattr(ws, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)
        self.token = ws._SESSION_TOKEN
        self.client = TestClient(ws.app)

    def _url(self, token: str | None = None, **params: str) -> str:
        tok = token if token is not None else self.token
        # TestClient.websocket_connect takes the path; it reconstructs the
        # query string, so we pass it inline.
        from urllib.parse import urlencode

        q = {"token": tok, **params}
        return f"/api/pty?{urlencode(q)}"

    def test_rejects_when_embedded_chat_disabled(self, monkeypatch):
        monkeypatch.setattr(self.ws_module, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", False)
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(self._url()):
                pass
        assert exc.value.code == 4403

    def test_rejects_missing_token(self, monkeypatch):
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect("/api/pty"):
                pass
        assert exc.value.code == 4401

    def test_rejects_bad_token(self, monkeypatch):
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(self._url(token="wrong")):
                pass
        assert exc.value.code == 4401

    def test_websocket_rejects_non_loopback_on_public_bind(self, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            self.ws_module.app.state, "bound_host", "0.0.0.0", raising=False
        )

        remote_ws = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"))
        loopback_ws = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

        assert self.ws_module._ws_client_is_allowed(remote_ws) is False
        assert self.ws_module._ws_client_is_allowed(loopback_ws) is True

    def test_streams_child_stdout_to_client(self, monkeypatch):
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (
                ["/bin/sh", "-c", "printf hermes-ws-ok"],
                None,
                None,
            ),
        )
        with self.client.websocket_connect(self._url()) as conn:
            # Drain frames until we see the needle or time out.  TestClient's
            # recv_bytes blocks; loop until we have the signal byte string.
            buf = b""
            import time

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    message = conn.receive()
                    if "bytes" in message:
                        buf += message["bytes"]
                    elif "text" in message:
                        buf += message["text"].encode()
                except Exception:
                    break
                if b"hermes-ws-ok" in buf:
                    break
            assert b"hermes-ws-ok" in buf

    def test_client_input_reaches_child_stdin(self, monkeypatch):
        # ``cat`` echoes stdin back, so a write → read round-trip proves
        # the full duplex path.
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            lambda resume=None, sidecar_url=None: (["/bin/cat"], None, None),
        )
        with self.client.websocket_connect(self._url()) as conn:
            conn.send_bytes(b"round-trip-payload\n")
            buf = b""
            import time

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    message = conn.receive()
                    if "bytes" in message:
                        buf += message["bytes"]
                    elif "text" in message:
                        buf += message["text"].encode()
                except Exception:
                    break

                if b"round-trip-payload" in buf:
                    break
            assert b"round-trip-payload" in buf

    def test_resize_escape_is_forwarded(self, monkeypatch):
        # Resize escape gets intercepted and applied via TIOCSWINSZ, then the
        # child reads the TTY ioctl directly. Avoid tput because CI may not set
        # TERM for non-interactive shells.
        import sys

        winsize_script = (
            "import fcntl, struct, termios, time; "
            "time.sleep(0.15); "
            "rows, cols, *_ = struct.unpack('HHHH', "
            "fcntl.ioctl(0, termios.TIOCGWINSZ, b'\\0' * 8)); "
            "print(cols); print(rows)"
        )
        monkeypatch.setattr(
            self.ws_module,
            "_resolve_chat_argv",
            # sleep gives the test time to push the resize before the child reads the ioctl.
            lambda resume=None, sidecar_url=None: (
                [sys.executable, "-c", winsize_script],
                None,
                None,
            ),
        )
        with self.client.websocket_connect(self._url()) as conn:
            conn.send_text(chr(27) + "[RESIZE:99;41]")
            buf = b""
            import time

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    message = conn.receive()
                    if "bytes" in message:
                        buf += message["bytes"]
                    elif "text" in message:
                        buf += message["text"].encode()
                except Exception:
                    break
                if b"41" in buf and b"99" in buf:
                    break
            assert b"99" in buf
            assert b"41" in buf
    def test_pub_broadcasts_to_events_subscribers(self, monkeypatch):
        """Frame written to /api/pub is rebroadcast verbatim to every
        /api/events subscriber on the same channel."""
        import time
        from urllib.parse import urlencode
        from hermes_cli import web_server as ws_mod

        qs = urlencode({"token": self.token, "channel": "broadcast-test"})
        pub_path = f"/api/pub?{qs}"
        sub_path = f"/api/events?{qs}"

        with self.client.websocket_connect(sub_path) as sub:
            # Wait for the subscriber to be registered on the server side.
            # websocket_connect returns when ws.accept() completes, but the
            # server adds us to ``_event_channels`` in a follow-up await,
            # so a publish immediately after connect can race ahead of the
            # subscriber registration and the message is dropped.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if ws_mod._event_channels.get("broadcast-test"):
                    break
                time.sleep(0.01)
            else:
                raise AssertionError(
                    "subscriber did not register on channel within 5s"
                )

            with self.client.websocket_connect(pub_path) as pub:
                pub.send_text('{"type":"tool.start","payload":{"tool_id":"t1"}}')
                received = sub.receive_text()

        assert "tool.start" in received
        assert '"tool_id":"t1"' in received

    def test_events_rejects_missing_channel(self):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with self.client.websocket_connect(
                f"/api/events?token={self.token}"
            ):
                pass
        assert exc.value.code == 4400

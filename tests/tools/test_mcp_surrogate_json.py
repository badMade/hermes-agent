"""Regression tests for UTF-8-safe MCP JSON serialization."""

import asyncio
from types import SimpleNamespace


class _AsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_mcp_json_dumps_preserves_cjk_but_escapes_lone_surrogates():
    from tools.mcp_tool import _mcp_json_dumps

    payload = _mcp_json_dumps({"result": "中文\ud800"})

    assert "中文" in payload
    assert "\ud800" not in payload
    assert "\\ud800" in payload
    payload.encode("utf-8")


def test_mcp_tool_handler_returns_utf8_encodable_result_for_surrogate_text(monkeypatch):
    import tools.mcp_tool as mcp_tool

    class FakeSession:
        async def call_tool(self, tool_name, arguments):
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(text="tool output \ud800")],
            )

    fake_server = SimpleNamespace(session=FakeSession(), _rpc_lock=_AsyncLock())
    monkeypatch.setitem(mcp_tool._servers, "surrogate-server", fake_server)
    monkeypatch.setattr(
        mcp_tool,
        "_run_on_mcp_loop",
        lambda coro, timeout=None: asyncio.run(coro),
    )

    handler = mcp_tool._make_tool_handler("surrogate-server", "demo", 1.0)
    result = handler({})

    assert "\ud800" not in result
    assert "\\ud800" in result
    result.encode("utf-8")


def test_sampling_tool_arguments_are_utf8_encodable():
    from tools.mcp_tool import SamplingHandler

    handler = SamplingHandler("surrogate-server", {})
    tool_use = SimpleNamespace(name="demo", input={"value": "中文\ud800"}, id="call_1")
    message = SimpleNamespace(role="assistant", content=[tool_use], content_as_list=[tool_use])

    converted = handler._convert_messages(SimpleNamespace(messages=[message]))
    arguments = converted[0]["tool_calls"][0]["function"]["arguments"]

    assert "中文" in arguments
    assert "\ud800" not in arguments
    assert "\\ud800" in arguments
    arguments.encode("utf-8")

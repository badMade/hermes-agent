import asyncio
import threading
from typing import Any
import pytest
from unittest.mock import patch

from environments.tool_context import _run_tool_in_thread


@pytest.mark.asyncio
async def test_run_tool_in_thread_async() -> None:
    """Test that _run_tool_in_thread uses a thread pool when an event loop is running."""
    main_thread = threading.get_ident()
    observed: dict[str, Any] = {}

    def record_thread(*args: Any) -> str:
        observed["thread_id"] = threading.get_ident()
        try:
            observed["running_loop"] = asyncio.get_running_loop()
        except RuntimeError:
            observed["running_loop"] = None
        return "async_result"

    with patch(
        "environments.tool_context.handle_function_call", side_effect=record_thread
    ) as mock_handle:
        result = _run_tool_in_thread("test_tool", {"arg": "val"}, "test_task")

        assert result == "async_result"
        mock_handle.assert_called_once_with("test_tool", {"arg": "val"}, "test_task")
        assert observed["thread_id"] != main_thread
        assert observed["running_loop"] is None


def test_run_tool_in_thread_sync() -> None:
    """Test that _run_tool_in_thread calls the function directly when no event loop is running."""
    with patch("environments.tool_context.handle_function_call") as mock_handle:
        mock_handle.return_value = "sync_result"
        result = _run_tool_in_thread("test_tool", {"arg": "val"}, "test_task")
        assert result == "sync_result"
        mock_handle.assert_called_once_with("test_tool", {"arg": "val"}, "test_task")


@pytest.mark.asyncio
async def test_run_tool_in_thread_timeout() -> None:
    """Test that a timeout is raised if the tool takes too long."""

    class FakeFuture:
        def __init__(self) -> None:
            self.timeout: float | None = None

        def result(self, timeout: float | None = None) -> str:
            self.timeout = timeout
            raise TimeoutError("Timed out")

    fake_future = FakeFuture()

    class FakeExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers
            self.submissions: list[tuple[Any, tuple[Any, ...]]] = []

        def __enter__(self) -> "FakeExecutor":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def submit(self, fn: Any, *args: Any) -> FakeFuture:
            self.submissions.append((fn, args))
            return fake_future

    requested_max_workers: list[int] = []
    fake_executor = FakeExecutor(max_workers=1)

    with patch("environments.tool_context.handle_function_call") as mock_handle:
        with patch(
            "environments.tool_context.concurrent.futures.ThreadPoolExecutor",
            side_effect=lambda max_workers: requested_max_workers.append(max_workers)
            or fake_executor,
        ):
            with pytest.raises(TimeoutError, match="Timed out"):
                _run_tool_in_thread("test_tool", {"arg": "val"}, "test_task")

    assert requested_max_workers == [1]
    assert fake_executor.submissions == [
        (mock_handle, ("test_tool", {"arg": "val"}, "test_task"))
    ]
    assert fake_future.timeout == 300


@pytest.mark.asyncio
async def test_run_tool_in_thread_exception() -> None:
    """Test that exceptions from the tool are propagated correctly in async context."""
    with patch(
        "environments.tool_context.handle_function_call",
        side_effect=ValueError("Test error"),
    ):
        with pytest.raises(ValueError, match="Test error"):
            _run_tool_in_thread("test_tool", {"arg": "val"}, "test_task")


def test_run_tool_in_thread_sync_exception() -> None:
    """Test that exceptions from the tool are propagated correctly in sync context."""
    with patch(
        "environments.tool_context.handle_function_call",
        side_effect=ValueError("Test sync error"),
    ):
        with pytest.raises(ValueError, match="Test sync error"):
            _run_tool_in_thread("test_tool", {"arg": "val"}, "test_task")

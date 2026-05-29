"""
Regression tests for container task_id mapping.

Top-level CLI calls use ``None`` and share ``"default"``. Gateway/ACP calls
use per-session task IDs and must keep isolated sandboxes. ``delegate_task``
children use separate child IDs for file-state/UI bookkeeping, then explicitly
alias those IDs to the parent's sandbox key while the child is running.
"""

import pytest

from tools import terminal_tool


@pytest.fixture(autouse=True)
def _clean_task_routing_state():
    """Ensure no stray overrides or aliases from other tests leak in."""
    before_overrides = dict(terminal_tool._task_env_overrides)
    before_aliases = dict(terminal_tool._task_container_aliases)
    terminal_tool._task_env_overrides.clear()
    terminal_tool._task_container_aliases.clear()
    yield
    terminal_tool._task_env_overrides.clear()
    terminal_tool._task_env_overrides.update(before_overrides)
    terminal_tool._task_container_aliases.clear()
    terminal_tool._task_container_aliases.update(before_aliases)


def test_none_task_id_maps_to_default():
    assert terminal_tool._resolve_container_task_id(None) == "default"


def test_empty_task_id_maps_to_default():
    assert terminal_tool._resolve_container_task_id("") == "default"


def test_literal_default_stays_default():
    assert terminal_tool._resolve_container_task_id("default") == "default"


def test_unaliased_subagent_task_id_collapses_to_default_for_cli_compatibility():
    assert terminal_tool._resolve_container_task_id("sa-0-deadbeef") == "default"
    assert terminal_tool._resolve_container_task_id("subagent-42-cafef00d") == "default"


def test_gateway_session_id_keeps_its_own_container_key():
    assert (
        terminal_tool._resolve_container_task_id("sess-123e4567-e89b-12d3")
        == "sess-123e4567-e89b-12d3"
    )


@pytest.mark.parametrize(
    "task_id",
    ["api-session-A", "api-session-", "api-session-123", "api-session-long-uuid-string"],
)
def test_api_session_id_keeps_its_own_container_key(task_id):
    assert terminal_tool._resolve_container_task_id(task_id) == task_id


def test_subagent_alias_maps_child_to_parent_session_container():
    terminal_tool.register_task_container_alias("sa-0-deadbeef", "gateway-session-1")
    assert terminal_tool._resolve_container_task_id("sa-0-deadbeef") == "gateway-session-1"


def test_subagent_alias_maps_child_to_default_for_cli_parent():
    terminal_tool.register_task_container_alias("sa-0-deadbeef", None)
    assert terminal_tool._resolve_container_task_id("sa-0-deadbeef") == "default"


def test_cleared_subagent_alias_collapses_to_default_again():
    terminal_tool.register_task_container_alias("sa-0-deadbeef", "gateway-session-1")
    assert terminal_tool._resolve_container_task_id("sa-0-deadbeef") == "gateway-session-1"
    terminal_tool.clear_task_container_alias("sa-0-deadbeef")
    assert terminal_tool._resolve_container_task_id("sa-0-deadbeef") == "default"


def test_rl_task_with_override_keeps_its_own_id():
    # RL / benchmark pattern: register a per-task image, then the task_id
    # must survive ``_resolve_container_task_id`` so the rollout lands in
    # its own sandbox.
    terminal_tool.register_task_env_overrides(
        "tb2-task-fix-git", {"docker_image": "tb2:fix-git", "cwd": "/app"}
    )
    try:
        assert (
            terminal_tool._resolve_container_task_id("tb2-task-fix-git")
            == "tb2-task-fix-git"
        )
    finally:
        terminal_tool.clear_task_env_overrides("tb2-task-fix-git")


def test_cleared_override_keeps_own_key():
    # With the isolation model, clearing the override does NOT collapse the ID
    # back to "default"; the task keeps its own sandbox key so that a stale
    # cleanup_vm call after rollout teardown pops the right (already-empty)
    # bucket rather than accidentally touching the shared "default" sandbox.
    terminal_tool.register_task_env_overrides("tb2-x", {"docker_image": "x:y"})
    assert terminal_tool._resolve_container_task_id("tb2-x") == "tb2-x"
    terminal_tool.clear_task_env_overrides("tb2-x")
    assert terminal_tool._resolve_container_task_id("tb2-x") == "tb2-x"


def test_get_active_env_reads_shared_container_from_subagent_id():
    """``get_active_env`` must see the shared ``"default"`` sandbox when
    called with a subagent's task_id, so the agent loop's turn-budget
    enforcement reads the real env (not None) during delegation."""
    sentinel = object()
    terminal_tool._active_environments["default"] = sentinel
    try:
        assert terminal_tool.get_active_env("subagent-7-cafe") is sentinel
        assert terminal_tool.get_active_env(None) is sentinel
        assert terminal_tool.get_active_env("default") is sentinel
    finally:
        terminal_tool._active_environments.pop("default", None)


def test_get_active_env_honours_rl_override():
    rl_env = object()
    default_env = object()
    terminal_tool._active_environments["default"] = default_env
    terminal_tool._active_environments["rl-42"] = rl_env
    terminal_tool.register_task_env_overrides("rl-42", {"docker_image": "x"})
    try:
        # With an override registered, lookup returns the task's own env,
        # not the shared "default" one.
        assert terminal_tool.get_active_env("rl-42") is rl_env
    finally:
        terminal_tool.clear_task_env_overrides("rl-42")
        terminal_tool._active_environments.pop("default", None)
        terminal_tool._active_environments.pop("rl-42", None)


class _CleanupProbe:
    def __init__(self):
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


def test_cleanup_vm_keeps_api_session_distinct_from_default_container():
    """Client-controlled API session IDs must not tear down the default sandbox."""
    api_env = _CleanupProbe()
    default_env = _CleanupProbe()
    terminal_tool._active_environments["api-session-A"] = api_env
    terminal_tool._active_environments["default"] = default_env
    terminal_tool._last_activity["api-session-A"] = 123.0
    terminal_tool._last_activity["default"] = 456.0
    terminal_tool._creation_locks["api-session-A"] = object()
    terminal_tool._creation_locks["default"] = object()
    try:
        terminal_tool.cleanup_vm("api-session-A")

        assert api_env.cleaned is True
        assert default_env.cleaned is False
        assert "api-session-A" not in terminal_tool._active_environments
        assert "api-session-A" not in terminal_tool._last_activity
        assert "api-session-A" not in terminal_tool._creation_locks
        assert terminal_tool._active_environments["default"] is default_env
        assert terminal_tool._last_activity["default"] == 456.0
        assert "default" in terminal_tool._creation_locks
    finally:
        terminal_tool._active_environments.pop("api-session-A", None)
        terminal_tool._active_environments.pop("default", None)
        terminal_tool._last_activity.pop("api-session-A", None)
        terminal_tool._last_activity.pop("default", None)
        terminal_tool._creation_locks.pop("api-session-A", None)
        terminal_tool._creation_locks.pop("default", None)


def test_cleanup_vm_honours_override_task_id():
    """Isolated benchmark task IDs should still clean their own sandbox."""
    env = _CleanupProbe()
    terminal_tool.register_task_env_overrides("rl-cleanup", {"docker_image": "x"})
    terminal_tool._active_environments["rl-cleanup"] = env
    try:
        terminal_tool.cleanup_vm("rl-cleanup")

        assert env.cleaned is True
        assert "rl-cleanup" not in terminal_tool._active_environments
    finally:
        terminal_tool.clear_task_env_overrides("rl-cleanup")
        terminal_tool._active_environments.pop("rl-cleanup", None)

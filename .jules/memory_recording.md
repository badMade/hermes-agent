### Task
Add missing test for `MemoryProvider.queue_prefetch`.

### Analysis
The abstract base class `MemoryProvider` defines `queue_prefetch` as a no-op method.
However, in `tests/agent/test_memory_provider.py`, the test verifying that optional hooks default to no-ops (`test_default_optional_hooks_are_noop`) used a `FakeMemoryProvider`.
The issue was that `FakeMemoryProvider` actively overrode *all* these optional hooks, meaning the test was actually exercising the overrides rather than the base default implementations.

### Solution
Created a `MinimalProvider` inline within the `test_default_optional_hooks_are_noop` test that only overrides the mandatory abstract methods (e.g., `name`, `is_available`, `initialize`, `get_tool_schemas`).
By instantiating `MinimalProvider`, the test correctly calls the base `MemoryProvider` hooks (like `queue_prefetch`, `sync_turn`, `on_turn_start`, etc.) and asserts they do not raise exceptions, ensuring true coverage of the default no-op behavior.

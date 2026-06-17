## Optimization: Bulk Task Link Insertion in kanban_db.py

**Optimization:** Replaced blocking `time.sleep()` with `await asyncio.sleep()` in the async `start_gateway` process termination wait loop.
**Impact:** Restores asynchronous execution of background tasks (like background cron timers, background connections, or tick mechanisms) during the gateway startup phase (which could take up to 10 seconds).
**Context:** When a service restarts with `--replace`, it polls the system using `_pid_exists` checking if the previous instance has shut down gracefully before forceful termination. Doing `time.sleep(0.5)` halted the whole event loop. Async sleep allows background event loop tasks to continue their tick cycles and execution.

## 2025-03-04 - Batch Tokenization Optimization
**Learning:** HuggingFace tokenizers in `trajectory_compressor.py` were processing texts iteratively (`self.tokenizer.encode(text)`) in a list comprehension. When processing lists of text, using `self.tokenizer(texts)` batch-encodes the entire list by delegating to the optimized Rust implementation, which is measurably faster (roughly 3-4x in benchmarks). When falling back, use `self.count_tokens` rather than jumping straight to character estimation to support tokenizers that lack `__call__` but have `.encode()`.
**Action:** When counting tokens for lists of items (e.g. trajectories or batched messages), always use `self.tokenizer(texts)` instead of iterating through elements with `.encode()`. Provide a fallback to the original token counting iteration in case batch encoding fails or the tokenizer doesn't support it.
**Date**: 2026-06-01
**File**: `hermes_cli/kanban_db.py` (`create_task()`)

### What
Replaced a `for` loop executing individual `INSERT OR IGNORE` queries with a single `conn.executemany` call for inserting task links (parent-child relationships).

### Why
The `for` loop caused an N+1 query issue. By using `executemany`, the SQLite engine can process all insertions efficiently in a single batch, reducing overhead.

### Expected Performance Impact
Measured improvement: Creation time for a task with 10,000 parents decreased from ~0.1575s to ~0.1344s (~15% speedup).

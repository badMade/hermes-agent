# Performance Learnings (Bolt Workflow)

## Gateway Startup Event Loop Block

**Optimization:** Replaced blocking `time.sleep()` with `await asyncio.sleep()` in the async `start_gateway` process termination wait loop.
**Impact:** Restores asynchronous execution of background tasks (like background cron timers, background connections, or tick mechanisms) during the gateway startup phase (which could take up to 10 seconds).
**Context:** When a service restarts with `--replace`, it polls the system using `_pid_exists` checking if the previous instance has shut down gracefully before forceful termination. Doing `time.sleep(0.5)` halted the whole event loop. Async sleep allows background event loop tasks to continue their tick cycles and execution.

## Kanban Task Links Optimization
- **Optimization**: Batch inserting `task_links` via `executemany` instead of single looping `INSERT OR IGNORE` commands on `sqlite3.Connection`.
- **Learnings**: SQLite batch execution provides significant gains (12-36%) on bulk inserts. We must evaluate generator conversion carefully — avoiding exhausting `Iterable` objects like `parents` when they need to be reused later on in the same scope (e.g. inside `_append_event`). Converting to `list` first guarantees the optimization works correctly and prevents bugs.

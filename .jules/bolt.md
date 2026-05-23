## 2024-05-16 - [Fast batch tokenization in python]
**Learning:** HuggingFace `tokenizer` batch encoding (passing a list of texts to `tokenizer(texts)`) is approximately 3x faster than calling `tokenizer.encode(text)` in a loop, as it delegates the iteration down to the optimized Rust implementation within the `transformers` library. This is critical when computing token counts across multiple turns within a chat trajectory.
**Action:** When working with tokenizers and a list of texts, prefer passing the entire list to the tokenizer at once rather than looping over items, making sure to fallback gracefully to character limits if the tokenizer object is absent or errors out.

# Performance Learnings (Bolt Workflow)

## Kanban Task Links Optimization
- **Optimization**: Batch inserting `task_links` via `executemany` instead of single looping `INSERT OR IGNORE` commands on `sqlite3.Connection`.
- **Learnings**: SQLite batch execution provides significant gains (12-36%) on bulk inserts. We must evaluate generator conversion carefully — avoiding exhausting `Iterable` objects like `parents` when they need to be reused later on in the same scope (e.g. inside `_append_event`). Converting to `list` first guarantees the optimization works correctly and prevents bugs.

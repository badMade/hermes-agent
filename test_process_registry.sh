uv run --with pytest-asyncio --with pytest-xdist --with faster-whisper pytest tests/tools/test_process_registry.py::TestStdinHelpers::test_close_stdin_allows_eof_driven_process_to_finish

#!/bin/bash
export PYTHONPATH=".:/usr/lib/python3/dist-packages:/home/jules/.local/share/pipx/venvs/poetry/lib/python3.12/site-packages/"
uv run pytest -c /dev/null tests/ > /tmp/tests_out.txt 2>&1
echo "Pytest exit code: $?"
tail -n 30 /tmp/tests_out.txt

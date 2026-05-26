import urllib.request
import json
import os

req = urllib.request.Request(
    "http://127.0.0.1:8000/submit",
    data=json.dumps({
        "branch_name": "jules-1287422288524102117-a199a6df",
        "commit_message": "🧪 Add tests for format_session_db_unavailable",
        "title": "🧪 Add tests for format_session_db_unavailable",
        "description": "🎯 **What:** \nAdded unit tests to `tests/test_hermes_state.py` for the `format_session_db_unavailable` function to ensure it properly handles edge cases and errors related to Session DB state.\n\n📊 **Coverage:** \n- `test_no_error_set`: Validates proper formatting when there is no underlying init error set.\n- `test_generic_error_set`: Validates proper formatting with the prefix prepended to a generic database error strings.\n- `test_nfs_marker_error_set`: Validates that specific marker errors, such as \"locking protocol\" (typically associated with NFS/SMB filesystem restrictions for WAL journaling), correctly emit the detailed formatting with an explanatory URL suffix.\n\n✨ **Result:** \nThe tests correctly exercise `format_session_db_unavailable()`, increasing overall codebase coverage and verifying the stability of user-facing fallback error reporting."
    }).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)
try:
    with urllib.request.urlopen(req) as f:
        print(f.read().decode('utf-8'))
except Exception as e:
    print(e)

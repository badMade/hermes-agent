import urllib.request
import json
import os
import subprocess

def get_current_branch():
    return subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).decode('utf-8').strip()

def get_pr_info():
    # Simplified version, usually gh cli is better
    pass

# We don't have gh cli, I'll use the memory snippet: "The `gh` CLI tool is not installed in the environment. To fetch GitHub PRs, issues, or review comments, execute a Python script using `urllib.request` and `json` via `run_in_bash_session`."

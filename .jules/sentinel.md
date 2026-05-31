## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2024-10-25 - [Sanitize Subprocess Environments for `shell=True` Subprocesses]
**Vulnerability:** Several utility files like `hermes_cli/memory_setup.py`, `hermes_cli/tools_config.py`, `tools/environments/docker.py`, and `tools/transcription_tools.py` were executing child processes using `subprocess.run(..., shell=True)` and `subprocess.Popen(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes executing untrusted or user-supplied shell commands (e.g., checking external tool existence or docker container removal).
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing `shell=True` commands or when untrusted processes are spawned.

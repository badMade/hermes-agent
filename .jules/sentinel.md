## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2024-05-24 - [Sanitize Subprocess Environments in Local Transcription Tools]
**Vulnerability:** Command injection and credential leakage vulnerability in `tools/transcription_tools.py` via `_transcribe_local_command`.
**Learning:** `subprocess.run(command, shell=True)` was used to run configured local STT commands (which can be modified) without sanitizing the environment variables passed to the child process. This means sensitive API keys available in the parent process's environment were being passed down to an untrusted local script or executable.
**Prevention:** Always explicitly pass `env=_sanitize_subprocess_env(os.environ.copy())` to `subprocess.run` or `subprocess.Popen` when `shell=True` is used or when executing external user-defined commands, to prevent secret leakage.

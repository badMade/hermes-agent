## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2025-02-26 - [Replace xml.etree with defusedxml to prevent XXE]
**Vulnerability:** The codebase was using `xml.etree.ElementTree.fromstring` and `xml.etree.ElementTree.parse` to parse untrusted XML data. This module is natively vulnerable to XML External Entity (XXE) injections, allowing malicious XML documents to access local files, conduct Server-Side Request Forgery (SSRF), or cause Denial of Service (Billion Laughs attack).
**Learning:** Python's built-in `xml.etree` is unsafe for parsing untrusted or external XML payloads.
**Prevention:** Always use `defusedxml.ElementTree` or `defusedxml.minidom` for parsing XML that could contain untrusted data.

## 2026-06-19 - [Fix Command Injection in Local STT Transcription]
**Vulnerability:** The local STT command execution (`_transcribe_local_command`) in `tools/transcription_tools.py` used `subprocess.run(..., shell=True)` with a formatted command string.
**Learning:** Even when inputs are quoted, `shell=True` is inherently unsafe for command execution when local binaries like Whisper can be executed directly as an argument list.
**Prevention:** Always tokenize command strings using `shlex.split()` and use `shell=False` for local binary execution without shell dependencies.

## 2025-02-27 - [Fix Zip Slip Vulnerability in File Sync]
**Vulnerability:** The `tools/environments/file_sync.py` script was extracting untrusted tarball archives fetched from remote environments using `tar.extractall(..., filter="data")` without an explicit pre-extraction path validation, and failing outright on older Python versions.
**Learning:** Python's native `tarfile` module relies entirely on the `filter="data"` backward compatibility which might not be supported on older interpreter versions. Even with it, it's safer to always validate extraction paths natively when handling untrusted files to prevent arbitrary host file overwrites (Zip Slip/Path Traversal vulnerabilities) entirely.
**Prevention:** Always manually validate each member using `tar.getmembers()` ensuring paths do not begin with `/` or contain `..` using `.split("/")`, and defensively wrap `tar.extractall` in a `try/except TypeError` with a fallback `extractall` call.

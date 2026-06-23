## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2024-05-25 - Security Enhancement: SQL Injection Prevention with LIMIT
**Vulnerability:** SQL Injection via string-interpolated subqueries with LIMIT. The `query` function in `optional-skills/mcp/fastmcp/templates/database_server.py` wrapped user SQL in a subquery: `SELECT * FROM ({sql}) LIMIT N`. This allowed malicious users to bypass simple checks (e.g. ensuring it starts with SELECT) and inject additional clauses or statements by manipulating the closing parenthesis.
**Learning:** SQLite does not natively support parameterization for the FROM clause (e.g., subqueries or table names). Attempting to string-interpolate user input into a subquery creates an injection vector, especially when trying to enforce a LIMIT clause on user-provided queries.
**Prevention:** To prevent SQL injection when applying limits to user-provided SQL queries, execute the raw user query directly and restrict the output rows in Python using `cursor.fetchmany(limit)` instead of trying to wrap the query in another SELECT with a LIMIT clause.
## 2024-05-24 - Security Enhancement: Shell Injection Prevention
**Vulnerability:** Use of `subprocess.run(shell=True)` in `hermes_cli/tools_config.py` for cua-driver installation.
**Learning:** Using `shell=True` can introduce shell injection vulnerabilities, especially if any parts of the command are dynamic. Although this specific case was a hardcoded URL string, it's best practice to replace `shell=True` with an argument list for defense in depth.
**Prevention:** Avoid `shell=True` in `subprocess.run` and pass the command and its arguments as a list. When using `bash -c`, pass the script content as an argument to `-c` rather than interpolating it into a single string with `shell=True`.

## 2024-05-26 - Security Enhancement: Zip Slip Prevention in Tar Extraction
**Vulnerability:** Use of `tar.extractall()` without path validation allows Zip Slip (Path Traversal / CWE-22) vulnerabilities. An attacker could craft an archive with member names starting with `/` or containing `..` to overwrite arbitrary files on the system. Symlinks, hardlinks, and device nodes in archives are additional attack vectors even when member names appear safe.
**Learning:** Python's `tarfile.extractall()` does not safely validate member paths before Python 3.12 (unless `filter='data'` is used, which is unavailable in older versions). Even when downloading from a trusted source, it is best practice to always explicitly validate paths to defend against compromised archives or Man-in-the-Middle attacks. Silently skipping unsafe members is also insufficient — it can hide tampering and cause confusing failures downstream.
**Prevention:** Fail closed on any unsafe tar member. Before calling `extractall()`, iterate over `tar.getmembers()` and raise `tarfile.TarError` for: (1) paths that are absolute or contain `..`, (2) any member that is not a regular file or directory (e.g. symlinks, hardlinks, device nodes). After validation raises on any unsafe member, use `tar.extractall(path, filter="data")` on Python 3.12+ and fall back to `tar.extractall(path)` on older versions (safe because the validation loop already rejected non-regular members). For production code, use `_safe_extract_tar_archive()` in `hermes_cli/main.py`, which performs fully manual extraction via `tar.extractfile()` to avoid `extractall()` entirely.

## 2025-02-26 - [Replace xml.etree with defusedxml to prevent XXE]
**Vulnerability:** The codebase was using `xml.etree.ElementTree.fromstring` and `xml.etree.ElementTree.parse` to parse untrusted XML data. This module is natively vulnerable to XML External Entity (XXE) injections, allowing malicious XML documents to access local files, conduct Server-Side Request Forgery (SSRF), or cause Denial of Service (Billion Laughs attack).
**Learning:** Python's built-in `xml.etree` is unsafe for parsing untrusted or external XML payloads.
**Prevention:** Always use `defusedxml.ElementTree` or `defusedxml.minidom` for parsing XML that could contain untrusted data.

## 2026-06-19 - [Fix Command Injection in Local STT Transcription]
**Vulnerability:** The local STT command execution (`_transcribe_local_command`) in `tools/transcription_tools.py` used `subprocess.run(..., shell=True)` with a formatted command string.
**Learning:** Even when inputs are quoted, `shell=True` is inherently unsafe for command execution when local binaries like Whisper can be executed directly as an argument list.
**Prevention:** Always tokenize command strings using `shlex.split()` and use `shell=False` for local binary execution without shell dependencies.

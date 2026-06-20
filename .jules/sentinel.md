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
## 2024-06-15 - Security Enhancement: Zip Slip Prevention in Tar Archives
**Vulnerability:** Path Traversal (Zip Slip) vulnerability via `tarfile.extractall()`.
**Learning:** Extracting untrusted tar archives without validating the names of the members allows attackers to craft filenames containing absolute paths (`/`) or directory traversal sequences (`..`). This allows arbitrary file overwrite.
**Prevention:** Always validate `member.name` for each item in the archive using `tar.getmembers()` to ensure it doesn't contain absolute paths or `..` before extracting. Additionally, use `filter="data"` with `extractall` wrapped in a `try...except TypeError` fallback to support older Python versions while maintaining modern protection.
## 2025-02-26 - [Replace xml.etree with defusedxml to prevent XXE]
**Vulnerability:** The codebase was using `xml.etree.ElementTree.fromstring` and `xml.etree.ElementTree.parse` to parse untrusted XML data. This module is natively vulnerable to XML External Entity (XXE) injections, allowing malicious XML documents to access local files, conduct Server-Side Request Forgery (SSRF), or cause Denial of Service (Billion Laughs attack).
**Learning:** Python's built-in `xml.etree` is unsafe for parsing untrusted or external XML payloads.
**Prevention:** Always use `defusedxml.ElementTree` or `defusedxml.minidom` for parsing XML that could contain untrusted data.

## 2026-06-19 - [Fix Command Injection in Local STT Transcription]
**Vulnerability:** The local STT command execution (`_transcribe_local_command`) in `tools/transcription_tools.py` used `subprocess.run(..., shell=True)` with a formatted command string.
**Learning:** Even when inputs are quoted, `shell=True` is inherently unsafe for command execution when local binaries like Whisper can be executed directly as an argument list.
**Prevention:** Always tokenize command strings using `shlex.split()` and use `shell=False` for local binary execution without shell dependencies.

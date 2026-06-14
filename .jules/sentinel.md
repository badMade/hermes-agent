## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2025-02-26 - [Replace xml.etree with defusedxml to prevent XXE]
**Vulnerability:** The codebase was using `xml.etree.ElementTree.fromstring` and `xml.etree.ElementTree.parse` to parse untrusted XML data. This module is natively vulnerable to XML External Entity (XXE) injections, allowing malicious XML documents to access local files, conduct Server-Side Request Forgery (SSRF), or cause Denial of Service (Billion Laughs attack).
**Learning:** Python's built-in `xml.etree` is unsafe for parsing untrusted or external XML payloads.
**Prevention:** Always use `defusedxml.ElementTree` or `defusedxml.minidom` for parsing XML that could contain untrusted data.

## 2024-05-25 - Security Enhancement: SQL Injection Prevention with LIMIT
**Vulnerability:** SQL Injection via string-interpolated subqueries with LIMIT. The `query` function in `optional-skills/mcp/fastmcp/templates/database_server.py` wrapped user SQL in a subquery: `SELECT * FROM ({sql}) LIMIT N`. This allowed malicious users to bypass simple checks (e.g. ensuring it starts with SELECT) and inject additional clauses or statements by manipulating the closing parenthesis.
**Learning:** SQLite does not natively support parameterization for the FROM clause (e.g., subqueries or table names). Attempting to string-interpolate user input into a subquery creates an injection vector, especially when trying to enforce a LIMIT clause on user-provided queries.
**Prevention:** To prevent SQL injection when applying limits to user-provided SQL queries, execute the raw user query directly and restrict the output rows in Python using `cursor.fetchmany(limit)` instead of trying to wrap the query in another SELECT with a LIMIT clause.
## 2024-05-24 - Security Enhancement: Shell Injection Prevention
**Vulnerability:** Use of `subprocess.run(shell=True)` in `hermes_cli/tools_config.py` for cua-driver installation.
**Learning:** Using `shell=True` can introduce shell injection vulnerabilities, especially if any parts of the command are dynamic. Although this specific case was a hardcoded URL string, it's best practice to replace `shell=True` with an argument list for defense in depth.
**Prevention:** Avoid `shell=True` in `subprocess.run` and pass the command and its arguments as a list. When using `bash -c`, pass the script content as an argument to `-c` rather than interpolating it into a single string with `shell=True`.

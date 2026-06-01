## 2024-05-24 - Security Enhancement: YAML Parsing & Subprocess Execution
**Vulnerability:** Use of `yaml.load` and `subprocess.run(shell=True)`.
**Learning:** `yaml.load(value, Loader=yaml.CSafeLoader)` is structurally equivalent to `yaml.safe_load(value)` but has significant performance advantages, so it is safe to keep it this way. `subprocess.run(shell=True)` can introduce shell injection vulnerabilities and should be replaced with a list of arguments and `shell=False`. When updating `subprocess.run` to not use `shell=True`, be careful to update the test mocks to correctly handle `shlex.split()` list format.
**Prevention:** Avoid `shell=True` in `subprocess` unless absolutely necessary, and prefer passing commands as argument lists. Update test mocks accordingly.

## 2024-05-25 - Security Enhancement: SQL Injection Prevention with LIMIT
**Vulnerability:** SQL Injection via string-interpolated subqueries with LIMIT. The `query` function in `optional-skills/mcp/fastmcp/templates/database_server.py` wrapped user SQL in a subquery: `SELECT * FROM ({sql}) LIMIT N`. This allowed malicious users to bypass simple checks (e.g. ensuring it starts with SELECT) and inject additional clauses or statements by manipulating the closing parenthesis.
**Learning:** SQLite does not natively support parameterization for the FROM clause (e.g., subqueries or table names). Attempting to string-interpolate user input into a subquery creates an injection vector, especially when trying to enforce a LIMIT clause on user-provided queries.
**Prevention:** To prevent SQL injection when applying limits to user-provided SQL queries, execute the raw user query directly and restrict the output rows in Python using `cursor.fetchmany(limit)` instead of trying to wrap the query in another SELECT with a LIMIT clause.

## 2024-06-03 - Security Enhancement: Safe Subprocess Execution
**Vulnerability:** Shell injection via `subprocess.run(shell=True)` in user-configurable flows.
**Learning:** Relying on `shell=True` when processing user-defined configuration strings (like `quick_commands` and `shell.exec`) allows execution of unintended arbitrary shell operators (e.g., pipes, semicolons). Even if intended for convenience, it poses an unacceptable security risk in the agent environment. Furthermore, when substituting dynamic content into subprocess templates, one must use `shlex.split()` on the template command *before* substituting arguments containing spaces, or rely on secure list formats from the start.
**Prevention:** Replace `shell=True` with an explicit list of arguments. When parsing user-defined command strings, use `shlex.split(command)` to safely tokenize the command prior to execution without involving the shell.

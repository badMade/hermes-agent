## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2025-02-28 - [Prevent XML External Entity (XXE) vulnerabilities in XML Parsing]
**Vulnerability:** The application used standard `xml.etree.ElementTree` to parse untrusted XML responses (e.g., from external APIs or uploaded documents), making it susceptible to XML External Entity (XXE) injection attacks.
**Learning:** Standard XML parsers in Python do not protect against maliciously crafted XML containing external entities, which can lead to data exfiltration, denial of service (DoS), or server-side request forgery (SSRF).
**Prevention:** Always use `defusedxml` (e.g., `defusedxml.ElementTree` or `defusedxml.minidom`) when parsing XML data from untrusted sources to safely disable external entity resolution and prevent XXE.

## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.

## 2026-06-02 - [XXE Injection Vulnerabilities in XML Parsing]
**Vulnerability:** Multiple modules (`optional-skills/devops/watchers/scripts/watch_rss.py`, `gateway/platforms/wecom_callback.py`, `skills/research/arxiv/scripts/search_arxiv.py`) parsed untrusted XML data (such as external RSS feeds, API callbacks, and external Search Results) using the native `xml.etree.ElementTree` library, which is vulnerable to XML External Entity (XXE) injection attacks.
**Learning:** Native Python XML libraries are unsafe for untrusted data. Malicious payloads could allow an attacker to read local files, cause Denial of Service (DoS), or perform Server-Side Request Forgery (SSRF) when parsing untrusted external XML.
**Prevention:** Always use the `defusedxml` package (e.g. `defusedxml.ElementTree` or `defusedxml.minidom`) to securely parse untrusted XML strings. Note that `defusedxml` is purely for parsing; native standard libraries like `xml.etree.ElementTree` can still be used for constructing XML elements.

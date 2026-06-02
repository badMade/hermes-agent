## 2024-05-24 - [Sanitize Subprocess Environments for `quick_commands` and `shell.exec`]
**Vulnerability:** The CLI and TUI Gateway executed user-defined `quick_commands` and arbitrary shell commands (`shell.exec`) using `subprocess.run(..., shell=True)` without sanitizing the environment variables passed to the child process.
**Learning:** This exposed sensitive API keys and credentials contained in the main Hermes process environment to these child processes, allowing for easy credential exfiltration by a malicious config or user interaction.
**Prevention:** Always use `tools.environments.local._sanitize_subprocess_env` to filter the environment before passing it to `subprocess` execution mechanisms when executing untrusted or user-supplied shell commands.
## 2024-11-20 - [Fix XXE vulnerabilities in XML parsing]
**Vulnerability:** The codebase uses `xml.etree.ElementTree.fromstring` to parse untrusted XML data (e.g., in `wecom_callback.py`, `watch_rss.py`, `search_arxiv.py`), which is vulnerable to XML External Entity (XXE) attacks.
**Learning:** `xml.etree.ElementTree` is vulnerable to XXE attacks. We should use `defusedxml` which is specifically designed to prevent these vulnerabilities by overriding the vulnerable methods.
**Prevention:** Replace `xml.etree.ElementTree.fromstring` and `xml.etree.ElementTree.parse` with `defusedxml.ElementTree.fromstring` and `defusedxml.ElementTree.parse` when parsing untrusted XML, especially for data from network requests.

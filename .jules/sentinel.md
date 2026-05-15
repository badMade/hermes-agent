## 2024-05-24 - Security Enhancement: YAML Parsing & Subprocess Execution
**Vulnerability:** Use of `subprocess.run(shell=True)` in local STT command execution.
**Learning:** `shell=True` can enable shell injection and should be replaced with argv invocation and `shell=False`. The YAML path already used `CSafeLoader`/`SafeLoader`; updates there are about preserving safe semantics and performance clarity, not fixing unsafe deserialization.
**Prevention:** Avoid `shell=True` in `subprocess` unless absolutely necessary, and prefer passing commands as argument lists. Keep YAML parsing on safe loaders, preferring `CSafeLoader` when available.

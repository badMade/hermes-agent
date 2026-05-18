## 2024-05-18 - Prevent Command Injection with Templated Strings in Subprocess
**Vulnerability:** Command Injection via Subprocess Template Strings (`shell=True`).
**Learning:** `tools/transcription_tools.py` executed local stt commands using `.format()` on user-controlled inputs with `shell=True`. Using `shlex.quote` in `shell=True` isn't foolproof enough when strings contain spaces.
**Prevention:** When mitigating command injection in subprocess calls using templated strings, tokenize the template with `shlex.split()` first, then substitute variables into the resulting list items. This ensures variables containing spaces (like file paths) are not improperly split and avoids argument injection. Finally pass the resulting list into `subprocess.run(args, check=True)` without `shell=True`.

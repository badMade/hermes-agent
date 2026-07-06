import sys
import yaml
import subprocess
import os

meta = {"external_dependencies": [{"name": "brv", "check": "brv --version", "install": "echo install"}]}

ext_deps = meta.get("external_dependencies", [])
for dep in ext_deps:
    dep_name = dep.get("name", "")
    check_cmd = dep.get("check", "")
    install_cmd = dep.get("install", "")
    if check_cmd:
        try:
            import shlex
            from tools.environments.local import _sanitize_subprocess_env
            sanitized_env = _sanitize_subprocess_env(os.environ.copy())
            subprocess.run(
                shlex.split(check_cmd), shell=False, capture_output=True, timeout=5, env=sanitized_env
            )
            print("check_cmd ran")
        except Exception as e:
            print(f"check_cmd failed: {e}")
            if install_cmd:
                print(f"\n  ⚠ '{dep_name}' not found. Install with:")
                print(f"    {install_cmd}")

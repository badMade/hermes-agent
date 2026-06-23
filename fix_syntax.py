import re

def modify_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # The issue:
    # 6894 |         with tarfile.open(archive) as tar:
    # 6895 |             for member in tar.getmembers():
    # 6896 |                 name = member.name
    # 6897 |                 if (
    # 6898 |                     name.startswith("/")
    # 6899 |                     or ".." in __import__("pathlib").Path(name).parts
    # 6900 |                 ):
    # 6901 |                     raise tarfile.TarError(f"refusing to extract unsafe path: {name!r}")

    # We will just rewrite the `if` block safely.

    new_if_block = """                if name.startswith("/") or ".." in __import__("pathlib").Path(name).parts:"""

    content = re.sub(
        r'                if \(\n                    name.startswith\("/"\)\n                    or "\.\." in __import__\("pathlib"\)\.Path\(name\)\.parts\n                \):',
        new_if_block,
        content
    )

    with open(filepath, 'w') as f:
        f.write(content)

modify_file('hermes_cli/main.py')
modify_file('scripts/install_psutil_android.py')

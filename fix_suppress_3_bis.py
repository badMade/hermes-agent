import re

def modify_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # The string replace wasn't applied, probably due to some character issue.
    # Let's write `os.geteuid() != 0` in a way ruff won't format to a separate line.

    # We will format it as `if os.geteuid() != 0:  # windows-footgun: ok`

    # Replace:
    #    try:
    #        if (
    #            os.geteuid()
    #            != 0  # windows-footgun: ok — Linux FHS helper, guarded by sys.platform == "linux" above + AttributeError catch
    #        ):
    #            return

    content = re.sub(
        r'    try:\n        if \(\n            os\.geteuid\(\)\n            != 0  # windows-footgun: ok — Linux FHS helper, guarded by sys\.platform == "linux" above \+ AttributeError catch\n        \):\n            return',
        r'    try:\n        if os.geteuid() != 0:  # windows-footgun: ok — Linux FHS helper, guarded by sys.platform == "linux" above + AttributeError catch\n            return',
        content
    )

    with open(filepath, 'w') as f:
        f.write(content)

modify_file('hermes_cli/main.py')

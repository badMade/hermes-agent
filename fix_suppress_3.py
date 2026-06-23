import re

def modify_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # The issue is that the ruff formatting splits `os.geteuid()` onto its own line.
    # The footgun checker expects `# windows-footgun: ok` on the same line as the call.

    content = content.replace(
        "            os.geteuid()\n            != 0  # windows-footgun: ok — Linux FHS helper, guarded by sys.platform == \"linux\" above + AttributeError catch",
        "            os.geteuid() != 0  # windows-footgun: ok — Linux FHS helper, guarded by sys.platform == \"linux\" above + AttributeError catch"
    )

    with open(filepath, 'w') as f:
        f.write(content)

modify_file('hermes_cli/main.py')

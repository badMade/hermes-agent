import re

def modify_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # We will format it as:
    #    try:
    #        uid = os.geteuid()  # windows-footgun: ok — Linux FHS helper
    #        if uid != 0:
    #            return

    # In reality the previous regex missed because I had already formatted it with `os.geteuid() != 0` on line 7237.
    # Let's replace the EXACT lines now.

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if 'os.geteuid() != 0  # windows-footgun: ok' in line:
            lines[i] = "        uid = os.geteuid()  # windows-footgun: ok — Linux FHS helper, guarded by sys.platform == \"linux\" above + AttributeError catch"
            lines.insert(i+1, "        if uid != 0:")
            break

    # Then we need to fix the parentheses from the if block
    for i, line in enumerate(lines):
        if line.strip() == "if (":
            if lines[i+1].strip().startswith("uid = os.geteuid()"):
                lines[i] = ""
                # remove the closing parenthesis on line i+3
                for j in range(i+2, i+5):
                    if lines[j].strip() == "):":
                        lines[j] = ""
                break

    content = '\n'.join(lines) + '\n'

    with open(filepath, 'w') as f:
        f.write(content)

modify_file('hermes_cli/main.py')

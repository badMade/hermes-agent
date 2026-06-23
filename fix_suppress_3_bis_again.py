import re

def modify_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # We will format it as:
    #    try:
    #        uid = os.geteuid()  # windows-footgun: ok — Linux FHS helper
    #        if uid != 0:
    #            return

    content = re.sub(
        r'    try:\n        if os\.geteuid\(\) != 0:  # windows-footgun: ok — Linux FHS helper, guarded by sys\.platform == "linux" above \+ AttributeError catch\n            return',
        r'    try:\n        uid = os.geteuid()  # windows-footgun: ok — Linux FHS helper\n        if uid != 0:\n            return',
        content
    )

    with open(filepath, 'w') as f:
        f.write(content)

modify_file('hermes_cli/main.py')

import re

file_path = 'ui-tui/packages/hermes-ink/src/ink/events/keyboard-event.ts'
with open(file_path, 'r') as f:
    content = f.read()

content = content.replace("this.meta = parsedKey.meta || parsedKey.option", "this.meta = Boolean(parsedKey.meta)")

with open(file_path, 'w') as f:
    f.write(content)

file_path = 'ui-tui/packages/hermes-ink/src/ink/events/input-event.ts'
with open(file_path, 'r') as f:
    content = f.read()

content = re.sub(
    r"    // `parseKeypress` parses \\u001B\\u001B\[A \(meta \+ up arrow\) as meta = false\n    // but with option = true, so we need to take this into account here\n    // to avoid breaking changes in Ink\.\n    // TODO\(vadimdemedes\): consider removing this in the next major version\.\n    meta: keypress\.meta \|\| keypress\.name === 'escape' \|\| keypress\.option,",
    "    meta: Boolean(keypress.meta),",
    content,
    flags=re.MULTILINE
)

content = re.sub(
    r"  // Strip meta if it's still remaining after `parseKeypress`\n  // TODO\(vadimdemedes\): remove this in the next major version\.\n  if \(input\.startsWith\('\\u001B'\)\) {\n    input = input\.slice\(1\)\n  }\n\n",
    "",
    content,
    flags=re.MULTILINE
)

with open(file_path, 'w') as f:
    f.write(content)
print("Patched")

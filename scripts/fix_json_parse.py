"""Fix JSON parsing in all dept/manager agents to properly strip code fences."""
import os, re

FENCE_RE = re.compile(r'```(?:json)?\s*([\s\S]*?)```')

def extract_json(text):
    m = FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()

# The replacement for try block in dept agents
OLD_BLOCK = '''        try:
            import re as _re
            _m = _re.search(r\'```(?:json)?\\s*([\\s\\S]*?)```\', response.content)
            _c = _m.group(1).strip() if _m else response.content.strip()
            parsed = json.loads(_c)'''

NEW_BLOCK = '''        try:
            import re as _re2
            _fm = _re2.search(r\'```[\\w]*\\s*([\\s\\S]*?)```\', response.content)
            _c = _fm.group(1).strip() if _fm else response.content.strip()
            parsed = json.loads(_c)'''

# Also handle files that still have the original buggy version
OLD_BUGGY = '''        try:
            # Strip markdown code fences
            _c = response.content.strip()'''

NEW_CLEAN = '''        try:
            import re as _re2
            _fm = _re2.search(r\'```[\\w]*\\s*([\\s\\S]*?)```\', response.content)
            _c = _fm.group(1).strip() if _fm else response.content.strip()'''

count = 0
for root, dirs, files in os.walk('agents'):
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        if os.path.join('ceo', 'agent.py') in path.replace('\\', '/'):
            continue
        txt = open(path, encoding='utf-8').read()
        new = txt

        if OLD_BLOCK in new:
            new = new.replace(OLD_BLOCK, NEW_BLOCK)
        elif OLD_BUGGY in new:
            # Remove the old buggy strip block entirely, replace with clean version
            new = re.sub(
                r'        try:\n            # Strip markdown code fences\n'
                r'            _c = response\.content\.strip\(\)\n'
                r'            if _c\.startswith[^\n]+\n'
                r'(?:                [^\n]+\n)*'
                r'                _c = _c\.lstrip\(\'json\'\)\.strip\(\)\n'
                r'            ',
                NEW_CLEAN + '\n            ',
                new
            )

        if new != txt:
            open(path, 'w', encoding='utf-8').write(new)
            count += 1

print(f'Patched {count} agent files')

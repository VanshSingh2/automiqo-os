import os, re

PATTERN = re.compile(
    r'        try:\n'
    r'(?:            (?:import re.*|_[a-z_]+ ?=.*)\n)*'
    r'            parsed = json\.loads\(_c\)\n'
    r'            return AgentResponse\(\n'
    r'(?:                [^\n]+\n)+'
    r'            \)\n'
    r'        except Exception:\n'
    r'            return AgentResponse\(status="ok", summary=response\.content, metrics=state\)',
)

REPLACEMENT = '        return self._parse_response(response.content)'

count = 0
for root, dirs, files in os.walk('agents'):
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        norm = path.replace('\\', '/')
        if norm.endswith('executive/ceo/agent.py'):
            continue
        txt = open(path, encoding='utf-8').read()
        new = PATTERN.sub(REPLACEMENT, txt)
        if new != txt:
            open(path, 'w', encoding='utf-8').write(new)
            count += 1

print(f'Replaced parse blocks in {count} files')

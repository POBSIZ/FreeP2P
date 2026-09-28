"""Check the exact Git index before publishing; never print matched secrets."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
rules = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github-token': rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}',
    'aws-key': rb'AKIA[A-Z0-9]{16}',
    'real-invite': rb'fpm?1:[A-Za-z0-9_-]{80,}',
    'local-control-token': rb'https?://(?:127\.0\.0\.1|localhost):\d+/#[-A-Za-z0-9_]{25,}',
    'personal-path': rb'(?:[A-Z]:[\\/]Users[\\/][^\s]+|/Users/[a-z][^/\s]+/)',
}
forbidden = {'.venv','.build-venv','test_runs','release','dist','build','.ssh'}
errors = []
for name in filter(None, paths):
    path = Path(name)
    if forbidden.intersection(path.parts) or path.suffix.lower() in {'.pem','.key','.pfx','.p12','.log'} or path.name in {'.env','instance.json','instance.lock'}:
        errors.append((name, 'forbidden-file'))
    data = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
    if path.suffix.lower() in {'.png','.ico','.icns'}:
        continue  # Generated exclusively from synthetic UI data/vector icon.
    for label, pattern in rules.items():
        if re.search(pattern, data):
            errors.append((name, label))
    if path.suffix == '.md':
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', data.decode('utf-8')):
            if '://' not in target and not target.startswith('#') and not (ROOT / path.parent / target.split('#')[0]).exists():
                errors.append((name, 'broken-local-link:' + target))
if errors:
    for name, label in errors:
        print(f'FAIL: {name}: {label}')
    raise SystemExit(1)
print(f'PASS: {len(list(filter(None, paths)))} indexed files; secret patterns, excluded paths and document links checked.')

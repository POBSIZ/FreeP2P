"""Run with a build venv's Python on the target OS."""
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from collect_notices import collect

ROOT = Path(__file__).resolve().parents[1]
collect(ROOT / 'build/notices')
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                str(ROOT / 'FreeP2P.spec')], cwd=ROOT, check=True)
release = ROOT / 'release'
release.mkdir(exist_ok=True)
machine = platform.machine().lower()
arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64'}.get(machine, machine)
name = f'FreeP2P-0.1.0-{platform.system().lower()}-{arch}'
archive = release / (name + '.zip')
if sys.platform == 'darwin':
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                    str(ROOT / 'dist/FreeP2P.app'), str(archive)], check=True)
else:
    shutil.make_archive(str(release / name), 'zip', ROOT / 'dist', 'FreeP2P')
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
print(f'Release: {archive}\nSHA256: {digest}')

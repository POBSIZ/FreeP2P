"""Collect bundled dependency licenses from the clean build environment."""
import importlib.metadata as metadata
from pathlib import Path
import sys


def collect(destination):
    destination.mkdir(parents=True, exist_ok=True)
    rows = ['Bundled/build dependencies and their upstream license notices:', '']
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        rows.append(f'{name} {dist.version}')
        for file in dist.files or []:
            if any(term in file.name.lower() for term in ('license', 'licence', 'copying', 'notice')) and '.dist-info' in str(file):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = destination / name / Path(*file.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
    import sysconfig
    candidates = [Path(sys.base_prefix) / 'LICENSE.txt', Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt']
    for source in candidates:
        if source.exists():
            (destination / 'PYTHON-LICENSE.txt').write_bytes(source.read_bytes())
            break
    else:
        raise RuntimeError('Python license not found; add its location before distributing')
    (destination / 'INDEX.txt').write_text('\n'.join(rows) + '\nPython: ' + sys.version.split()[0] + '\n', encoding='utf-8')

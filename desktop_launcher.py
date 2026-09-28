"""Portable desktop entry point. All runtime dependencies are bundled."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import webbrowser


def data_directory():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home()))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
    path = base / 'FreeP2P'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def acquire_lock(handle):
    handle.seek(0)
    if sys.platform == 'win32':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def main():
    parser = argparse.ArgumentParser(description='FreeP2P desktop launcher')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--local', action='store_true', help='Loopback test mode')
    parser.add_argument('--data-dir', type=Path, help='Separate application state directory')
    args = parser.parse_args()
    directory = args.data_dir or data_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = directory / 'instance.json'
    with (directory / 'instance.lock').open('a+b') as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b'0')
            lock.flush()
        try:
            acquire_lock(lock)
        except OSError:
            # The other instance may still be importing the bundled libraries.
            for _ in range(50):
                try:
                    url = json.loads(state.read_text(encoding='utf-8'))['url']
                    if not args.no_browser:
                        webbrowser.open(url)
                    return 0
                except (OSError, ValueError, KeyError):
                    time.sleep(0.1)
            raise RuntimeError('FreeP2P is already starting. Please try again shortly.')
        state.unlink(missing_ok=True)

        def ready(url):
            # Contains a local control token; restrict access on Unix.
            fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump({'url': url, 'pid': os.getpid()}, output)

        # Windowed builds have no stdout/stderr. Keep diagnostics available.
        with (directory / 'app.log').open('w', encoding='utf-8') as log:
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = log
            try:
                from minecraft_web import run
                args.port = 0  # OS selects a free local port.
                args.on_ready = ready
                asyncio.run(run(args))
            finally:
                state.unlink(missing_ok=True)
                sys.stdout, sys.stderr = old_stdout, old_stderr
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

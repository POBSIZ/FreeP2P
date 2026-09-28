"""Scheduled two-host smoke test of the real Peer engine (no signaling relay)."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from freep2p import Peer


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def read_control(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (FileNotFoundError, json.JSONDecodeError):
        # A producer may still be uploading/writing the control file.
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--role', required=True)
    args = parser.parse_args()
    folder = Path(args.directory)
    folder.mkdir(parents=True, exist_ok=True)
    peer = Peer(timeout=45)
    result = {'role': args.role, 'done': False, 'pass': False, 'states': [], 'events': []}
    sent = 0
    start = None
    next_message = 0
    last_snapshot = 0
    deadline = time.monotonic() + 600
    try:
        while time.monotonic() < deadline:
            peer.tick()
            if peer.public and not (folder / 'ready.json').exists():
                save(folder / 'ready.json', {'code': peer.code, 'public': peer.public,
                     'local_port': peer.sock.getsockname()[1]})
            control = folder / 'control.json'
            data = read_control(control) if start is None else None
            if data is not None:
                start = data['start_epoch']
                peer.connect(data['peer_code'])
                # Address exchange is complete; hold probes until the scheduled test.
                peer.state = 'ARMED'
            if start is not None and time.time() >= start and peer.state == 'ARMED':
                peer.retry()
            if peer.state == 'CONNECTED' and sent < 5 and time.monotonic() >= next_message:
                sent += 1
                peer.chat(f'FREEP2P-CROSS-HOST:{args.role}:{sent}')
                next_message = time.monotonic() + 2
            if not result['states'] or result['states'][-1]['state'] != peer.state:
                result['states'].append({'epoch': time.time(), 'state': peer.state})
            result.update(state=peer.state, public=peer.public, target=peer.target,
                          local_port=peer.sock.getsockname()[1], rtt_ms=peer.rtt,
                          sent=sent, pending=len(peer.pending), events=list(peer.events))
            received = [s for _, s in peer.events if s.startswith('상대 › FREEP2P-CROSS-HOST:')]
            receipts = [s for _, s in peer.events if s.startswith('전달 확인 #')]
            result.update(received=len(received), acknowledged=len(receipts))
            if start is not None and time.time() >= start + 60:
                result['done'] = True
                result['pass'] = len(received) == 5 and len(receipts) == 5 and peer.state == 'CONNECTED'
            if time.monotonic() >= last_snapshot + 1 or result['done']:
                save(folder / 'result.json', result)
                last_snapshot = time.monotonic()
            if result['done']:
                return 0 if result['pass'] else 1
            time.sleep(.02)
        raise TimeoutError('No scheduled test completed before the safety deadline')
    except Exception as error:
        result.update(done=True, error=str(error))
        save(folder / 'result.json', result)
        return 1
    finally:
        peer.close()


if __name__ == '__main__':
    raise SystemExit(main())

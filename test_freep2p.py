import hashlib
import hmac
import socket
import struct
import time
import unittest

from freep2p import COOKIE, Peer, UI, encode, invitation, parse_invitation, parse_stun, wrap


def response(tid, ip='203.0.113.8', port=45678):
    address = struct.unpack('!I', socket.inet_aton(ip))[0] ^ COOKIE
    attribute = struct.pack('!HHBBHI', 0x20, 8, 0, 1, port ^ (COOKIE >> 16), address)
    return struct.pack('!HHI12s', 0x101, len(attribute), COOKIE, tid) + attribute


class ProtocolTests(unittest.TestCase):
    def test_stun_validation(self):
        tid = b'a' * 12
        data = response(tid)
        self.assertEqual(parse_stun(data, tid), ('203.0.113.8', 45678))
        self.assertIsNone(parse_stun(data, b'b' * 12))
        for end in range(len(data)):
            self.assertIsNone(parse_stun(data[:end], tid))
        damaged = bytearray(data)
        damaged[22:24] = b'\xff\xff'
        self.assertIsNone(parse_stun(damaged, tid))

    def test_invitation(self):
        token = 'ab' * 16
        code = invitation(('127.0.0.1', 4567), token)
        self.assertEqual(parse_invitation(code), (('127.0.0.1', 4567), token))
        for bad in ('hello', 'fp1:?', invitation(('::1', 123), token), invitation(('127.0.0.1', 0), token)):
            with self.assertRaises(ValueError):
                parse_invitation(bad)

    def test_unicode_and_escape_sanitization(self):
        self.assertEqual(wrap('가나다라', 4), ['가나', '다라'])
        self.assertNotIn('\x1b', ''.join(wrap('hello\x1b[2J', 80)))


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.a = Peer('127.0.0.1', local=True, timeout=1)
        self.b = Peer('127.0.0.1', local=True, timeout=1)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)

    def pump(self, condition, seconds=2):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.a.tick()
            self.b.tick()
            if condition():
                return
            time.sleep(0.005)
        self.fail('condition timed out')

    def connect(self):
        self.a.connect(self.b.code)
        self.b.connect(self.a.code)
        self.pump(lambda: self.a.state == self.b.state == 'CONNECTED')

    def test_connection_and_bidirectional_chat_same_socket(self):
        before = self.a.sock.getsockname()
        self.connect()
        self.a.chat('안녕하세요')
        self.b.chat('Hello')
        self.pump(lambda: not self.a.pending and not self.b.pending)
        self.assertTrue(any('상대 › 안녕하세요' in text for _, text in self.b.events))
        self.assertTrue(any('상대 › Hello' in text for _, text in self.a.events))
        self.assertEqual(before, self.a.sock.getsockname())

    def test_retry_after_lost_receipt_does_not_duplicate_chat(self):
        self.connect()
        real_send = self.b.send
        dropped = []
        def send(kind, text, seq=None):
            if kind == 'receipt' and not dropped:
                dropped.append(True)
                return None
            return real_send(kind, text, seq)
        self.b.send = send
        self.a.chat('once')
        self.pump(lambda: not self.a.pending, 3)
        self.assertEqual(sum('상대 › once' in text for _, text in self.b.events), 1)
        self.assertTrue(dropped)

    def test_unauthenticated_endpoint_change_rejected(self):
        self.connect()
        target = self.a.target
        for data in (b'garbage', b'[]', b'{"b":{},"m":"bad"}'):
            self.a.receive(data, ('127.0.0.2', 4444), time.monotonic())
        self.assertEqual(self.a.target, target)

    def test_timeout_and_retry(self):
        self.a.connect(self.b.code)
        self.a.started -= 2
        self.a.tick()
        self.assertEqual(self.a.state, 'FAILED')
        self.b.connect(self.a.code)
        self.a.retry()
        self.pump(lambda: self.a.state == self.b.state == 'CONNECTED')

    def test_chat_during_handshake_not_falsely_acknowledged(self):
        self.a.connect(self.b.code)
        self.b.connect(self.a.code)
        body = {'v': 1, 'n': 1, 't': 'chat', 'd': 'early'}
        wire = encode({'b': body, 'm': hmac.new(self.a.key, encode(body), hashlib.sha256).hexdigest()})
        self.b.receive(wire, self.a.public, time.monotonic())
        self.assertNotIn(1, self.b.seen)
        self.assertFalse(any('상대 › early' in text for _, text in self.b.events))

    def test_bracketed_paste_and_editing(self):
        ui = UI(self.a)
        ui.input('\x1b[200~' + self.b.code + '\n\x1b[201~')
        self.assertEqual(ui.buffer, self.b.code)
        self.assertIsNone(self.a.target)
        ui.input('\r')
        self.assertEqual(self.a.state, 'PUNCHING')
        ui.input('한글\x7f')
        self.assertEqual(ui.buffer, '한')

    def test_fake_stun_uses_same_socket_as_peer_connection(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0))
            server.settimeout(1)
            with_peer = Peer('127.0.0.1', servers=[f'127.0.0.1:{server.getsockname()[1]}'])
            self.addCleanup(with_peer.close)
            with_peer.tick()
            data, address = server.recvfrom(4096)
            server.sendto(response(data[8:20], *address), address)
            with_peer.tick()
            self.assertEqual(with_peer.public, address)
            self.assertEqual(with_peer.state, 'WAITING')
            self.assertEqual(with_peer.sock.getsockname(), address)


if __name__ == '__main__':
    unittest.main()

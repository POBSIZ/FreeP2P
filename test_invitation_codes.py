import hashlib
import unittest
import zlib

from cryptography.hazmat.primitives import serialization

from freep2p import encode
from mc_tunnel import b64, certificate, decode_code, encode_code, unb64


class InvitationCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cert = certificate()
        cls.der = cert.public_bytes(serialization.Encoding.DER)

    def invitation(self, role='host', name='My world'):
        data = {'role': role, 'name': name, 'ip': '192.0.2.10', 'port': 45678,
                'token': b64(bytes(range(32)))}
        if role == 'host':
            data['cert'] = b64(self.der)
        return data

    def packed(self, payload):
        return 'fpm2:' + b64(payload + zlib.crc32(payload).to_bytes(4, 'big'))

    def test_compact_round_trip_preserves_endpoint_identity_and_full_token(self):
        for role in ('host', 'guest'):
            codes = set()
            for name in ('A', 'My world', '나의 월드', '🧱' * 40):
                with self.subTest(role=role, name=name):
                    original = self.invitation(role, name)
                    encoded = encode_code(original)
                    decoded = decode_code(encoded)
                    self.assertTrue(encoded.startswith('f3h:' if role == 'host' else 'f3g:'))
                    self.assertEqual(len(encoded), 103 if role == 'host' else 60)
                    self.assertEqual(decoded['version'], 3)
                    self.assertEqual(decoded['name'], '호스트' if role == 'host' else '참가자')
                    for key in ('role', 'ip', 'port', 'token'):
                        self.assertEqual(decoded[key], original[key])
                    if role == 'host':
                        self.assertEqual(decoded['cert_sha256'], b64(hashlib.sha256(self.der).digest()))
                        self.assertNotIn('cert', decoded)
                    codes.add(encoded)
            self.assertEqual(len(codes), 1, 'The display name must not change or lengthen the code')

    def test_typical_codes_are_shorter_without_reducing_token_or_fingerprint(self):
        for role, maximum in (('host', 120), ('guest', 80)):
            data = self.invitation(role)
            compact = encode_code(data)
            legacy = 'fpm1:' + b64(encode(data))
            self.assertLessEqual(len(compact), maximum)
            self.assertLess(len(compact), len(legacy) // 2)
            self.assertEqual(len(unb64(decode_code(compact)['token'])), 32)
        self.assertEqual(len(unb64(decode_code(encode_code(self.invitation()))['cert_sha256'])), 32)

    def test_legacy_codes_keep_embedded_certificate_and_identity(self):
        for role in ('host', 'guest'):
            data = self.invitation(role)
            decoded = decode_code('fpm1:' + b64(encode(data)))
            self.assertEqual(decoded['version'], 1)
            for key, value in data.items():
                self.assertEqual(decoded[key], value)

    def test_v2_codes_preserve_names_and_can_still_be_read(self):
        for role in ('host', 'guest'):
            for name in ('A', '나의 월드', '🧱' * 40):
                data = self.invitation(role, name)
                code = encode_code(data, version=2)
                decoded = decode_code(code)
                self.assertTrue(code.startswith('fpm2:'))
                self.assertEqual(decoded['version'], 2)
                for key in ('role', 'name', 'ip', 'port', 'token'):
                    self.assertEqual(decoded[key], data[key])
                if role == 'host':
                    self.assertEqual(decoded['cert_sha256'], b64(hashlib.sha256(self.der).digest()))

    def test_accidental_changes_are_rejected(self):
        encoded = encode_code(self.invitation(), version=2)
        raw = unb64(encoded[5:])
        for index in (0, 2, 7, 30, len(raw) - 5, len(raw) - 1):
            damaged = bytearray(raw)
            damaged[index] ^= 1
            with self.subTest(index=index), self.assertRaises(ValueError):
                decode_code('fpm2:' + b64(damaged))
        for code in (encoded[:-1], encoded + 'A', 'fpm2:!', 'fpm2:', 'fpm3:abcd',
                     'fpm2:' + 'A' * 4096, None, 1, {}, []):
            with self.subTest(type=type(code).__name__), self.assertRaises(ValueError):
                decode_code(code)

    def test_malformed_binary_fields_are_rejected_even_with_valid_checksum(self):
        guest = unb64(encode_code(self.invitation('guest', 'A'), version=2)[5:])[:-4]
        malformed = [b'', guest[:38], guest[:39], bytes([9]) + guest[1:],
                     guest[:1] + b'\0\0\0\0' + guest[5:],
                     guest[:1] + bytes([224, 0, 0, 1]) + guest[5:],
                     guest[:1] + b'\xff\xff\xff\xff' + guest[5:],
                     guest[:5] + b'\0\0' + guest[7:],
                     guest[:39] + b'\xff', guest[:39] + b'A' * 41]
        host = unb64(encode_code(self.invitation('host', 'A'), version=2)[5:])[:-4]
        malformed.extend((host[:70], host[:71], host[:71] + b'\xff'))
        for index, payload in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(ValueError):
                decode_code(self.packed(payload))

    def test_v3_checksums_cover_the_prefix_and_every_payload_byte(self):
        for role in ('host', 'guest'):
            code = encode_code(self.invitation(role))
            prefix, raw = code[:4], unb64(code[4:])
            for index in range(len(raw)):
                damaged = bytearray(raw)
                damaged[index] ^= 1
                with self.subTest(role=role, index=index), self.assertRaises(ValueError):
                    decode_code(prefix + b64(damaged))
            other_prefix = 'f3g:' if role == 'host' else 'f3h:'
            wrong_checksum = zlib.crc32(other_prefix.encode('ascii') + raw[:-4]).to_bytes(4, 'big')
            for bad_code in (other_prefix + code[4:], prefix + b64(raw[:-4] + wrong_checksum),
                             code[:-1], code + 'A', prefix + '!', prefix):
                with self.subTest(role=role), self.assertRaises(ValueError):
                    decode_code(bad_code)

    def test_v3_fixed_lengths_and_endpoint_fields_are_enforced(self):
        for role in ('host', 'guest'):
            code = encode_code(self.invitation(role))
            prefix, payload = code[:4], unb64(code[4:])[:-4]
            malformed = (payload[:-1], payload + b'A', b'\0\0\0\0' + payload[4:],
                         bytes([224, 0, 0, 1]) + payload[4:], b'\xff' * 4 + payload[4:],
                         payload[:4] + b'\0\0' + payload[6:])
            for index, data in enumerate(malformed):
                checksum = zlib.crc32(prefix.encode('ascii') + data).to_bytes(4, 'big')
                with self.subTest(role=role, index=index), self.assertRaises(ValueError):
                    decode_code(prefix + b64(data + checksum))

    def test_invalid_input_fields_are_rejected_for_both_formats(self):
        cases = [('role', 'server'), ('name', ''), ('name', 'A' * 41), ('name', None),
                 ('ip', '0.0.0.0'), ('ip', '224.0.0.1'), ('ip', '255.255.255.255'),
                 ('ip', '::1'), ('port', 0), ('port', 65536), ('port', True),
                 ('port', '25565'), ('token', b64(b'short')), ('token', '!')]
        for key, value in cases:
            data = self.invitation()
            data[key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    encode_code(data)
                with self.assertRaises(ValueError):
                    encode_code(data, version=2)
                with self.assertRaises(ValueError):
                    decode_code('fpm1:' + b64(encode(data)))

    def test_legacy_invalid_certificate_and_forged_version_are_not_trusted(self):
        data = self.invitation()
        data['cert'] = b64(b'not a certificate')
        with self.assertRaises(ValueError):
            decode_code('fpm1:' + b64(encode(data)))
        data = self.invitation()
        data['version'] = 2
        data['cert_sha256'] = b64(b'wrong fingerprint'.ljust(32, b'\0'))
        decoded = decode_code('fpm1:' + b64(encode(data)))
        self.assertEqual(decoded['version'], 1)
        self.assertNotIn('cert_sha256', decoded)

    def test_compact_host_can_be_encoded_again_from_its_fingerprint(self):
        code = encode_code(self.invitation())
        self.assertEqual(encode_code(decode_code(code)), code)
        for fingerprint in ('!', b64(b'too short'), b64(b'x' * 33)):
            data = decode_code(code)
            data['cert_sha256'] = fingerprint
            with self.assertRaises(ValueError):
                encode_code(data)


if __name__ == '__main__':
    unittest.main()

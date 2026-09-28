import tempfile
import unittest
from pathlib import Path

from tools.network_probe import read_control, save


class ControlFileTests(unittest.TestCase):
    def test_missing_partial_and_complete_control(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'control.json'
            self.assertIsNone(read_control(path))
            for partial in ('', '{', '{"start_epoch":'):
                path.write_text(partial, encoding='utf-8')
                self.assertIsNone(read_control(path))
            expected = {'start_epoch': 123, 'peer_code': 'example'}
            save(path, expected)
            self.assertEqual(read_control(path), expected)


if __name__ == '__main__':
    unittest.main()

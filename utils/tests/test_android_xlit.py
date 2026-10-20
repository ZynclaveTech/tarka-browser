"""A3: Indian-language rows in the Android address bar (spec §5). The model
and word lists are not in the APK: android/xlit/files.py splits the word
lists per language and pins every file's size and sha256 for the download.
These tests run offline."""
import hashlib
import json
import pathlib
import struct
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'android' / 'xlit'))
import files  # noqa: E402


def txlw_tags(path):
    data = pathlib.Path(path).read_bytes()
    assert data[:8] == b'TXLW\x01\x00\x00\x00'
    (length,) = struct.unpack('<I', data[8:12])
    return set(json.loads(data[12:12 + length]))


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        words = self.tmp / 'words'
        words.mkdir()
        (words / 'hi.tsv').write_text('नमस्ते\t5\nघर\t3\n', encoding='utf-8')
        (words / 'ta.tsv').write_text('வணக்கம்\t4\n', encoding='utf-8')
        (self.tmp / 'english.txt').write_text('the\nhello\n', encoding='utf-8')
        (self.tmp / 'model.bin').write_bytes(b'TXLM' + bytes(60))
        self.args = (words, self.tmp / 'english.txt', self.tmp / 'model.bin')

    def build(self, name='out'):
        out = self.tmp / name
        return out, files.build(*self.args, out)

    def test_one_file_per_language_each_with_english(self):
        out, _ = self.build()
        self.assertEqual(sorted(p.name for p in out.glob('xlit-words-*.bin')),
                         ['xlit-words-hi.bin', 'xlit-words-ta.bin'])
        self.assertEqual(txlw_tags(out / 'xlit-words-hi.bin'), {'hi', 'en'})
        self.assertEqual(txlw_tags(out / 'xlit-words-ta.bin'), {'ta', 'en'})
        self.assertEqual((out / 'xlit-model.bin').read_bytes(), self.args[2].read_bytes())

    def test_files_json_matches_bytes(self):
        out, table = self.build()
        self.assertEqual(json.loads((out / 'files.json').read_text()), table)
        self.assertEqual(set(table), {'xlit-model.bin', 'xlit-words-hi.bin', 'xlit-words-ta.bin'})
        for name, entry in table.items():
            data = (out / name).read_bytes()
            self.assertEqual(entry, {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})

    def test_header_lists_every_file_once(self):
        out, table = self.build()
        inc = self.tmp / 'xlit_files.inc'
        files.header(out / 'files.json', inc)
        text = inc.read_text()
        for name, entry in table.items():
            self.assertEqual(text.count(f'"{name}"'), 1)
            self.assertIn(f'{{"{name}", {entry["size"]}, "{entry["sha256"]}"}},', text)

    def test_build_is_deterministic(self):
        a, _ = self.build('a')
        b, _ = self.build('b')
        for p in a.iterdir():
            self.assertEqual(p.read_bytes(), (b / p.name).read_bytes(), p.name)

    def test_build_sh_runs_files_after_install_xlit(self):
        sh = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('android/xlit/files.py" build', sh)
        self.assertLess(sh.index('_install_xlit\n'), sh.index('android/xlit/files.py" build'))
        self.assertIn('third_party/indicxlit/android', sh)
        self.assertIn('chrome/browser/tark_xlit/xlit_files.inc', sh)
        self.assertIn("'android/xlit/files.py'", (ROOT / 'android' / 'prep_hash.py').read_text())


if __name__ == '__main__':
    unittest.main()

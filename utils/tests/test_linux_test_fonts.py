"""L2: linux/fetch_test_fonts.py puts Chromium's test fonts (a GCS dependency
the lite source tarball leaves out; the unit test programs need them) where
DEPS pins them, checked against DEPS' sha256."""
import hashlib
import io
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'linux' / 'fetch_test_fonts.py'


def archive():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        data = b'font'
        info = tarfile.TarInfo('./Ahem.ttf')
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


DEPS = """deps = {{
  'src/third_party/test_fonts/test_fonts': {{
      'dep_type': 'gcs',
      'bucket': 'chromium-fonts',
      'objects': [
          {{
              'object_name': 'abc123',
              'sha256sum': '{sha}',
              'size_bytes': 1,
          }},
      ],
  }},
}}
"""


class TestFetchTestFonts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.src = root / 'src'
        self.src.mkdir()
        self.store = root / 'store' / 'chromium-fonts'
        self.store.mkdir(parents=True)
        self.data = archive()
        (self.store / 'abc123').write_bytes(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, sha):
        (self.src / 'DEPS').write_text(DEPS.format(sha=sha))
        env = dict(os.environ, TARK_GCS_BASE=(self.store.parent).as_uri())
        return subprocess.run([sys.executable, str(SCRIPT), str(self.src)], capture_output=True, text=True, env=env)

    def test_unpacks_where_deps_says(self):
        r = self.run_it(hashlib.sha256(self.data).hexdigest())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.src / 'third_party/test_fonts/test_fonts/Ahem.ttf').read_bytes(), b'font')

    def test_refuses_another_archive(self):
        r = self.run_it('0' * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.src / 'third_party/test_fonts/test_fonts/Ahem.ttf').exists())

    def test_nothing_to_do_when_there(self):
        fonts = self.src / 'third_party/test_fonts/test_fonts'
        fonts.mkdir(parents=True)
        (fonts / 'Ahem.ttf').write_bytes(b'already')
        r = self.run_it('0' * 64)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((fonts / 'Ahem.ttf').read_bytes(), b'already')


if __name__ == '__main__':
    unittest.main()

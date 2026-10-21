"""A5: Tark for Android's release identity (android/release/version.py):
version name <chromium>-r<revision>, version code BUILD*100000 + PATCH*100 +
revision, so a later Chromium is always higher and Tark's own revisions of
one Chromium count up within it."""
import json
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'android' / 'release'))
import version  # noqa: E402


class TestVersion(unittest.TestCase):
    def test_version_code_and_name(self):
        self.assertEqual(version.version_code('155.0.8059.39', 1), 805903901)
        self.assertEqual(version.version_name('155.0.8059.39', 1), '155.0.8059.39-r1')
        for bad in (0, 100):
            with self.assertRaises(ValueError):
                version.version_code('155.0.8059.39', bad)

    def test_later_chromium_always_higher(self):
        self.assertGreater(version.version_code('155.0.8060.1', 1),
                           version.version_code('155.0.8059.99', 99))

    def test_patch_numbers_fit(self):
        with self.assertRaises(ValueError):
            version.version_code('155.0.8059.1000', 1)

    def test_command_line_reads_the_repo(self):
        out = subprocess.run([sys.executable, str(REPO / 'android' / 'release' / 'version.py'), str(REPO)],
                             capture_output=True, text=True, check=True).stdout.split()
        chromium = (REPO / 'ungoogled-chromium' / 'chromium_version.txt').read_text().strip()
        revision = json.loads((REPO / 'android' / 'release.json').read_text())['revision']
        self.assertEqual(out, [version.version_name(chromium, revision),
                               str(version.version_code(chromium, revision))])

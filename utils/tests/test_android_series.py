"""A1: android/series.py writes Tark's Android patch series (Tark's patches
from patches/series minus android/desktop-only-patches.txt), and the Android
build config pins the spec's values."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ANDROID = REPO / 'android'
sys.path.insert(0, str(ANDROID))


def lines(path):
    return [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class TestAndroidSeries(unittest.TestCase):
    def setUp(self):
        import series  # noqa: E402  (android/series.py)
        self.series = series.series(REPO)
        self.tark = [e for e in lines(REPO / 'patches' / 'series') if e.startswith('tarka/')]
        self.skip = set(lines(ANDROID / 'desktop-only-patches.txt'))

    def test_only_tark_in_order(self):
        self.assertTrue(self.series)
        self.assertTrue(all(e.startswith('tarka/') for e in self.series))
        self.assertEqual(self.series, [e for e in self.tark if e not in self.skip])
        self.assertEqual(self.series[0], next(e for e in self.tark if e not in self.skip))

    def test_skip_list_entries_exist(self):
        self.assertTrue(self.skip)
        for entry in self.skip:
            self.assertIn(entry, self.tark, entry)

    def test_sparkle_skipped(self):
        self.assertNotIn('tarka/updater/sparkle.patch', self.series)

    def test_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / 'series'
            result = subprocess.run([sys.executable, str(ANDROID / 'series.py'), str(REPO), str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(lines(out), self.series)


class TestAndroidConfig(unittest.TestCase):
    def test_args_gn(self):
        args = (ANDROID / 'args.gn').read_text()
        for line in ('target_os = "android"', 'target_cpu = "arm64"',
                     'is_official_build = true', 'is_component_build = false',
                     'chrome_pgo_phase = 0', 'symbol_level = 0',
                     'chrome_public_manifest_package = "com.gettarka.tarka"'):
            self.assertIn(line, args)

    def test_gclient_template(self):
        text = (ANDROID / 'gclient.android').read_text()
        # gclient's standard layout: .gclient beside a solution named "src"
        # (depot_tools rejects an absolute solution name).
        self.assertIn('"name": "src"', text)
        self.assertNotIn('UC_OUT', text)
        self.assertIn("target_os = ['android']", text)
        self.assertIn('target_os_only = False', text)
        compile(text, 'gclient.android', 'exec')


if __name__ == '__main__':
    unittest.main()

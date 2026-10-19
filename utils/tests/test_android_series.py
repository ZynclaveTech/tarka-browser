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

    def test_tark_in_order_then_android_only(self):
        self.assertTrue(self.series)
        android = [e for e in self.series if e.startswith('android/')]
        tark = [e for e in self.series if not e.startswith('android/')]
        self.assertTrue(all(e.startswith('tarka/') for e in tark))
        self.assertEqual(tark, [e for e in self.tark if e not in self.skip])
        # Android-only patches (android/patches/series) come last.
        self.assertEqual(self.series[len(tark):], android)
        self.assertEqual(android, ['android/' + e for e in lines(ANDROID / 'patches' / 'series')])
        for e in android:
            self.assertTrue((ANDROID / 'patches' / e[len('android/'):]).is_file(), e)

    def test_locales_fix_is_android_only(self):
        self.assertIn('android/locales-android-branch.patch', self.series)
        self.assertNotIn('android/locales-android-branch.patch',
                         (REPO / 'patches' / 'series').read_text())

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
                     'chrome_public_manifest_package = "com.gettarka.tarka"',
                     'use_sysroot = false', 'use_clang_modules = false'):
            self.assertIn(line, args)

    def test_gclient_template(self):
        text = (ANDROID / 'gclient.android').read_text()
        # gclient's standard layout: .gclient beside a solution named "src"
        # (depot_tools rejects an absolute solution name).
        self.assertIn('"name": "src"', text)
        self.assertNotIn('UC_OUT', text)
        self.assertIn("target_os = ['android']", text)
        self.assertIn('target_os_only = False', text)
        # DEPS gates the Android SDK on 'checkout_android and non_git_source'.
        self.assertIn('"non_git_source": "True"', text)
        compile(text, 'gclient.android', 'exec')


if __name__ == '__main__':
    unittest.main()

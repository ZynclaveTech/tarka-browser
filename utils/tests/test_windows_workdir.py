"""W1: windows/prepare_workdir.py assembles the folder upstream's Windows
build.py runs in: upstream's files, the shared ungoogled-chromium core, and
Tark's patches (minus the Mac-only ones) after the Windows platform ones."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'windows' / 'prepare_workdir.py'


def lines(path):
    return [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class TestWindowsWorkdir(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = pathlib.Path(cls.tmp.name) / 'tw'
        cls.result = subprocess.run([sys.executable, str(SCRIPT), str(REPO), str(cls.work)],
                                    capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_runs(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_upstream_files_and_hook(self):
        for name in ('build.py', 'package.py', 'flags.windows.gn', 'downloads.ini',
                     'tark_post_patch.py', 'tark_repo.txt'):
            self.assertTrue((self.work / name).is_file(), name)
        self.assertIn('tark_post_patch.py', (self.work / 'build.py').read_text())
        self.assertEqual((self.work / 'tark_repo.txt').read_text().strip(), str(REPO))

    def test_core_is_the_shared_submodule(self):
        self.assertTrue((self.work / 'ungoogled-chromium' / 'patches' / 'series').is_file())
        self.assertFalse((self.work / 'ungoogled-chromium' / '.git').exists())

    def test_series_is_windows_then_tark_without_mac_only(self):
        series = lines(self.work / 'patches' / 'series')
        upstream = lines(REPO / 'windows' / 'upstream' / 'patches' / 'series')
        tark = [l for l in lines(REPO / 'patches' / 'series') if l.startswith('tarka/')]
        mac_only = lines(REPO / 'windows' / 'mac-only-patches.txt')
        self.assertEqual(series[:len(upstream)], upstream)
        self.assertEqual(series[len(upstream):], [l for l in tark if l not in mac_only])
        self.assertIn('tarka/updater/sparkle.patch', mac_only)
        for entry in series:
            self.assertTrue((self.work / 'patches' / entry).is_file(), entry)

    def test_domain_list_skips_tarks_exceptions(self):
        skip = lines(REPO / 'utils' / 'domain_substitution_skip.txt')
        listed = set(lines(self.work / 'ungoogled-chromium' / 'domain_substitution.list'))
        self.assertTrue(skip)
        self.assertFalse(listed & set(skip))
        self.assertEqual((self.work / 'domain_substitution.list').read_text(),
                         (self.work / 'ungoogled-chromium' / 'domain_substitution.list').read_text())

    def test_rerun_keeps_build_dir(self):
        marker = self.work / 'build' / 'keep.txt'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('x')
        again = subprocess.run([sys.executable, str(SCRIPT), str(REPO), str(self.work)],
                               capture_output=True, text=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertTrue(marker.is_file())


if __name__ == '__main__':
    unittest.main()

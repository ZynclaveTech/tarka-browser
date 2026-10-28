"""L1: linux/prepare_workdir.py assembles the folder upstream's Linux
scripts/build.sh runs in: upstream's files, the shared ungoogled-chromium
core, and Tark's patches (minus the Mac-only ones) after the portablelinux
ones."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'linux' / 'prepare_workdir.py'


def lines(path):
    return [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class TestLinuxWorkdir(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = pathlib.Path(cls.tmp.name) / 'tl'
        cls.result = subprocess.run([sys.executable, str(SCRIPT), str(REPO), str(cls.work)],
                                    capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_runs(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_upstream_files_and_hook(self):
        for name in ('scripts/build.sh', 'scripts/shared.sh', 'scripts/package.sh',
                     'docker/build.Dockerfile', 'flags.linux.gn', 'LICENSE',
                     'tark_post_patch.py', 'tark_repo.txt'):
            self.assertTrue((self.work / name).is_file(), name)
        self.assertIn('tark_post_patch.py', (self.work / 'scripts' / 'build.sh').read_text())
        self.assertEqual((self.work / 'tark_repo.txt').read_text().strip(), str(REPO))

    def test_onnxruntime_runs_on_every_build(self):
        # A tree kept from before Tark's steps installed ONNX Runtime skips
        # those steps (.tark.stamp); its headers must still arrive.
        text = (self.work / 'scripts' / 'build.sh').read_text()
        self.assertIn('tark_post_patch.py" --onnxruntime-only', text)
        self.assertGreater(text.index('--onnxruntime-only'), text.index('.tark.stamp'))

    def test_tarks_gn_args_follow_upstreams(self):
        flags = lines(self.work / 'flags.linux.gn')
        upstream = lines(REPO / 'linux' / 'upstream' / 'flags.linux.gn')
        self.assertEqual(flags, upstream + lines(REPO / 'linux' / 'args.gn'))

    def test_core_is_the_shared_submodule(self):
        self.assertTrue((self.work / 'ungoogled-chromium' / 'patches' / 'series').is_file())
        self.assertFalse((self.work / 'ungoogled-chromium' / '.git').exists())

    def test_series_is_linux_then_tark_without_mac_only(self):
        series = lines(self.work / 'patches' / 'series')
        upstream = lines(REPO / 'linux' / 'upstream' / 'patches' / 'series')
        tark = [l for l in lines(REPO / 'patches' / 'series') if l.startswith('tarka/')]
        mac_only = lines(REPO / 'linux' / 'mac-only-patches.txt')
        self.assertEqual(series[:len(upstream)], upstream)
        self.assertEqual(series[len(upstream):], [l for l in tark if l not in mac_only])
        self.assertIn('tarka/updater/sparkle.patch', mac_only)
        self.assertFalse([l for l in series if '/macos/' in l or '/windows/' in l and not l.startswith('tarka/')])
        for entry in series:
            self.assertTrue((self.work / 'patches' / entry).is_file(), entry)

    def test_domain_list_skips_tarks_exceptions(self):
        skip = lines(REPO / 'utils' / 'domain_substitution_skip.txt')
        listed = set(lines(self.work / 'ungoogled-chromium' / 'domain_substitution.list'))
        self.assertTrue(skip)
        self.assertFalse(listed & set(skip))

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

"""L1: linux/package_tarball.sh makes Tark-<chromium>-<revision>-x64-linux.tar.xz
from the build's out/Default, with one top folder of the same name, a
`tark` launcher, and a .sha256 that sha256sum -c accepts."""
import hashlib
import os
import pathlib
import subprocess
import tarfile
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'linux' / 'package_tarball.sh'
FILES = ['chrome', 'chrome_100_percent.pak', 'chrome_200_percent.pak', 'chrome_crashpad_handler',
         'chrome-wrapper', 'icudtl.dat', 'libEGL.so', 'libGLESv2.so', 'libqt5_shim.so',
         'libqt6_shim.so', 'libvk_swiftshader.so', 'libvulkan.so.1', 'product_logo_48.png',
         'resources.pak', 'v8_context_snapshot.bin', 'vk_swiftshader_icd.json', 'xdg-mime',
         'xdg-settings', 'locales/en-US.pak', 'indicxlit/xlit-model.bin', 'indicxlit/xlit-words.bin',
         'libonnxruntime.so.1', 'tark_adblock/lists.zip']


class TestLinuxPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.outdir = root / 'Default'
        for f in FILES:
            (self.outdir / f).parent.mkdir(parents=True, exist_ok=True)
            (self.outdir / f).write_text(f)
        (self.outdir / 'chromedriver').write_text('not shipped')
        self.dest = root / 'out'
        self.r = subprocess.run(['bash', str(SCRIPT), str(REPO), str(self.outdir), str(self.dest)],
                                capture_output=True, text=True)
        chromium = (REPO / 'ungoogled-chromium' / 'chromium_version.txt').read_text().strip()
        revision = (REPO / 'revision.txt').read_text().strip()
        self.stem = f'Tark-{chromium}-{revision}-x64-linux'

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)

    def test_tarball_has_one_top_folder_with_the_files_and_a_launcher(self):
        with tarfile.open(self.dest / f'{self.stem}.tar.xz') as t:
            names = t.getnames()
            self.assertTrue(all(n == self.stem or n.startswith(self.stem + '/') for n in names))
            for f in FILES + ['tark']:
                self.assertIn(f'{self.stem}/{f}', names)
            self.assertNotIn(f'{self.stem}/chromedriver', names)
            launcher = t.getmember(f'{self.stem}/tark')
            self.assertTrue(launcher.mode & 0o111)

    def test_sha256_matches(self):
        line = (self.dest / f'{self.stem}.tar.xz.sha256').read_text().split()
        data = (self.dest / f'{self.stem}.tar.xz').read_bytes()
        self.assertEqual(line, [hashlib.sha256(data).hexdigest(), f'{self.stem}.tar.xz'])


class TestLinuxPackageOptional(unittest.TestCase):
    """xdg-mime and xdg-settings (the default-browser helpers) are packed when
    the build has them; anything else missing stops the package."""
    def make(self, skip):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = pathlib.Path(tmp.name) / 'Default'
        for f in FILES:
            if f in skip:
                continue
            (out / f).parent.mkdir(parents=True, exist_ok=True)
            (out / f).write_text(f)
        return subprocess.run(['bash', str(SCRIPT), str(REPO), str(out), str(pathlib.Path(tmp.name) / 'o')],
                              capture_output=True, text=True)

    def test_without_the_xdg_helpers(self):
        r = self.make({'xdg-mime', 'xdg-settings'})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_without_chrome_fails(self):
        self.assertNotEqual(self.make({'chrome'}).returncode, 0)


if __name__ == '__main__':
    unittest.main()

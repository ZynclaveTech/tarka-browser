"""L3: linux/package_deb.sh makes tark_<chromium>-<revision>_amd64.deb from
the tarball's folder: Tark in /opt/tark, a tark command, the app menu entry
and icons, the AppArmor profile Ubuntu 23.10+ needs for Chromium's sandbox,
and maintainer scripts that are safe to run twice."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'linux' / 'package_deb.sh'
HAVE_DPKG = shutil.which('dpkg-deb') is not None


@unittest.skipUnless(HAVE_DPKG, 'needs dpkg-deb')
class TestLinuxDeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.tmp.name)
        chromium = (REPO / 'ungoogled-chromium' / 'chromium_version.txt').read_text().strip()
        revision = (REPO / 'revision.txt').read_text().strip()
        cls.version = f'{chromium}-{revision}'
        app = root / f'Tark-{cls.version}-x64-linux'
        app.mkdir()
        for f in ('chrome', 'tark', 'libonnxruntime.so.1', 'resources.pak'):
            (app / f).write_text(f)
        (app / 'tark').chmod(0o755)
        src = root / 'src'
        logos = src / 'chrome' / 'app' / 'theme' / 'chromium'
        logos.mkdir(parents=True)
        for size in (16, 24, 48, 64, 128, 256):
            (logos / f'product_logo_{size}.png').write_bytes(b'png%d' % size)
        cls.dest = root / 'out'
        cls.r = subprocess.run(['bash', str(SCRIPT), str(REPO), str(app), str(src), str(cls.dest)],
                               capture_output=True, text=True, env=dict(os.environ, TARK_DEB_DEPENDS='libc6'))
        cls.deb = cls.dest / f'tark_{cls.version}_amd64.deb'

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def field(self, name):
        return subprocess.run(['dpkg-deb', '-f', str(self.deb), name],
                              capture_output=True, text=True).stdout.strip()

    def test_builds(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        self.assertTrue(self.deb.is_file())

    def test_control(self):
        self.assertEqual(self.field('Package'), 'tark')
        self.assertEqual(self.field('Version'), self.version)
        self.assertEqual(self.field('Architecture'), 'amd64')
        self.assertIn('libc6', self.field('Depends'))
        self.assertIn('xdg-utils', self.field('Depends'))

    def test_contents(self):
        listing = subprocess.run(['dpkg-deb', '-c', str(self.deb)], capture_output=True, text=True).stdout
        for path in ('./opt/tark/chrome', './opt/tark/tark', './opt/tark/libonnxruntime.so.1',
                     './usr/share/applications/tark.desktop',
                     './usr/share/icons/hicolor/256x256/apps/tark.png',
                     './usr/share/icons/hicolor/16x16/apps/tark.png',
                     './etc/apparmor.d/tark',
                     './opt/tark/tark-archive-keyring.gpg'):
            self.assertIn(path, listing)
        self.assertRegex(listing, r'\./usr/bin/tark -> /opt/tark/tark')

    def test_desktop_entry_is_tarks(self):
        out = pathlib.Path(self.tmp.name) / 'x'
        subprocess.run(['dpkg-deb', '-x', str(self.deb), str(out)], check=True)
        desktop = (out / 'usr/share/applications/tark.desktop').read_text()
        self.assertIn('Name=Tark\n', desktop)
        self.assertIn('Exec=/usr/bin/tark %U', desktop)
        self.assertIn('Icon=tark', desktop)
        self.assertIn('x-scheme-handler/https', desktop)
        apparmor = (out / 'etc/apparmor.d/tark').read_text()
        self.assertIn('/opt/tark/chrome', apparmor)
        self.assertIn('userns,', apparmor)

    def test_carries_tarks_package_key(self):
        out = pathlib.Path(self.tmp.name) / 'k'
        subprocess.run(['dpkg-deb', '-x', str(self.deb), str(out)], check=True)
        self.assertEqual((out / 'opt/tark/tark-archive-keyring.gpg').read_bytes(),
                         (REPO / 'linux/deb/tark-archive-keyring.gpg').read_bytes())

    def test_launcher_names_the_desktop_entry(self):
        out = pathlib.Path(self.tmp.name) / 'y'
        subprocess.run(['dpkg-deb', '-x', str(self.deb), str(out)], check=True)
        self.assertIn('CHROME_DESKTOP=tark.desktop', (out / 'opt/tark/tark').read_text())

    def test_postinst_twice_writes_one_apt_source(self):
        ctl = pathlib.Path(self.tmp.name) / 'ctl'
        subprocess.run(['dpkg-deb', '-e', str(self.deb), str(ctl)], check=True)
        root = pathlib.Path(self.tmp.name) / 'root'
        (root / 'opt/tark').mkdir(parents=True)
        (root / 'opt/tark/tark-archive-keyring.gpg').write_bytes(b'key')
        env = dict(os.environ, DPKG_ROOT=str(root), PATH='/usr/bin:/bin')
        for _ in range(2):
            r = subprocess.run(['sh', str(ctl / 'postinst'), 'configure'], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        source = (root / 'etc/apt/sources.list.d/tark.list').read_text()
        self.assertEqual(source.count('deb '), 1)
        self.assertIn('signed-by=/usr/share/keyrings/tark-archive-keyring.gpg]', source)
        self.assertIn('https://gettarka.com/apt stable main', source)
        self.assertEqual((root / 'usr/share/keyrings/tark-archive-keyring.gpg').read_bytes(), b'key')

    def test_postinst_without_a_key_adds_no_source(self):
        ctl = pathlib.Path(self.tmp.name) / 'ctl2'
        subprocess.run(['dpkg-deb', '-e', str(self.deb), str(ctl)], check=True)
        root = pathlib.Path(self.tmp.name) / 'root2'
        (root / 'opt/tark').mkdir(parents=True)
        env = dict(os.environ, DPKG_ROOT=str(root), PATH='/usr/bin:/bin')
        r = subprocess.run(['sh', str(ctl / 'postinst'), 'configure'], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((root / 'etc/apt/sources.list.d/tark.list').exists())


if __name__ == '__main__':
    unittest.main()

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


SDK = pathlib.Path.home() / 'Library' / 'Android' / 'sdk'
BUILD_TOOLS = sorted((SDK / 'build-tools').glob('*'))[-1] if (SDK / 'build-tools').exists() else None
PLATFORM = sorted((SDK / 'platforms').glob('android-*'))[-1] if (SDK / 'platforms').exists() else None


def tools_missing():
    import shutil
    if not (BUILD_TOOLS and PLATFORM and shutil.which('keytool') and shutil.which('jarsigner')):
        return 'needs the Android SDK (aapt2, apksigner) and a JDK (keytool, jarsigner)'
    return None


@unittest.skipIf(tools_missing(), tools_missing() or '')
class TestSigning(unittest.TestCase):
    """A5 Task 2: the release key is made and used on the Mac only; the
    build machine's APK and bundle (signed with Chromium's debug key) are
    signed again with it."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        sys.path.insert(0, str(REPO / 'android' / 'release'))
        import sign
        cls.sign = sign
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        cls.home = cls.tmp / 'home'
        cls.home.mkdir()
        cls.keygen = subprocess.run(['bash', str(REPO / 'android' / 'release' / 'keygen.sh'), 'Test Org'],
                                    capture_output=True, text=True, env={**__import__('os').environ, 'HOME': str(cls.home)})
        cls.keystore = cls.home / '.config' / 'tark' / 'android-release.p12'
        cls.passfile = cls.home / '.config' / 'tark' / 'android-release.pass'
        # A second key stands in for Chromium's debug key.
        cls.old = cls.tmp / 'old.p12'
        subprocess.run(['keytool', '-genkeypair', '-keyalg', 'RSA', '-keysize', '2048', '-alias', 'old',
                        '-storetype', 'PKCS12', '-keystore', str(cls.old), '-storepass', 'oldpass',
                        '-dname', 'CN=Old', '-validity', '1'], check=True, capture_output=True)
        cls.apk, cls.aab = cls.fixtures(805903901)

    @classmethod
    def fixtures(cls, code, name='155.0.8059.39-r1', tag=''):
        """An APK and an app bundle with this version, both signed with the
        old key, as the build machine's are."""
        import zipfile
        d = cls.tmp / f'fx{code}{tag}'
        d.mkdir()
        (d / 'AndroidManifest.xml').write_text(
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.gettarka.tarka" '
            f'android:versionCode="{code}" android:versionName="{name}"><application/></manifest>')
        aapt2 = str(BUILD_TOOLS / 'aapt2')
        jar = str(PLATFORM / 'android.jar')
        subprocess.run([aapt2, 'link', '-o', str(d / 'u.apk'), '--manifest', str(d / 'AndroidManifest.xml'),
                        '-I', jar], check=True)
        subprocess.run([str(BUILD_TOOLS / 'apksigner'), 'sign', '--ks', str(cls.old), '--ks-pass', 'pass:oldpass',
                        '--out', str(d / 'ChromePublic.apk'), str(d / 'u.apk')], check=True)
        subprocess.run([aapt2, 'link', '--proto-format', '-o', str(d / 'p.apk'), '--manifest',
                        str(d / 'AndroidManifest.xml'), '-I', jar], check=True)
        with zipfile.ZipFile(d / 'p.apk') as p, zipfile.ZipFile(d / 'ChromePublic.aab', 'w') as b:
            b.writestr('BundleConfig.pb', b'')
            b.writestr('base/manifest/AndroidManifest.xml', p.read('AndroidManifest.xml'))
            b.writestr('base/resources.pb', p.read('resources.pb'))
        subprocess.run(['jarsigner', '-keystore', str(cls.old), '-storepass', 'oldpass',
                        str(d / 'ChromePublic.aab'), 'old'], check=True, capture_output=True)
        return d / 'ChromePublic.apk', d / 'ChromePublic.aab'

    def fingerprint(self):
        out = subprocess.run(['keytool', '-list', '-v', '-keystore', str(self.keystore),
                              '-storepass:file', str(self.passfile)], capture_output=True, text=True,
                             check=True).stdout
        return next(l.split(':', 1)[1].strip() for l in out.splitlines()
                    if l.strip().startswith('SHA256:')).replace(':', '').lower()

    def test_keygen_makes_a_private_key_and_prints_only_its_fingerprint(self):
        self.assertEqual(self.keygen.returncode, 0, self.keygen.stderr)
        for f in (self.keystore, self.passfile):
            self.assertEqual(f.stat().st_mode & 0o777, 0o600, f)
        self.assertIn(self.fingerprint().upper()[:16], self.keygen.stdout.replace(':', '').upper())
        self.assertNotIn(self.passfile.read_text().strip(), self.keygen.stdout + self.keygen.stderr)

    def test_keygen_refuses_to_overwrite(self):
        again = subprocess.run(['bash', str(REPO / 'android' / 'release' / 'keygen.sh'), 'Test Org'],
                               capture_output=True, text=True,
                               env={**__import__('os').environ, 'HOME': str(self.home)})
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('exists', again.stderr)

    def test_sign_apk_with_own_key(self):
        out = self.tmp / 'signed.apk'
        cert = self.sign.sign_apk(self.apk, out, self.keystore, self.passfile)
        self.assertEqual(cert, self.fingerprint())
        listed = subprocess.run([str(BUILD_TOOLS / 'apksigner'), 'verify', '--print-certs', str(out)],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(listed.count('certificate SHA-256 digest'), 1)

    def test_sign_aab_replaces_the_old_signature(self):
        out = self.tmp / 'signed.aab'
        cert = self.sign.sign_aab(self.aab, out, self.keystore, self.passfile)
        self.assertEqual(cert, self.fingerprint())
        import zipfile
        names = zipfile.ZipFile(out).namelist()
        self.assertFalse([n for n in names if n.upper().startswith('META-INF/OLD.')], names)
        self.assertTrue([n for n in names if n.upper().startswith('META-INF/TARK.')], names)

    def test_release_names_both_files_and_returns_the_hashes(self):
        outdir = self.tmp / 'release'
        result = self.sign.release(self.apk, self.aab, outdir, self.keystore, self.passfile)
        self.assertEqual(sorted(p.name for p in outdir.iterdir()),
                         ['tark-155.0.8059.39-r1.aab', 'tark-155.0.8059.39-r1.apk'])
        import hashlib
        self.assertEqual(result['apk_sha256'],
                         hashlib.sha256((outdir / 'tark-155.0.8059.39-r1.apk').read_bytes()).hexdigest())
        self.assertEqual(result['cert_sha256'], self.fingerprint())
        self.assertEqual((result['version_name'], result['version_code']), ('155.0.8059.39-r1', 805903901))

    def test_mismatched_versions_refused(self):
        _, other_aab = self.fixtures(805903902, '155.0.8059.39-r2', tag='b')
        with self.assertRaisesRegex(ValueError, 'version'):
            self.sign.release(self.apk, other_aab, self.tmp / 'mismatch', self.keystore, self.passfile)

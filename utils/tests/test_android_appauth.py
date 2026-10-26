"""Sign in with Zynclave: AppAuth for Android's sources, placed into
third_party/appauth/src by android/appauth/fetch.py (the archive checked
against a pinned sha256), built by android/patches/appauth-library.patch."""
import hashlib
import io
import pathlib
import re
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'android' / 'appauth'))
import fetch  # noqa: E402

PATCHES = ROOT / 'android' / 'patches'
P = fetch.PREFIX


def fake_archive(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(path)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestPlace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = pathlib.Path(self.tmp.name) / 'src'
        self.src.mkdir()
        self.data = fake_archive({
            P + 'LICENSE': 'Apache\n',
            P + 'library/java/net/openid/appauth/AuthState.java': 'class AuthState {}\n',
            P + 'library/java/net/openid/appauth/browser/Browsers.java': 'class Browsers {}\n',
            P + 'library/AndroidManifest.xml': '<manifest/>\n',
            P + 'library/res/values/styles.xml': '<resources/>\n',
            P + 'app/java/net/openid/appauthdemo/LoginActivity.java': 'class LoginActivity {}\n',
            P + 'library/javatests/net/openid/appauth/AuthStateTest.java': 'class T {}\n',
            'elsewhere/LICENSE': 'no\n',
        })
        self.pinned = fetch.SHA256
        fetch.SHA256 = hashlib.sha256(self.data).hexdigest()

    def tearDown(self):
        fetch.SHA256 = self.pinned
        self.tmp.cleanup()

    def placed(self):
        dest = self.src / 'third_party/appauth/src'
        return sorted(str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file())

    def test_only_the_library_sources_and_licence(self):
        self.assertEqual(fetch.place(self.src, self.data), 3)
        self.assertEqual(self.placed(), [
            'LICENSE',
            'library/java/net/openid/appauth/AuthState.java',
            'library/java/net/openid/appauth/browser/Browsers.java',
        ])

    def test_replaces_an_earlier_copy(self):
        stale = self.src / 'third_party/appauth/src/library/java/net/openid/appauth/Old.java'
        stale.parent.mkdir(parents=True)
        stale.write_text('old\n')
        fetch.place(self.src, self.data)
        self.assertNotIn('library/java/net/openid/appauth/Old.java', self.placed())

    def test_refuses_a_tampered_archive_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            fetch.place(self.src, self.data + b'x')
        self.assertFalse((self.src / 'third_party/appauth/src').exists())

    def test_main_fails_on_a_tampered_cache(self):
        cache = pathlib.Path(self.tmp.name) / 'cache'
        cache.mkdir()
        (cache / f'AppAuth-Android-{fetch.VERSION}.tar.gz').write_bytes(self.data + b'x')
        self.assertEqual(fetch.main([str(self.src), '--cache', str(cache)]), 1)


class TestPinned(unittest.TestCase):
    def test_the_release(self):
        self.assertEqual(fetch.VERSION, '0.11.1')
        self.assertRegex(fetch.SHA256, r'^[0-9a-f]{64}$')
        self.assertTrue(fetch.URL.startswith('https://github.com/openid/AppAuth-Android/'))


class TestWiring(unittest.TestCase):
    def test_in_the_series_after_voice(self):
        series = [l for l in (PATCHES / 'series').read_text().split() if l.endswith('.patch')]
        i = series.index('appauth-library.patch')
        self.assertEqual(series[i - 1], 'voice-language-detect.patch')
        self.assertEqual(series[i + 1], 'zynclave-account.patch')

    def test_build_sh_fetches_beside_the_crates(self):
        sh = (ROOT / 'android' / 'build.sh').read_text()
        prep = sh[:sh.index('# --- end prepare ---')]
        self.assertIn('android/appauth/fetch.py" "$_src_dir" --cache "$_download_cache/appauth"', prep)
        self.assertLess(prep.index('adblock/crates.py'), prep.index('appauth/fetch.py'))

    def test_build_gn_names_every_fetched_source(self):
        text = (PATCHES / 'appauth-library.patch').read_text()
        names = set(re.findall(r'^\+\s+"src/(library/java/net/openid/appauth/\S+\.java)",', text, re.M))
        self.assertGreaterEqual(len(names), 50)
        self.assertIn('library/java/net/openid/appauth/RedirectUriReceiverActivity.java', names)
        self.assertIn('chromium_code = false', text)
        self.assertIn('License: Apache-2.0', text)
        self.assertIn('Shipped: yes', text)


if __name__ == '__main__':
    unittest.main()

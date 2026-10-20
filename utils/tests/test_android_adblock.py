"""A2: adblock-rust in Tark for Android (spec §4). Task 3: the adblock crate
and its new dependencies, placed into Chromium's vendored crates by
android/adblock/crates.py (each .crate checked against a pinned sha256) and
wired up by android/patches/adblock-crates.patch."""
import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'android' / 'adblock'))
import crates  # noqa: E402

PATCHES = ROOT / 'android' / 'patches'


def patch_text(name):
    return (PATCHES / name).read_text()


def added(text):
    return '\n'.join(l[1:] for l in text.splitlines() if l.startswith('+') and not l.startswith('+++'))


class TestCrateList(unittest.TestCase):
    def test_the_new_crates(self):
        self.assertEqual(sorted(n for n, _, _ in crates.CRATES), sorted([
            'adblock', 'arrayvec', 'flatbuffers', 'idna', 'idna_adapter', 'percent-encoding',
            'precomputed-hash', 'rustc-hash', 'rustc_version', 'seahash', 'semver']))
        for n, v, sha in crates.CRATES:
            self.assertRegex(sha, r'^[0-9a-f]{64}$', n)
        self.assertIn(('adblock', '0.13.3'), [(n, v) for n, v, _ in crates.CRATES])

    def test_epochs(self):
        self.assertEqual(crates.epoch('0.13.3'), 'v0_13')
        self.assertEqual(crates.epoch('25.12.19'), 'v25')
        self.assertEqual(crates.epoch('1.1.0'), 'v1')
        self.assertEqual(crates.epoch('0.0.18'), 'v0_0_18')


def fake_crate(name, version, files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f'{name}-{version}/{path}')
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestPlace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = pathlib.Path(self.tmp.name) / 'src'
        self.cio = self.src / 'third_party/rust/chromium_crates_io'
        (self.cio / 'vendor').mkdir(parents=True)
        self.data = fake_crate('demo', '0.2.1', {'Cargo.toml': '[package]\nname = "demo"\n',
                                                  'src/lib.rs': 'pub fn f() {}\n'})
        self.sha = hashlib.sha256(self.data).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_places_a_checked_crate(self):
        crates.place(self.src, 'demo', '0.2.1', self.sha, self.data)
        d = self.cio / 'vendor' / 'demo-v0_2'
        self.assertEqual((d / 'src/lib.rs').read_text(), 'pub fn f() {}\n')
        self.assertEqual(json.loads((d / '.cargo-checksum.json').read_text()), {'files': {}})

    def test_refuses_a_crate_with_the_wrong_sha256(self):
        with self.assertRaises(ValueError):
            crates.place(self.src, 'demo', '0.2.1', '0' * 64, self.data)
        self.assertFalse((self.cio / 'vendor' / 'demo-v0_2').exists())

    def test_applies_the_crate_patches(self):
        pdir = self.cio / 'patches' / 'demo-v0_2'
        pdir.mkdir(parents=True)
        p = 'third_party/rust/chromium_crates_io/vendor/demo-v0_2/LICENSE'
        (pdir / '0001-licence.diff').write_text(
            f'diff --git a/{p} b/{p}\nnew file mode 100644\n--- /dev/null\n+++ b/{p}\n@@ -0,0 +1 @@\n+MIT\n')
        crates.place(self.src, 'demo', '0.2.1', self.sha, self.data)
        self.assertEqual((self.cio / 'vendor/demo-v0_2/LICENSE').read_text(), 'MIT\n')


class TestCratesPatch(unittest.TestCase):
    def setUp(self):
        self.p = patch_text('adblock-crates.patch')
        self.add = added(self.p)

    def test_in_the_series(self):
        self.assertIn('adblock-crates.patch', (PATCHES / 'series').read_text().split())

    def test_adblock_pinned_with_only_its_two_features(self):
        self.assertIn('adblock = { version = "=0.13.3", default-features = false, '
                      'features = ["full-regex-handling", "single-thread"] }', self.add)
        self.assertNotIn('embedded-domain-resolver', self.add)
        self.assertNotIn('css-validation', self.add)

    def test_regex_becomes_shippable(self):
        # Chromium ships regex as test-only; adblock-rust needs it in the browser.
        self.assertRegex(self.p, r"-group = 'test'")
        self.assertIn('-  testonly = true', self.p)

    def test_build_files_for_every_new_crate(self):
        for n, v, _ in crates.CRATES:
            d = n.replace('-', '_')
            self.assertIn(f'+++ b/third_party/rust/{d}/{crates.epoch(v)}/BUILD.gn', self.p, n)

    def test_crate_patches_recorded(self):
        self.assertIn('patches/adblock-v0_13/0001-Tark-thiserror-2-and-no-url.diff', self.p)
        self.assertIn('patches/seahash-v4/0001-Tark-add-licence.diff', self.p)


class TestBuildSh(unittest.TestCase):
    def test_crates_placed_after_substitution(self):
        s = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('android/adblock/crates.py', s)
        self.assertLess(s.index('domain_substitution.py" apply'), s.index('android/adblock/crates.py'))
        self.assertLess(s.index('android/adblock/crates.py'), s.index('# --- end prepare ---'))

    def test_prep_hash_covers_the_crates(self):
        h = (ROOT / 'android' / 'prep_hash.py').read_text()
        self.assertIn('android/adblock/crates.py', h)


if __name__ == '__main__':
    unittest.main()

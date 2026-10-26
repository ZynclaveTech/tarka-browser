"""Desktop ad blocker: utils/adblock_lists.py puts the newest signed desktop
list bundle into the tree before every Mac and Windows build, and refuses
anything whose signature does not check (the build stops)."""
import datetime
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'android' / 'adblock'))
sys.path.insert(0, str(REPO / 'utils'))
sys.path.insert(0, str(REPO / 'utils' / 'tests'))
import adblock_lists  # noqa: E402
import bundle  # noqa: E402
import ed25519  # noqa: E402
from test_android_adblock_bundle import RESOURCES, RFC_SECRET1, fixture_lists  # noqa: E402

SCRIPT = REPO / 'utils' / 'adblock_lists.py'


class TestAdblockLists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.lists = root / 'lists'
        self.lists.mkdir()
        self.name = 'lists-00432630.zip'
        self.data = self.publish(platform='desktop', age_days=1)
        self.pubkey = root / 'pub.txt'
        self.pubkey.write_text(ed25519.secret_to_public(RFC_SECRET1).hex())
        self.dest = root / 'src' / 'chrome' / 'browser' / 'tark_adblock' / 'lists.zip'

    def publish(self, platform, age_days):
        created = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=age_days))
        data = bundle.make_zip(fixture_lists(), RESOURCES, created.strftime('%Y-%m-%dT%H:%M:%SZ'), '1.75.0',
                               platform=platform)
        (self.lists / self.name).write_bytes(data)
        (self.lists / 'latest.json').write_text(json.dumps(bundle.make_index(data, self.name, RFC_SECRET1)))
        return data

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.dest), '--lists-dir', str(self.lists),
                               '--pubkey', str(self.pubkey)], capture_output=True, text=True)

    def test_a_signed_bundle_is_put_in_place(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dest.read_bytes(), self.data)

    def test_a_bad_signature_stops_the_build(self):
        tampered = bytearray(self.data)
        tampered[-30] ^= 1
        (self.lists / self.name).write_bytes(bytes(tampered))
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_a_missing_bundle_stops_the_build(self):
        (self.lists / self.name).unlink()
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_a_badly_named_bundle_is_refused(self):
        index = json.loads((self.lists / 'latest.json').read_text())
        index['file'] = '../evil.zip'
        (self.lists / 'latest.json').write_text(json.dumps(index))
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_an_android_bundle_is_refused(self):
        # Both bundles are signed with the same key: the platform is in the
        # signed manifest, so Android's cannot stand in for the desktop one.
        self.publish(platform='android', age_days=1)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('platform', r.stderr)
        self.assertFalse(self.dest.exists())

    def test_a_stale_bundle_is_refused(self):
        # An old signed bundle served again (a rollback) is refused.
        self.publish(platform='desktop', age_days=31)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_the_default_source_is_the_desktop_bundle(self):
        self.assertEqual(adblock_lists.LISTS_BASE, 'https://gettarka.com/lists/desktop/v1/')


if __name__ == '__main__':
    unittest.main()

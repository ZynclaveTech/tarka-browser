"""A2 Task 1: the adblock list bundle (android/adblock/bundle.py). Lists and
uBlock Origin's scriptlets and redirect resources are bundled as text in one
zip, signed with Ed25519; phones verify and compile it (spec §4). These tests
run offline."""
import hashlib
import io
import json
import pathlib
import sys
import unittest
import zipfile

ADBLOCK = pathlib.Path(__file__).resolve().parents[2] / 'android' / 'adblock'
sys.path.insert(0, str(ADBLOCK))
import bundle  # noqa: E402
import ed25519  # noqa: E402

# RFC 8032 §7.1, TEST 1 and TEST 2.
RFC_SECRET1 = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
RFC_PUBLIC1 = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
RFC_SIG1 = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155'
                         '5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
RFC_SECRET2 = bytes.fromhex('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb')
RFC_PUBLIC2 = bytes.fromhex('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c')
RFC_SIG2 = bytes.fromhex('92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
                         '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')


class TestEd25519(unittest.TestCase):
    def test_rfc8032_vectors(self):
        self.assertEqual(ed25519.secret_to_public(RFC_SECRET1), RFC_PUBLIC1)
        self.assertEqual(ed25519.sign(RFC_SECRET1, b''), RFC_SIG1)
        self.assertTrue(ed25519.verify(RFC_PUBLIC1, b'', RFC_SIG1))
        self.assertEqual(ed25519.sign(RFC_SECRET2, b'\x72'), RFC_SIG2)
        self.assertTrue(ed25519.verify(RFC_PUBLIC2, b'\x72', RFC_SIG2))

    def test_wrong_message_or_key_fails(self):
        self.assertFalse(ed25519.verify(RFC_PUBLIC2, b'\x73', RFC_SIG2))
        self.assertFalse(ed25519.verify(RFC_PUBLIC1, b'\x72', RFC_SIG2))


class TestPreprocess(unittest.TestCase):
    def pre(self, text, files=None):
        files = files or {}
        return bundle.preprocess(text, 'https://lists.example/filters/main.txt',
                                 lambda url: files[url])

    def test_mobile_and_chromium_blocks_kept(self):
        out = self.pre('a\n!#if env_mobile\nb\n!#endif\n!#if env_chromium && !env_firefox\nc\n!#endif\n')
        self.assertEqual(out.split(), ['a', 'b', 'c'])

    def test_other_platform_blocks_dropped(self):
        out = self.pre('a\n!#if env_firefox\nb\n!#else\nc\n!#endif\n!#if cap_html_filtering\nd\n!#endif\n')
        self.assertEqual(out.split(), ['a', 'c'])

    def test_nested_and_unknown_tokens(self):
        out = self.pre('!#if env_mobile\n!#if adguard_app_android\nx\n!#endif\ny\n!#endif\n!#if (env_safari || env_mobile)\nz\n!#endif\n')
        self.assertEqual(out.split(), ['y', 'z'])

    def test_same_origin_include_inlined(self):
        files = {'https://lists.example/filters/part.txt': 'p1\n!#if env_firefox\np2\n!#endif\n'}
        out = self.pre('a\n!#include part.txt\nb\n', files)
        self.assertEqual(out.split(), ['a', 'p1', 'b'])

    def test_cross_origin_include_refused(self):
        with self.assertRaises(ValueError):
            self.pre('!#include https://elsewhere.example/x.txt\n')


def fixture_lists():
    return [
        bundle.List('ublock-filters', 'https://u.example/filters.txt', 1, 'example.com##.ad\n'),
        bundle.List('easylist', 'https://e.example/easylist.txt', 0, '||ads.example^\n'),
    ]


RESOURCES = [{'name': 'noop.js', 'aliases': [], 'kind': {'mime': 'application/javascript'},
              'content': 'KGZ1bmN0aW9uKCkge30pKCk='}]


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.data = bundle.make_zip(fixture_lists(), RESOURCES, '2026-10-20T02:30:00Z', '1.75.0')

    def test_entries(self):
        names = zipfile.ZipFile(io.BytesIO(self.data)).namelist()
        self.assertEqual(sorted(names), ['lists/easylist.txt', 'lists/ublock-filters.txt',
                                         'manifest.json', 'resources.json'])

    def test_manifest(self):
        z = zipfile.ZipFile(io.BytesIO(self.data))
        m = json.loads(z.read('manifest.json'))
        self.assertEqual(m['format'], 1)
        self.assertEqual(m['created'], '2026-10-20T02:30:00Z')
        self.assertEqual(m['ubo_tag'], '1.75.0')
        by = {e['name']: e for e in m['lists']}
        self.assertEqual(by['ublock-filters']['permission'], 1)
        self.assertEqual(by['easylist']['permission'], 0)
        self.assertEqual(by['easylist']['sha256'],
                         hashlib.sha256(b'||ads.example^\n').hexdigest())
        self.assertEqual(m['resources_sha256'], hashlib.sha256(z.read('resources.json')).hexdigest())

    def test_deterministic(self):
        again = bundle.make_zip(fixture_lists(), RESOURCES, '2026-10-20T02:30:00Z', '1.75.0')
        self.assertEqual(self.data, again)


class TestSignVerify(unittest.TestCase):
    def setUp(self):
        self.data = bundle.make_zip(fixture_lists(), RESOURCES, '2026-10-20T02:30:00Z', '1.75.0')
        self.index = bundle.make_index(self.data, 'lists-20261020.zip', RFC_SECRET1)

    def test_index_fields(self):
        self.assertEqual(self.index['format'], 1)
        self.assertEqual(self.index['file'], 'lists-20261020.zip')
        self.assertEqual(self.index['size'], len(self.data))
        self.assertEqual(self.index['created'], '2026-10-20T02:30:00Z')

    def test_good_bundle_verifies(self):
        self.assertEqual(bundle.check(self.data, self.index, RFC_PUBLIC1), None)

    def test_flipped_byte_refused(self):
        bad = bytearray(self.data)
        bad[len(bad) // 2] ^= 1
        self.assertIsNotNone(bundle.check(bytes(bad), self.index, RFC_PUBLIC1))

    def test_other_key_refused(self):
        self.assertIsNotNone(bundle.check(self.data, self.index, RFC_PUBLIC2))

    def test_oversize_refused(self):
        index = dict(self.index, size=17 * 1024 * 1024)
        self.assertIsNotNone(bundle.check(self.data, index, RFC_PUBLIC1))


class TestSpecLists(unittest.TestCase):
    def test_lists_and_permissions(self):
        spec = {name: perm for name, perm in bundle.LISTS}
        self.assertEqual(spec, {
            'ublock-filters': 1, 'ublock-privacy': 1, 'ublock-badware': 1,
            'ublock-quick-fixes': 1, 'ublock-unbreak': 1,
            'easylist': 0, 'easyprivacy': 0, 'IND-0': 0})


if __name__ == '__main__':
    unittest.main()


WORKFLOW = ADBLOCK.parents[1] / '.github' / 'workflows' / 'android-adblock-lists.yml'


class TestWorkflow(unittest.TestCase):
    """A2 Task 2: the daily job that signs and publishes the bundle on
    gettarka.com (spec §4: it must not depend on the Mac being on)."""

    def setUp(self):
        self.y = WORKFLOW.read_text()

    def test_workflow_runs_daily_or_by_hand_only(self):
        self.assertIn("cron: '30 2 * * *'", self.y)
        self.assertIn('workflow_dispatch:', self.y)
        for trigger in ('push:', 'pull_request', 'pull_request_target'):
            self.assertNotIn(trigger, self.y)

    def test_workflow_signs_with_the_secret_and_checks_first(self):
        self.assertIn('secrets.TARK_LISTS_SIGNING_KEY', self.y)
        self.assertLess(self.y.index('listtool/target/release/listtool check'), self.y.index('bundle.py sign'))
        self.assertIn('bundle.py verify', self.y)
        self.assertIn('lists_pubkey.txt', self.y)

    def test_workflow_uses_an_oidc_role_never_static_keys(self):
        self.assertIn('id-token: write', self.y)
        self.assertIn('role-to-assume: arn:aws:iam::967555169405:role/tark-lists-publisher', self.y)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', self.y)
        self.assertNotIn('aws-secret-access-key', self.y)

    def test_workflow_uploads_zip_before_index_and_invalidates_only_the_index(self):
        zip_up = self.y.index('lists/android/v1/$(basename "$z")')
        index_up = self.y.index('lists/android/v1/latest.json --content-type')
        self.assertLess(zip_up, index_up)
        self.assertIn('--paths /lists/android/v1/latest.json', self.y)
        self.assertNotIn("--paths '/*'", self.y)


class TestPublicKey(unittest.TestCase):
    def test_public_key_is_32_bytes_hex(self):
        key = (ADBLOCK / 'lists_pubkey.txt').read_text().strip()
        self.assertEqual(len(bytes.fromhex(key)), 32)


class TestWorkflowHardening(unittest.TestCase):
    """The workflow holds the list-signing key in a public repo."""

    def setUp(self):
        self.y = WORKFLOW.read_text()

    def test_every_action_is_pinned_to_a_commit(self):
        import re
        uses = re.findall(r'uses:\s*(\S+)', self.y)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}$', u)

    def test_checkout_leaves_no_token_behind(self):
        self.assertIn('persist-credentials: false', self.y)

    def test_the_key_is_never_echoed(self):
        self.assertNotIn('set -x', self.y)
        self.assertNotIn('echo "$TARK_LISTS_SIGNING_KEY"', self.y)


class TestKeyOnlyOnMain(unittest.TestCase):
    """The signing key and AWS are reachable only from main (the user,
    2026-10-21): the job runs in the "lists" environment, which only main may
    use and which holds the key; changes to the publishing path need the
    code owner's review."""

    def test_the_job_runs_in_the_lists_environment(self):
        self.assertIn('\n    environment: lists\n', WORKFLOW.read_text())

    def test_the_publishing_path_has_a_code_owner(self):
        owners = (ADBLOCK.parents[1] / '.github' / 'CODEOWNERS').read_text().splitlines()
        rules = {l.split()[0]: l.split()[1:] for l in owners if l.strip() and not l.startswith('#')}
        for path in ('/.github/', '/android/adblock/'):
            self.assertEqual(rules.get(path), ['@soorajpandey'], path)

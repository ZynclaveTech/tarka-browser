"""Tests for utils/trust_data.py (no network: fetches are replaced)."""
import datetime
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import trust_data as td  # noqa: E402

F = td._encode_field


def openssl(*args, data=None):
    return subprocess.run(['openssl', *args], input=data, capture_output=True, check=True).stdout


class Keys:
    """An RSA key pair in a temporary directory."""

    def __init__(self, tmp, name):
        self.path = os.path.join(tmp, name + '.pem')
        openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', self.path)
        self.spki = openssl('pkey', '-in', self.path, '-pubout', '-outform', 'DER')

    def sign(self, message):
        return openssl('dgst', '-sha256', '-sign', self.path, data=message)


def make_crx(keys, app_id, files):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    archive = archive.getvalue()
    signed_header = F(1, bytes((ord(app_id[i]) - 97) << 4 | (ord(app_id[i + 1]) - 97) for i in range(0, 32, 2)))
    message = b'CRX3 SignedData\x00' + struct.pack('<I', len(signed_header)) + signed_header + archive
    header = F(2, F(1, keys.spki) + F(2, keys.sign(message))) + F(10000, signed_header)
    return b'Cr24' + struct.pack('<II', 3, len(header)) + header + archive


def make_cert(tmp, cn):
    path = os.path.join(tmp, cn + '.der')
    openssl('req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
            '-keyout', os.path.join(tmp, cn + '.key'), '-subj', '/CN=' + cn, '-days', '30',
            '-outform', 'DER', '-out', path)
    with open(path, 'rb') as f:
        return f.read()


def make_crl_set(sequence):
    header = json.dumps({'Version': 0, 'ContentType': 'CRLSet', 'Sequence': sequence,
                         'NumParents': 0, 'BlockedSPKIs': []}).encode()
    return struct.pack('<H', len(header)) + header


class TmpCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class Crx3Test(TmpCase):

    def setUp(self):
        super().setUp()
        self.keys = Keys(self.tmp, 'component')
        self.component = td.Component(td.crx_id(self.keys.spki), td.sha256_hex(self.keys.spki), '', '')

    def test_verified_crx_gives_its_archive(self):
        crx = make_crx(self.keys, self.component.app_id, {'crl-set': b'data'})
        archive = td.verify_crx3(crx, self.component)
        self.assertEqual(zipfile.ZipFile(io.BytesIO(archive)).read('crl-set'), b'data')

    def test_changed_archive_fails(self):
        crx = make_crx(self.keys, self.component.app_id, {'crl-set': b'data'})
        with self.assertRaisesRegex(td.TrustDataError, 'does not verify'):
            td.verify_crx3(crx[:-1] + bytes([crx[-1] ^ 1]), self.component)

    def test_other_key_fails(self):
        other = Keys(self.tmp, 'other')
        crx = make_crx(other, self.component.app_id, {'crl-set': b'data'})
        with self.assertRaisesRegex(td.TrustDataError, 'no proof by the pinned key'):
            td.verify_crx3(crx, self.component)

    def test_other_component_id_fails(self):
        crx = make_crx(self.keys, 'a' * 32, {'crl-set': b'data'})
        with self.assertRaisesRegex(td.TrustDataError, 'another component'):
            td.verify_crx3(crx, self.component)

    def test_chromium_pin_is_read_from_the_tree(self):
        path = os.path.join(self.tmp, 'installer.cc')
        with open(path, 'w') as f:
            f.write('const uint8_t kPin[32] = {\n' + ', '.join('0x%02x' % b for b in range(32)) + '};\n')
        component = td.Component('', '', 'installer.cc', 'kPin')
        self.assertEqual(td.chromium_pin(self.tmp, component), bytes(range(32)).hex())


class RootStoreTest(TmpCase):

    def setUp(self):
        super().setUp()
        self.root_a = make_cert(self.tmp, 'Root A')
        self.root_b = make_cert(self.tmp, 'Root B')
        self.extra = make_cert(self.tmp, 'Extra')
        constraints = F(1, 1790812799) + F(3, b'153.0.8010.0')
        self.crs = (F(1, F(1, self.root_a) + F(3, b'2.23.140.1.1') + F(4, constraints) + F(12, 28))
                    + F(1, F(1, self.root_b) + F(11, b'\x83\x9a') + F(10, 1))
                    + F(2, 42)
                    + F(3, F(1, self.extra) + F(6, 1)))

    def test_textproto_names_certs_by_hash(self):
        version, files, anchors = td.root_store_files(self.crs, set(), 'test', log=lambda m: None)
        text = files['root_store.textproto'].decode()
        self.assertEqual(version, 42)
        self.assertIn('version_major: 42\n', text)
        a, b = td.sha256_hex(self.root_a), td.sha256_hex(self.root_b)
        self.assertIn('# CN=Root A\ntrust_anchors {\n  sha256_hex: "%s"\n  ev_policy_oids: "2.23.140.1.1"\n'
                      '  constraints {\n    sct_not_after_sec: 1790812799\n    min_version: "153.0.8010.0"\n'
                      '  }\n  crs_root_id: 28\n}' % a, text)
        self.assertIn('  trust_anchor_id: "\\x83\\x9a"\n  tls_trust_anchor: true\n', text)
        self.assertIn('additional_certs {\n  sha256_hex: "%s"\n  eutl: true\n}' % td.sha256_hex(self.extra), text)
        self.assertEqual(anchors, {a: 'CN=Root A', b: 'CN=Root B'})
        self.assertEqual(td.textproto_anchors(text), anchors)
        certs = files['root_store.certs'].decode()
        self.assertIn('# %s\n# CN=Root A\n-----BEGIN CERTIFICATE-----\n' % a, certs)
        self.assertNotIn('Extra', certs)
        self.assertIn('CN=Extra', files['additional.certs'].decode())

    def test_distrusted_anchor_is_left_out(self):
        a = td.sha256_hex(self.root_a)
        logged = []
        _, files, anchors = td.root_store_files(self.crs, {a, 'f' * 64}, 'test', log=logged.append)
        self.assertNotIn(a, anchors)
        self.assertNotIn(a, files['root_store.textproto'].decode())
        self.assertNotIn(a, files['root_store.certs'].decode())
        self.assertEqual(logged, ['distrust.txt: %s is not in root store v42 (removed upstream already)' % ('f' * 64)])

    def test_unknown_field_fails(self):
        with self.assertRaisesRegex(td.TrustDataError, 'field 7 in trust_anchors'):
            td.root_store_files(self.crs + F(1, F(1, self.root_a) + F(7, 1)), set(), 'test')

    def test_negative_int64(self):
        self.assertEqual(td._scalar('int64', (1 << 64) - 5), '-5')


class InstallTest(TmpCase):

    def setUp(self):
        super().setUp()
        self.data = os.path.join(self.tmp, 'trust')
        self.tree = os.path.join(self.tmp, 'src')
        os.makedirs(self.data)
        self.files = {
            'log_list.json': b'{"url": "https://ct.googleapis.com/logs/"}',
            'crl-set': make_crl_set(7),
            'root_store.textproto': b'version_major: 42\n',
            'root_store.certs': b'# certs\n',
            'additional.certs': b'# additional\n',
        }
        for name, data in self.files.items():
            with open(os.path.join(self.data, name), 'wb') as f:
                f.write(data)
        self.write_manifest()
        for dest in (td.LOG_LIST_DEST, td.ROOT_STORE_DIR + '/root_store.textproto',
                     td.ROOT_STORE_DIR + '/root_store.certs', td.ROOT_STORE_DIR + '/additional.certs'):
            os.makedirs(os.path.join(self.tree, os.path.dirname(dest)), exist_ok=True)
            open(os.path.join(self.tree, dest), 'w').close()
        os.makedirs(os.path.join(self.tree, os.path.dirname(td.CRL_SET_INC)))

    def write_manifest(self):
        with open(os.path.join(self.data, 'manifest.json'), 'w') as f:
            json.dump({'crl_set': {'sequence': 7, 'component_version': '7'},
                       'sha256': {n: td.sha256_hex(d) for n, d in self.files.items()}}, f)

    def read(self, path):
        with open(os.path.join(self.tree, path), 'rb') as f:
            return f.read()

    def test_copies_files_and_writes_the_crl_set_array(self):
        regex = os.path.join(self.tmp, 'domain_regex.list')
        with open(regex, 'w') as f:
            f.write('google([A-Za-z\\-]*?\\\\*?)\\.com(?!mon)#9oo91e\\g<1>.qjz9zk\n')
        td.install(self.tree, self.data, regex)
        self.assertEqual(self.read(td.LOG_LIST_DEST), b'{"url": "https://ct.9oo91eapis.qjz9zk/logs/"}')
        self.assertEqual(self.read(td.ROOT_STORE_DIR + '/additional.certs'), b'# additional\n')
        inc = self.read(td.CRL_SET_INC).decode()
        self.assertIn('// CRLSet sequence 7', inc)
        values = bytes(int(v, 16) for v in inc.replace(',', ' ').split() if v.startswith('0x'))
        self.assertEqual(values, self.files['crl-set'])

    def test_changed_file_fails(self):
        with open(os.path.join(self.data, 'crl-set'), 'ab') as f:
            f.write(b'x')
        with self.assertRaisesRegex(td.TrustDataError, 'crl-set does not match'):
            td.install(self.tree, self.data)

    def test_missing_destination_fails(self):
        os.remove(os.path.join(self.tree, td.LOG_LIST_DEST))
        with self.assertRaisesRegex(td.TrustDataError, 'moved upstream'):
            td.install(self.tree, self.data)


class CheckTest(TmpCase):

    def write_list(self, stamp):
        with open(os.path.join(self.tmp, 'log_list.json'), 'w') as f:
            json.dump({'log_list_timestamp': stamp}, f)

    def test_fresh_list_passes_and_gives_the_lapse_date(self):
        self.write_list('2026-10-22T13:35:15Z')
        now = datetime.datetime(2026, 10, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(td.check(self.tmp, 21, now).date(), datetime.date(2026, 12, 31))

    def test_old_list_fails(self):
        self.write_list('2026-09-20T13:35:40Z')
        now = datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc)
        with self.assertRaisesRegex(td.TrustDataError, '31 days old.*lapses 2026-11-29'):
            td.check(self.tmp, 21, now)


class RefreshTest(TmpCase):
    """refresh with Google's servers replaced by test keys and data."""

    def setUp(self):
        super().setUp()
        self.data = os.path.join(self.tmp, 'trust')
        os.makedirs(self.data)
        with open(os.path.join(self.data, 'distrust.txt'), 'w') as f:
            f.write('# none\n')
        self.log_keys = Keys(self.tmp, 'loglist')
        self.crl_keys = Keys(self.tmp, 'crl')
        self.pki_keys = Keys(self.tmp, 'pki')
        self.saved = (td.LOG_LIST_KEY_SHA256, td.CRL_SET, td.PKI_METADATA, td.fetch, td.fetch_component)
        td.LOG_LIST_KEY_SHA256 = td.sha256_hex(self.log_keys.spki)
        td.CRL_SET = td.Component(td.crx_id(self.crl_keys.spki), td.sha256_hex(self.crl_keys.spki), '', '')
        td.PKI_METADATA = td.Component(td.crx_id(self.pki_keys.spki), td.sha256_hex(self.pki_keys.spki), '', '')
        self.sequence = 10
        self.stamp = '2026-10-22T13:35:15Z'
        root = make_cert(self.tmp, 'Root')
        self.crs = F(1, F(1, root)) + F(2, 42)
        td.fetch = self.fake_fetch
        td.fetch_component = self.fake_component

    def tearDown(self):
        td.LOG_LIST_KEY_SHA256, td.CRL_SET, td.PKI_METADATA, td.fetch, td.fetch_component = self.saved
        super().tearDown()

    def log_list(self):
        return json.dumps({'version': '1.0', 'log_list_timestamp': self.stamp, 'operators': []}).encode()

    def fake_fetch(self, url, data=None, headers=None):
        if url.endswith('log_list.json'):
            return self.log_list()
        if url.endswith('log_list.sig'):
            return self.log_keys.sign(self.log_list())
        if url.endswith('log_list_pubkey.pem'):
            return openssl('pkey', '-in', self.log_keys.path, '-pubout')
        raise AssertionError(url)

    def fake_component(self, component, prodversion):
        if component is td.CRL_SET:
            return '1', make_crx(self.crl_keys, component.app_id, {'crl-set': make_crl_set(self.sequence)})
        return '2', make_crx(self.pki_keys, component.app_id, {'crs.pb': self.crs})

    def test_writes_files_and_manifest(self):
        manifest = td.refresh(self.data, log=lambda m: None)
        self.assertEqual(manifest['crl_set']['sequence'], 10)
        self.assertEqual(manifest['root_store']['version_major'], 42)
        for name, digest in manifest['sha256'].items():
            with open(os.path.join(self.data, name), 'rb') as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest)

    def test_bad_log_list_signature_fails(self):
        self.log_keys = Keys(self.tmp, 'impostor')
        with self.assertRaisesRegex(td.TrustDataError, 'different log-list key'):
            td.refresh(self.data, log=lambda m: None)

    def test_going_backwards_fails(self):
        td.refresh(self.data, log=lambda m: None)
        self.sequence = 9
        with self.assertRaisesRegex(td.TrustDataError, 'older than what resources/trust has: CRLSet'):
            td.refresh(self.data, log=lambda m: None)
        td.refresh(self.data, allow_older=True, log=lambda m: None)


if __name__ == '__main__':
    unittest.main()

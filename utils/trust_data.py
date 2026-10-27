#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's certificate trust data: CT log list, Chrome Root Store, CRLSet.

    python3 utils/trust_data.py refresh [--data DIR] [--chromium-src TREE]
    python3 utils/trust_data.py install TREE [--data DIR]
    python3 utils/trust_data.py check [--data DIR] [--max-age-days N]

Tark's component updater serves only Widevine, so Chrome's pushes of these
three never reach it. Each release carries them instead (tarka-notes
notes/2026-10-22-trust-data-updates.md, option (c), step 1).

refresh (on a build machine; users never contact Google for this) fetches
and verifies, then writes resources/trust/:
  - log_list.json from gstatic.com, checked against its .sig with Google's
    log-list key (pinned below). Chromium rolls this same file verbatim.
  - crl-set from the CRLSet component (update.googleapis.com), its CRX3
    signature checked against the key Chromium pins in
    crl_set_component_installer.cc.
  - root_store.textproto, root_store.certs and additional.certs, written
    from crs.pb in the PKI-metadata component (also a CRX3 checked against
    Chromium's pin): the root store Chrome itself is using, in the textproto
    form Chromium's root_store_tool builds from. Tark's own distrusts
    (distrust.txt) are left out. A field the schema below does not know
    fails the refresh rather than being dropped.
  - manifest.json: where each file came from, its version and sha256.
A refresh that would go backwards (older list, lower CRLSet sequence or
root store version) fails unless --allow-older.

install copies the files over Chromium's (after domain substitution, which it
applies to the log list itself with --domain-regex) and writes the CRLSet as
a C++ byte array for tark_bundled_crl_set.cc, checking each file against the
manifest first.

check fails when the log list is too old to ship: Chromium stops enforcing
CT 70 days after the list's date (ChromeCTPolicyEnforcer::IsLogDataTimely).
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(REPO, 'resources', 'trust')

LOG_LIST_URL = 'https://www.gstatic.com/ct/log_list/v3/'
# SHA-256 of the SubjectPublicKeyInfo of Google's CT log-list signing key
# (RSA-4096), published at gstatic.com/ct/log_list/v3/log_list_pubkey.pem.
LOG_LIST_KEY_SHA256 = 'f1d8b68e50210d8e73d9a3e97f571773c52d7f28c0b1a71beee81d8562e6fd85'

OMAHA_URL = 'https://update.googleapis.com/service/update2/json'


class Component:

    def __init__(self, app_id, key_sha256, pin_file, pin_name):
        self.app_id = app_id
        self.key_sha256 = key_sha256
        self.pin_file = pin_file
        self.pin_name = pin_name


CRL_SET = Component(
    'hfnkpimlhhgieaddgfemjhofmfblmnib',
    '75daf8cb77684033654c97e5c51bcd817b1eeb112ce1a4338cf5725eedb84397',
    'chrome/browser/component_updater/crl_set_component_installer.cc', 'kCrlSetPublicKeySHA256')
PKI_METADATA = Component(
    'efniojlnjndmcbiieegkicadnoecjjef',
    '45d8e9bd9d3c2188446a8203de4299456625feb3d1f81165b46fd31b2189be9c',
    'chrome/browser/component_updater/pki_metadata_component_installer_policy.cc',
    'kPKIMetadataPublicKeySHA256')

ROOT_STORE_DIR = 'net/data/ssl/chrome_root_store'
LOG_LIST_DEST = 'components/certificate_transparency/data/log_list.json'
CRL_SET_INC = 'chrome/browser/net/tark_crl_set_data.inc'
CT_TIMELY_DAYS = 70


class TrustDataError(Exception):
    pass


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


# --- protobuf (just enough to read CRX3 headers and RootStore) -------------

def _varint(data, pos):
    result = shift = 0
    while True:
        if pos >= len(data):
            raise TrustDataError('truncated protobuf')
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def proto_fields(data):
    """Yields (field number, value) for each field; bytes for length-delimited."""
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            value, pos = data[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = _varint(data, pos)
            value, pos = data[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = data[pos:pos + 4], pos + 4
        else:
            raise TrustDataError('unsupported protobuf wire type %d' % wire)
        yield number, value


# --- signatures -------------------------------------------------------------

def openssl_verify(spki_der, signature, message):
    """Verifies a SHA-256 RSA (PKCS#1 v1.5) or ECDSA signature with openssl."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for name, data in (('key.der', spki_der), ('sig', signature), ('msg', message)):
            paths[name] = os.path.join(tmp, name)
            with open(paths[name], 'wb') as f:
                f.write(data)
        result = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-verify', paths['key.der'], '-keyform', 'DER',
             '-signature', paths['sig'], paths['msg']],
            capture_output=True)
        return result.returncode == 0


def crx_id(spki_der):
    return ''.join(chr(ord('a') + int(c, 16)) for c in sha256_hex(spki_der)[:32])


def verify_crx3(crx, component):
    """Returns the CRX's zip archive once a proof by the pinned key verifies."""
    if crx[:4] != b'Cr24' or struct.unpack('<I', crx[4:8])[0] != 3:
        raise TrustDataError('not a CRX3 file')
    header_size = struct.unpack('<I', crx[8:12])[0]
    header = crx[12:12 + header_size]
    archive = crx[12 + header_size:]
    proofs, signed_header = [], None
    for number, value in proto_fields(header):
        if number in (2, 3):  # sha256_with_rsa, sha256_with_ecdsa
            proof = dict(proto_fields(value))
            proofs.append((proof.get(1, b''), proof.get(2, b'')))
        elif number == 10000:
            signed_header = value
    if signed_header is None:
        raise TrustDataError('CRX3 has no signed header data')
    signed_id = dict(proto_fields(signed_header)).get(1, b'')
    if ''.join(chr(ord('a') + (b >> 4)) + chr(ord('a') + (b & 15)) for b in signed_id) != component.app_id:
        raise TrustDataError('CRX3 is signed for another component')
    message = b'CRX3 SignedData\x00' + struct.pack('<I', len(signed_header)) + signed_header + archive
    for key, signature in proofs:
        if sha256_hex(key) == component.key_sha256:
            if crx_id(key) != component.app_id:
                raise TrustDataError('pinned key does not match the component id')
            if openssl_verify(key, signature, message):
                return archive
            raise TrustDataError('CRX3 signature by the pinned key does not verify')
    raise TrustDataError('CRX3 carries no proof by the pinned key %s' % component.key_sha256)


def chromium_pin(tree, component):
    """Reads the key hash Chromium pins for a component, as hex."""
    with open(os.path.join(tree, component.pin_file)) as f:
        text = f.read()
    match = re.search(re.escape(component.pin_name) + r'\[32\]\s*=\s*\{([^}]*)\}', text)
    if not match:
        raise TrustDataError('%s not found in %s' % (component.pin_name, component.pin_file))
    return ''.join('%02x' % int(b, 16) for b in re.findall(r'0x([0-9a-fA-F]{2})', match.group(1)))


# --- network ----------------------------------------------------------------

def fetch(url, data=None, headers=None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_component(component, prodversion):
    """Asks Google's update server for a component; returns (version, crx)."""
    body = json.dumps({'request': {
        'protocol': '3.1', 'acceptformat': 'crx3', 'updater': 'chromium',
        'prodversion': prodversion, 'os': {'platform': 'Mac OS X', 'arch': 'arm64'},
        'arch': 'arm64',
        'app': [{'appid': component.app_id, 'version': '0.0.0.0', 'updatecheck': {}}],
    }}).encode()
    raw = fetch(OMAHA_URL, body, {'Content-Type': 'application/json'})
    response = json.loads(raw.decode().split('\n', 1)[1] if raw.startswith(b")]}'") else raw)
    app = response['response']['app'][0]
    check = app['updatecheck']
    if check.get('status') != 'ok':
        raise TrustDataError('%s: update check said %r' % (component.app_id, check.get('status')))
    package = check['manifest']['packages']['package'][0]
    codebase = next(u['codebase'] for u in check['urls']['url'] if u['codebase'].startswith('https://'))
    crx = fetch(codebase + package['name'])
    if sha256_hex(crx) != package['hash_sha256']:
        raise TrustDataError('%s: download does not match the update server\'s hash' % component.app_id)
    return check['manifest']['version'], crx


# --- data -------------------------------------------------------------------

def crl_set_sequence(crl_set):
    header_len = struct.unpack('<H', crl_set[:2])[0]
    header = json.loads(crl_set[2:2 + header_len])
    if header.get('ContentType') != 'CRLSet':
        raise TrustDataError('crl-set is not a CRLSet')
    return header['Sequence']


# Chromium 155's net/cert/root_store.proto, field number -> (name, type).
# A message type is another dict.
CONSTRAINT_SET = {
    1: ('sct_not_after_sec', 'int64'), 2: ('sct_all_after_sec', 'int64'),
    3: ('min_version', 'string'), 4: ('max_version_exclusive', 'string'),
    5: ('permitted_dns_names', 'string'), 8: ('index_not_after', 'uint64'),
    9: ('index_after', 'uint64'), 10: ('validity_starts_not_after_sec', 'int64'),
    11: ('validity_starts_after_sec', 'int64'),
}
TRUST_ANCHOR = {
    1: ('der', 'bytes'), 2: ('sha256_hex', 'string'), 3: ('ev_policy_oids', 'string'),
    4: ('constraints', CONSTRAINT_SET), 5: ('display_name', 'string'), 6: ('eutl', 'bool'),
    8: ('enforce_anchor_expiry', 'bool'), 9: ('enforce_anchor_constraints', 'bool'),
    10: ('tls_trust_anchor', 'bool'), 11: ('trust_anchor_id', 'bytes'), 12: ('crs_root_id', 'int32'),
}
MTC_ANCHOR = {
    1: ('log_id', 'bytes'), 2: ('constraints', CONSTRAINT_SET), 3: ('tls_trust_anchor', 'bool'),
    4: ('crs_root_id', 'int32'),
}
ROOT_STORE = {
    1: ('trust_anchors', TRUST_ANCHOR), 2: ('version_major', 'int64'),
    3: ('additional_certs', TRUST_ANCHOR), 4: ('mtc_anchors', MTC_ANCHOR),
}


def _quote(data):
    out = []
    for b in data:
        c = chr(b)
        out.append('\\' + c if c in '"\\' else c if 32 <= b < 127 else '\\x%02x' % b)
    return '"' + ''.join(out) + '"'


def _scalar(kind, value):
    if kind in ('int64', 'int32'):
        return str(value - (1 << 64) if value >= 1 << 63 else value)
    if kind == 'uint64':
        return str(value)
    if kind == 'bool':
        return 'true' if value else 'false'
    if kind == 'string':
        return _quote(value)
    return '"%s"' % ''.join('\\x%02x' % b for b in value)  # bytes


def textproto_fields(data, schema, indent, where):
    """Text-format lines for a message, failing on fields the schema lacks."""
    lines = []
    for number, value in proto_fields(data):
        if number not in schema:
            raise TrustDataError('crs.pb has field %d in %s, which Chromium 155\'s root_store.proto '
                                 'lacks; check the proto and update trust_data.py' % (number, where))
        name, kind = schema[number]
        if isinstance(kind, dict):
            lines.append('%s%s {' % (indent, name))
            lines += textproto_fields(value, kind, indent + '  ', name)
            lines.append('%s}' % indent)
        else:
            if isinstance(value, bytes) != (kind in ('string', 'bytes')):
                raise TrustDataError('crs.pb: %s.%s has the wrong wire type' % (where, name))
            lines.append('%s%s: %s' % (indent, name, _scalar(kind, value)))
    return lines


def _encode_varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        if not value:
            out.append(byte)
            return bytes(out)
        out.append(byte | 0x80)


def _encode_field(number, value):
    """Encodes a varint (int) or length-delimited (bytes) field."""
    if isinstance(value, int):
        return _encode_varint(number << 3) + _encode_varint(value)
    return _encode_varint(number << 3 | 2) + _encode_varint(len(value)) + value


def cert_subject(der):
    result = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-noout', '-subject',
                             '-nameopt', 'RFC2253'], input=der, capture_output=True, check=True)
    return result.stdout.decode().strip().removeprefix('subject=')


def pem(der):
    body = base64.b64encode(der).decode()
    return '-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----\n' % '\n'.join(
        body[i:i + 64] for i in range(0, len(body), 64))


def root_store_files(crs_pb, distrusted, source, log=print):
    """root_store.textproto, root_store.certs and additional.certs from crs.pb.

    As in Chromium's own files, certificates go to the .certs files and the
    textproto names each by SHA-256. Distrusted trust anchors are left out.
    Returns (version, {file name: bytes}, {trust-anchor SHA-256: subject}).
    """
    header = ('# Generated by utils/trust_data.py refresh from %s.\n'
              '# Do not edit: Tark\'s own removals are in resources/trust/distrust.txt.\n' % source)
    blocks = []
    certs = {'trust_anchors': [header], 'additional_certs': [header]}
    version, anchors, dropped = None, {}, set()
    for number, value in proto_fields(crs_pb):
        if number not in ROOT_STORE:
            raise TrustDataError('crs.pb has field %d in RootStore, which Chromium 155\'s '
                                 'root_store.proto lacks' % number)
        name, kind = ROOT_STORE[number]
        if name == 'version_major':
            version = value
            continue
        comment = []
        if kind is TRUST_ANCHOR:
            fields = list(proto_fields(value))
            der = dict(fields).get(1)
            if der is None:
                raise TrustDataError('crs.pb: a %s entry has no certificate' % name)
            digest = sha256_hex(der)
            if name == 'trust_anchors' and digest in distrusted:
                dropped.add(digest)
                continue
            subject = cert_subject(der)
            if name == 'trust_anchors':
                anchors[digest] = subject
            comment = ['# ' + subject]
            certs[name].append('\n# %s\n# %s\n%s' % (digest, subject, pem(der)))
            value = _encode_field(2, digest.encode()) + b''.join(
                _encode_field(n, v) for n, v in fields if n != 1)
        blocks.append('\n'.join(comment + ['%s {' % name] + textproto_fields(value, kind, '  ', name) + ['}']))
    if version is None:
        raise TrustDataError('crs.pb has no version_major')
    for digest in sorted(distrusted - dropped):
        log('distrust.txt: %s is not in root store v%d (removed upstream already)' % (digest, version))
    textproto = header + '\nversion_major: %d\n\n' % version + '\n\n'.join(blocks) + '\n'
    files = {
        'root_store.textproto': textproto,
        'root_store.certs': ''.join(certs['trust_anchors']),
        'additional.certs': ''.join(certs['additional_certs']),
    }
    return version, {k: v.encode() for k, v in files.items()}, anchors


def textproto_anchors(text):
    """{SHA-256: comment} of the trust anchors in a root_store.textproto."""
    found = re.findall(r'((?:^#[^\n]*\n)*)^trust_anchors \{\n(?:^ [^\n]*\n)*?\s*sha256_hex: "([0-9a-f]{64})"',
                       text, re.M)
    return {digest: comment.strip().splitlines()[0].lstrip('# ') if comment.strip() else ''
            for comment, digest in found}


def read_distrust(data_dir):
    path = os.path.join(data_dir, 'distrust.txt')
    result = set()
    with open(path) as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if line:
                if not re.fullmatch(r'[0-9a-f]{64}', line):
                    raise TrustDataError('distrust.txt: not a SHA-256: %r' % line)
                result.add(line)
    return result


def log_list_date(log_list_json):
    stamp = json.loads(log_list_json)['log_list_timestamp']
    return datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def read_manifest(data_dir):
    path = os.path.join(data_dir, 'manifest.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def write_file(path, data):
    with open(path, 'wb') as f:
        f.write(data)


# --- commands ---------------------------------------------------------------

def refresh(data_dir, chromium_src=None, prodversion='156.0.8078.47', allow_older=False,
            log=print):
    if chromium_src:
        for component in (CRL_SET, PKI_METADATA):
            if chromium_pin(chromium_src, component) != component.key_sha256:
                raise TrustDataError('%s in the tree differs from trust_data.py\'s pin' % component.pin_name)

    # CT log list.
    log_list = fetch(LOG_LIST_URL + 'log_list.json')
    signature = fetch(LOG_LIST_URL + 'log_list.sig')
    key_der = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'],
                             input=fetch(LOG_LIST_URL + 'log_list_pubkey.pem'),
                             capture_output=True, check=True).stdout
    if sha256_hex(key_der) != LOG_LIST_KEY_SHA256:
        raise TrustDataError('gstatic serves a different log-list key')
    if not openssl_verify(key_der, signature, log_list):
        raise TrustDataError('log_list.json does not match log_list.sig')
    log_list_info = json.loads(log_list)
    log('log list %s, %s' % (log_list_info['version'], log_list_info['log_list_timestamp']))

    # CRLSet.
    crl_version, crl_crx = fetch_component(CRL_SET, prodversion)
    crl_zip = zipfile.ZipFile(io.BytesIO(verify_crx3(crl_crx, CRL_SET)))
    crl_set = crl_zip.read('crl-set')
    sequence = crl_set_sequence(crl_set)
    log('CRLSet component %s, sequence %d, %d bytes' % (crl_version, sequence, len(crl_set)))

    # Root store: the one Chrome is using, from the PKI-metadata component.
    pki_version, pki_crx = fetch_component(PKI_METADATA, prodversion)
    pki_zip = zipfile.ZipFile(io.BytesIO(verify_crx3(pki_crx, PKI_METADATA)))
    distrusted = read_distrust(data_dir)
    version, root_files, anchors = root_store_files(
        pki_zip.read('crs.pb'), distrusted,
        'crs.pb in the PKI-metadata component %s, version %s' % (PKI_METADATA.app_id, pki_version), log)
    log('PKI metadata component %s: root store v%d, %d trust anchors after Tark\'s distrusts'
        % (pki_version, version, len(anchors)))
    # For review: what changed against the root store Tark had.
    before_path = os.path.join(data_dir, 'root_store.textproto')
    if not os.path.exists(before_path) and chromium_src:
        before_path = os.path.join(chromium_src, ROOT_STORE_DIR, 'root_store.textproto')
    if os.path.exists(before_path):
        with open(before_path) as f:
            before = textproto_anchors(f.read())
        for digest in sorted(set(anchors) - set(before), key=anchors.get):
            log('  + %s' % anchors[digest])
        for digest in sorted(set(before) - set(anchors), key=before.get):
            log('  - %s' % (before[digest] or digest))

    previous = read_manifest(data_dir)
    if previous and not allow_older:
        backwards = []
        if log_list_info['log_list_timestamp'] < previous['log_list']['timestamp']:
            backwards.append('log list')
        if sequence < previous['crl_set']['sequence']:
            backwards.append('CRLSet')
        if version < previous['root_store']['version_major']:
            backwards.append('root store')
        if backwards:
            raise TrustDataError('older than what resources/trust has: ' + ', '.join(backwards))

    files = {
        'log_list.json': log_list,
        'crl-set': crl_set,
        **root_files,
    }
    manifest = {
        'fetched': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'log_list': {
            'source': LOG_LIST_URL + 'log_list.json',
            'version': log_list_info['version'],
            'timestamp': log_list_info['log_list_timestamp'],
            'signing_key_sha256': LOG_LIST_KEY_SHA256,
        },
        'crl_set': {
            'component': CRL_SET.app_id,
            'component_version': crl_version,
            'crx_sha256': sha256_hex(crl_crx),
            'sequence': sequence,
        },
        'root_store': {
            'component': PKI_METADATA.app_id,
            'component_version': pki_version,
            'crx_sha256': sha256_hex(pki_crx),
            'version_major': version,
            'distrusted': sorted(distrusted),
        },
        'sha256': {name: sha256_hex(data) for name, data in files.items()},
    }
    os.makedirs(data_dir, exist_ok=True)
    for name, data in files.items():
        write_file(os.path.join(data_dir, name), data)
    write_file(os.path.join(data_dir, 'manifest.json'),
               (json.dumps(manifest, indent=2) + '\n').encode())
    return manifest


def crl_set_inc(crl_set, manifest):
    lines = ['// Generated by utils/trust_data.py install. Do not edit.',
             '// CRLSet sequence %d (component version %s).' % (
                 manifest['crl_set']['sequence'], manifest['crl_set']['component_version'])]
    for i in range(0, len(crl_set), 16):
        lines.append(' '.join('0x%02x,' % b for b in crl_set[i:i + 16]))
    return '\n'.join(lines) + '\n'


def substitute_domains(text, regex_list):
    """Applies ungoogled-chromium's domain_regex.list, as domain_substitution.py does."""
    with open(regex_list) as f:
        for line in filter(len, f.read().splitlines()):
            pattern, replacement = line.split('#')
            text = re.sub(pattern, replacement, text)
    return text


def install(tree, data_dir, domain_regex=None):
    manifest = read_manifest(data_dir)
    if manifest is None:
        raise TrustDataError('no manifest.json in %s' % data_dir)
    files = {}
    for name, digest in manifest['sha256'].items():
        with open(os.path.join(data_dir, name), 'rb') as f:
            files[name] = f.read()
        if sha256_hex(files[name]) != digest:
            raise TrustDataError('%s does not match manifest.json' % name)
    copies = {
        'log_list.json': LOG_LIST_DEST,
        'root_store.textproto': ROOT_STORE_DIR + '/root_store.textproto',
        'root_store.certs': ROOT_STORE_DIR + '/root_store.certs',
        'additional.certs': ROOT_STORE_DIR + '/additional.certs',
    }
    missing = [dest for dest in copies.values() if not os.path.isfile(os.path.join(tree, dest))]
    if missing or not os.path.isdir(os.path.join(tree, os.path.dirname(CRL_SET_INC))):
        raise TrustDataError('not in the tree (moved upstream?): ' +
                             ', '.join(missing or [os.path.dirname(CRL_SET_INC)]))
    if domain_regex:
        # Chromium's log list is on ungoogled-chromium's substitution list;
        # install runs after substitution, so it substitutes its own copy.
        files['log_list.json'] = substitute_domains(files['log_list.json'].decode(), domain_regex).encode()
    for name, dest in copies.items():
        write_file(os.path.join(tree, dest), files[name])
    write_file(os.path.join(tree, CRL_SET_INC), crl_set_inc(files['crl-set'], manifest).encode())
    return manifest


def check(data_dir, max_age_days, now=None):
    """Returns the date CT enforcement lapses; fails if the list is too old to ship."""
    with open(os.path.join(data_dir, 'log_list.json'), 'rb') as f:
        date = log_list_date(f.read())
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = (now - date).days
    lapse = date + datetime.timedelta(days=CT_TIMELY_DAYS)
    if age > max_age_days:
        raise TrustDataError('log list is %d days old (limit %d); run trust_data.py refresh. '
                             'CT enforcement lapses %s.' % (age, max_age_days, lapse.date()))
    return lapse


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--data', default=DEFAULT_DATA)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('refresh')
    p.add_argument('--chromium-src', help='check Chromium\'s component key pins against ours')
    p.add_argument('--prodversion', default='156.0.8078.47')
    p.add_argument('--allow-older', action='store_true')
    p = sub.add_parser('install')
    p.add_argument('tree')
    p.add_argument('--domain-regex', help='ungoogled-chromium\'s domain_regex.list, to substitute '
                   'the log list\'s hosts as the rest of the tree')
    p = sub.add_parser('check')
    p.add_argument('--max-age-days', type=int, default=21)
    args = parser.parse_args()
    try:
        if args.command == 'refresh':
            refresh(args.data, args.chromium_src, args.prodversion, args.allow_older)
        elif args.command == 'install':
            manifest = install(args.tree, args.data, args.domain_regex)
            print('trust data installed: log list %s, root store v%d, CRLSet sequence %d' % (
                manifest['log_list']['timestamp'], manifest['root_store']['version_major'],
                manifest['crl_set']['sequence']))
        else:
            lapse = check(args.data, args.max_age_days)
            print('log list fresh enough; CT enforcement lapses %s' % lapse.date())
    except TrustDataError as e:
        print('trust_data.py: %s' % e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

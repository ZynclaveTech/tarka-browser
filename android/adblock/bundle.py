#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's adblock list bundle (A2, spec §4).

    bundle.py build --out DIR [--listtool PATH]
    bundle.py pin-ubo TAG                           prints ubo.json for TAG
    bundle.py sign ZIP --key SECRET_HEX_FILE        writes DIR/latest.json
    bundle.py verify ZIP INDEX.json --pubkey HEX_OR_FILE
    bundle.py keygen --out SECRET_HEX_FILE          prints the public key

One zip holds the lists as text (lists/<name>.txt), uBlock Origin's redirect
resources and scriptlets as adblock-rust Resources (resources.json), and
manifest.json. latest.json carries the zip's size, sha256 and an Ed25519
signature over its bytes. Phones verify the signature and compile the lists
themselves; the same zip ships in the APK.

uBlock Origin's code runs while bundling (scriptlets.mjs imports its scriptlet
module), so build uses only the version pinned in ubo.json, whose tarball must
have the pinned sha256. A new uBO is a reviewed change to ubo.json (pin-ubo).
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections import namedtuple

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ed25519  # noqa: E402

# Spec §4, by uBlock Origin's assets.json keys. uBO's own lists are trusted
# with permission mask 1: their trusted-* scriptlets (most of YouTube's
# rules) are dropped without it.
LISTS = [
    ('ublock-filters', 1), ('ublock-privacy', 1), ('ublock-badware', 1),
    ('ublock-quick-fixes', 1), ('ublock-unbreak', 1),
    ('easylist', 0), ('easyprivacy', 0), ('IND-0', 0),
]
INDIANLIST = 'https://easylist-downloads.adblockplus.org/indianlist.txt'
MAX_SIZE = 16 * 1024 * 1024
FORMAT = 1
USER_AGENT = 'Tark-lists/1 (+https://gettarka.com)'

# `!#if` tokens that hold for Tark, per platform, as uBO evaluates them on
# Chromium for Android and on desktop Chromium (Mac and Windows share one
# bundle). Tark injects user stylesheets (cap_user_stylesheet); every other
# token is false, as in uBO.
PLATFORM_TOKENS = {
    'android': frozenset({'env_chromium', 'env_mobile', 'cap_user_stylesheet'}),
    'desktop': frozenset({'env_chromium', 'cap_user_stylesheet'}),
}


def _tokens(platform):
    if platform not in PLATFORM_TOKENS:
        raise ValueError(f'unknown platform {platform!r}')
    return PLATFORM_TOKENS[platform]

List = namedtuple('List', 'name url permission text')


def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode('utf-8')


# --- !#if / !#include, as uBO's preprocessor ---------------------------------

def _eval(expr, true_tokens):
    tokens = re.findall(r'!|&&|\|\||\(|\)|[A-Za-z0-9_]+', expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def unary():
        t = take()
        if t == '!':
            return not unary()
        if t == '(':
            v = disj()
            if take() != ')':
                raise ValueError(f'bad !#if expression: {expr}')
            return v
        return t in true_tokens

    def conj():
        v = unary()
        while peek() == '&&':
            take()
            v = unary() and v
        return v

    def disj():
        v = conj()
        while peek() == '||':
            take()
            v = conj() or v
        return v

    value = disj()
    if peek() is not None:
        raise ValueError(f'bad !#if expression: {expr}')
    return value


def preprocess(text, base_url, fetch=_fetch, platform='android'):
    """Evaluates !#if/!#else/!#endif and inlines same-origin !#include files
    (themselves preprocessed). adblock-rust treats these lines as comments."""
    true_tokens = _tokens(platform)
    out = []
    stack = []  # (taking, parent_taking)
    taking = True
    base = urllib.parse.urlsplit(base_url)
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('!#if '):
            stack.append((taking, taking))
            taking = taking and _eval(s[5:], true_tokens)
        elif s == '!#else':
            if not stack:
                raise ValueError('!#else without !#if')
            parent = stack[-1][1]
            taking = parent and not taking
        elif s == '!#endif':
            if not stack:
                raise ValueError('!#endif without !#if')
            taking = stack.pop()[0]
        elif not taking:
            continue
        elif s.startswith('!#include '):
            url = urllib.parse.urljoin(base_url, s[10:].strip())
            u = urllib.parse.urlsplit(url)
            if (u.scheme, u.netloc) != (base.scheme, base.netloc):
                raise ValueError(f'cross-origin !#include refused: {url}')
            out.append(preprocess(fetch(url), url, fetch, platform))
        else:
            out.append(line)
    return '\n'.join(out) + '\n'


# --- the zip and its index -------------------------------------------------

def _entry(name):
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def make_zip(lists, resources, created, ubo_tag, platform='android'):
    """The bundle's bytes; the same inputs always give the same bytes. The
    platform is in the signed manifest, so one platform's bundle never stands
    in for the other's (both are signed with the same key)."""
    _tokens(platform)
    resources_json = json.dumps(resources, separators=(',', ':'), sort_keys=True).encode()
    manifest = {
        'format': FORMAT,
        'created': created,
        'platform': platform,
        'ubo_tag': ubo_tag,
        'lists': [{'name': l.name, 'url': l.url, 'permission': l.permission,
                   'sha256': hashlib.sha256(l.text.encode()).hexdigest()} for l in lists],
        'resources_sha256': hashlib.sha256(resources_json).hexdigest(),
        'licences': 'uBlock Origin lists, scriptlets and resources: GPL-3.0 '
                    '(https://github.com/uBlockOrigin/uAssets, https://github.com/gorhill/uBlock); '
                    'EasyList and EasyPrivacy: GPL-3.0 / CC BY-SA 3.0 (https://easylist.to); '
                    'IndianList: GPL-3.0 / CC BY-SA 3.0 (https://easylist.to).',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(_entry('manifest.json'), json.dumps(manifest, indent=1, sort_keys=True))
        z.writestr(_entry('resources.json'), resources_json)
        for l in lists:
            z.writestr(_entry(f'lists/{l.name}.txt'), l.text)
    return buf.getvalue()


def manifest_of(data):
    return json.loads(zipfile.ZipFile(io.BytesIO(data)).read('manifest.json'))


def make_index(data, file_name, secret):
    return {
        'format': FORMAT,
        'file': file_name,
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'created': manifest_of(data)['created'],
        'sig': base64.b64encode(ed25519.sign(secret, data)).decode(),
    }


def check(data, index, public):
    """None when the zip matches its index and signature, else the reason."""
    if index.get('format') != FORMAT:
        return f'unknown format {index.get("format")}'
    if index.get('size', 0) > MAX_SIZE or len(data) > MAX_SIZE:
        return 'over 16 MB'
    if len(data) != index['size']:
        return 'size differs from the index'
    if hashlib.sha256(data).hexdigest() != index['sha256']:
        return 'sha256 differs from the index'
    if not ed25519.verify(public, data, base64.b64decode(index['sig'])):
        return 'bad signature'
    if manifest_of(data).get('created') != index.get('created'):
        return 'manifest date differs from the index'
    return None


# --- building from the publishers ------------------------------------------

UBO_PIN = HERE / 'ubo.json'


def _fetch_bytes(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def _ubo_url(tag):
    return f'https://codeload.github.com/gorhill/uBlock/tar.gz/refs/tags/{tag}'


def ubo_pin():
    """The uBlock Origin release bundling uses: {'tag', 'sha256'}."""
    return json.loads(UBO_PIN.read_text())


def pin_ubo(tag, fetch=_fetch_bytes):
    """ubo.json for a new release, after reading its code."""
    return {'tag': tag, 'sha256': hashlib.sha256(fetch(_ubo_url(tag))).hexdigest()}


def _ubo_source(pin, dest, fetch=_fetch_bytes):
    """The pinned release unpacked in dest; a tarball with any other sha256 is
    refused before anything is unpacked."""
    data = fetch(_ubo_url(pin['tag']))
    got = hashlib.sha256(data).hexdigest()
    if got != pin['sha256']:
        raise ValueError(f"uBlock Origin {pin['tag']}: sha256 {got} is not the pinned {pin['sha256']}")
    tarfile.open(fileobj=io.BytesIO(data), mode='r:gz').extractall(dest, filter='data')
    return next(pathlib.Path(dest).glob('uBlock-*'))


def fetch_lists(assets, platform='android'):
    lists = []
    for name, permission in LISTS:
        entry = assets.get(name)
        if name == 'IND-0' and not entry:
            url = INDIANLIST
        else:
            urls = entry['contentURL']
            urls = [urls] if isinstance(urls, str) else urls
            url = next(u for u in urls if u.startswith('https://'))
        text = preprocess(_fetch(url), url, platform=platform)
        if len(text) < 1000:
            raise ValueError(f'{name} is suspiciously short ({len(text)} bytes)')
        lists.append(List(name, url, permission, text))
    return lists


# A bundle's name counts minutes from here: never reused (a published zip is
# cached for a year), and still lists-<8 digits>.zip, the only shape installed
# Tarks accept (ValidBundleFileName), for about 190 years.
NAME_EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def bundle_file_name(now):
    minutes = int((now - NAME_EPOCH).total_seconds() // 60)
    if not 0 <= minutes < 10 ** 8:
        raise ValueError(f'{now} is outside the bundle names\' range')
    return f'lists-{minutes:08d}.zip'


def build(out_dir, listtool=None, platform='android'):
    _tokens(platform)
    pin = ubo_pin()
    listtool = listtool or str(HERE / 'listtool' / 'target' / 'release' / 'listtool')
    with tempfile.TemporaryDirectory() as tmp:
        ubo = _ubo_source(pin, tmp)
        assets = json.loads((ubo / 'assets' / 'assets.json').read_text())
        lists = fetch_lists(assets, platform)
        redirects = pathlib.Path(tmp) / 'redirects.json'
        subprocess.run([listtool, 'resources', '--ubo', str(ubo), '--out', str(redirects)], check=True)
        scriptlets = subprocess.run(['node', str(HERE / 'scriptlets.mjs'), str(ubo)], check=True,
                                    capture_output=True, text=True).stdout
        resources = json.loads(redirects.read_text()) + json.loads(scriptlets)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    created = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    data = make_zip(lists, resources, created, pin['tag'], platform=platform)
    path = pathlib.Path(out_dir) / bundle_file_name(now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _read_key(arg):
    p = pathlib.Path(arg)
    text = p.read_text() if p.is_file() else arg
    return bytes.fromhex(text.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--out', required=True)
    b.add_argument('--listtool')
    b.add_argument('--platform', choices=sorted(PLATFORM_TOKENS), default='android')
    s = sub.add_parser('sign')
    s.add_argument('zip')
    s.add_argument('--key', required=True)
    v = sub.add_parser('verify')
    v.add_argument('zip')
    v.add_argument('index')
    v.add_argument('--pubkey', required=True)
    u = sub.add_parser('pin-ubo')
    u.add_argument('tag')
    k = sub.add_parser('keygen')
    k.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    if args.cmd == 'build':
        print(build(args.out, args.listtool, args.platform))
    elif args.cmd == 'pin-ubo':
        print(json.dumps(pin_ubo(args.tag), indent=1))
    elif args.cmd == 'sign':
        z = pathlib.Path(args.zip)
        index = make_index(z.read_bytes(), z.name, _read_key(args.key))
        (z.parent / 'latest.json').write_text(json.dumps(index, indent=1) + '\n')
    elif args.cmd == 'verify':
        index = json.loads(pathlib.Path(args.index).read_text())
        reason = check(pathlib.Path(args.zip).read_bytes(), index, _read_key(args.pubkey))
        if reason:
            print(f'refused: {reason}', file=sys.stderr)
            return 1
    elif args.cmd == 'keygen':
        out = pathlib.Path(args.out)
        if out.exists():
            print(f'{out} exists; not overwriting a signing key', file=sys.stderr)
            return 1
        secret = os.urandom(32)
        out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secret.hex() + '\n')
        print(ed25519.secret_to_public(secret).hex())
    return 0


if __name__ == '__main__':
    sys.exit(main())

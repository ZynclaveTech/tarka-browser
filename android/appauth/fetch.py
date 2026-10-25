#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Places AppAuth for Android's library sources in third_party/appauth/src
(Sign in with Zynclave, spec §5.2).

    python3 android/appauth/fetch.py SRC [--cache DIR]

android/patches/appauth-library.patch adds third_party/appauth's BUILD.gn
and README.chromium; this puts the sources they name in place: only
library/java/net/openid/appauth/** and LICENSE from the 0.11.1 tag's
archive, which is checked against the sha256 pinned here first. No sample
app, tests or Gradle files reach the tree. Runs after domain substitution,
which never sees these files.
"""

import argparse
import hashlib
import io
import pathlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request

VERSION = '0.11.1'
URL = f'https://github.com/openid/AppAuth-Android/archive/refs/tags/{VERSION}.tar.gz'
SHA256 = '77cb76cbbf9d88bf62eb1b265c54a321a887a26454280c92ddef8937dcb9097e'
PREFIX = f'AppAuth-Android-{VERSION}/'
KEEP = ('library/java/net/openid/appauth/', 'LICENSE')
DEST = 'third_party/appauth/src'


def download(cache):
    path = pathlib.Path(cache) / f'AppAuth-Android-{VERSION}.tar.gz'
    if not path.is_file():
        req = urllib.request.Request(URL, headers={'User-Agent': 'Tark-build/1 (+https://gettarka.com)'})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.read())
    return path.read_bytes()


def wanted(name):
    """The archive member's path under src/, or None to leave it out."""
    if not name.startswith(PREFIX):
        return None
    rel = name[len(PREFIX):]
    if rel == KEEP[1] or (rel.startswith(KEEP[0]) and rel.endswith('.java')):
        return rel
    return None


def place(src, data):
    """Checks the archive and unpacks the kept files into SRC/third_party/
    appauth/src, replacing what was there. Raises ValueError on a checksum
    mismatch, before anything is written."""
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError(f'AppAuth {VERSION}: sha256 is not the pinned one')
    dest = pathlib.Path(src) / DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
            members = [m for m in tar.getmembers() if m.isfile() and wanted(m.name)]
            for m in members:
                m.name = wanted(m.name)
            tar.extractall(pathlib.Path(tmp) / 'src', members=members, filter='data')
            count = len(members)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(pathlib.Path(tmp) / 'src'), dest)
    return count


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('src')
    ap.add_argument('--cache', default=str(pathlib.Path(__file__).resolve().parents[2] / 'build' / 'appauth'))
    args = ap.parse_args(argv)
    try:
        count = place(args.src, download(args.cache))
    except ValueError as e:
        print(f'fetch.py: {e}', file=sys.stderr)
        return 1
    print(f'appauth {VERSION}: {count} files')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The ad blocker's built-in list bundle, for the Mac and Windows builds.

    adblock_lists.py DEST [--lists-dir DIR] [--pubkey FILE]

Fetches gettarka.com/lists/desktop/v1/latest.json and the bundle it names (or
takes both from DIR, as TARK_LISTS_DIR does for android/build.sh), checks the
bundle against its index and Tark's list-signing key
(android/adblock/bundle.py check), and only then writes it to DEST
(chrome/browser/tark_adblock/lists.zip). Anything that does not check stops
the build: an app is never built without lists or with unsigned ones.
"""

import argparse
import json
import pathlib
import re
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ADBLOCK = HERE.parent / 'android' / 'adblock'
sys.path.insert(0, str(ADBLOCK))
import bundle  # noqa: E402

LISTS_BASE = 'https://gettarka.com/lists/desktop/v1/'
BUNDLE_NAME = re.compile(r'lists-[0-9]{8}\.zip')


def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': bundle.USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(bundle.MAX_SIZE + 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('dest')
    ap.add_argument('--lists-dir')
    ap.add_argument('--pubkey', default=str(ADBLOCK / 'lists_pubkey.txt'))
    args = ap.parse_args(argv)

    def read(name):
        if args.lists_dir:
            return (pathlib.Path(args.lists_dir) / name).read_bytes()
        return _fetch(LISTS_BASE + name)

    try:
        index = json.loads(read('latest.json'))
        name = index.get('file', '')
        if not BUNDLE_NAME.fullmatch(name):
            raise ValueError(f'bad bundle name {name!r}')
        data = read(name)
    except (OSError, ValueError) as e:
        print(f'adblock_lists: {e}', file=sys.stderr)
        return 1
    public = bytes.fromhex(pathlib.Path(args.pubkey).read_text().strip())
    reason = bundle.check(data, index, public)
    if reason:
        print(f'adblock_lists: refused {name}: {reason}', file=sys.stderr)
        return 1
    dest = pathlib.Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f'adblock_lists: {name} ({len(data)} bytes, {index["created"]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())

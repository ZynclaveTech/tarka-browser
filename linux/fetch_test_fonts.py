#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Chromium's test fonts for Tark's unit tests on Linux (L2).

    python3 linux/fetch_test_fonts.py SRC

The unit test programs need third_party/test_fonts/test_fonts, a GCS
dependency the lite source tarball leaves out. This reads its bucket, object
and sha256 from SRC/DEPS, downloads it (TARK_GCS_BASE stands in for
https://storage.googleapis.com in tests), refuses any other content, and
unpacks it. Nothing to do when the fonts are there.
"""

import hashlib
import io
import os
import pathlib
import re
import sys
import tarfile
import urllib.request

DEP = 'src/third_party/test_fonts/test_fonts'


def pin(deps_text):
    # The first of each field after the entry's name is the entry's own.
    block = deps_text[deps_text.index(f"'{DEP}'"):]
    field = lambda name: re.search(rf"'{name}': '([^']+)'", block).group(1)
    return field('bucket'), field('object_name'), field('sha256sum')


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: fetch_test_fonts.py SRC')
    src = pathlib.Path(sys.argv[1])
    dest = src / 'third_party' / 'test_fonts' / 'test_fonts'
    if (dest / 'Ahem.ttf').is_file():
        print('test fonts: already there')
        return
    bucket, name, sha256 = pin((src / 'DEPS').read_text(encoding='utf-8'))
    base = os.environ.get('TARK_GCS_BASE', 'https://storage.googleapis.com')
    with urllib.request.urlopen(f'{base}/{bucket}/{name}') as response:
        data = response.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        sys.exit(f'test fonts: sha256 {got}, DEPS pins {sha256}')
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        archive.extractall(dest, filter='data')
    print(f'test fonts: {name} into {dest}')


if __name__ == '__main__':
    main()

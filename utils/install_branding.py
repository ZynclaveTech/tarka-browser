#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Copy Tark's generated brand files over Chromium's (spec 6.3).

    python3 utils/install_branding.py resources/branding/mark build/src

Each line of <mark dir>/install.txt names a file Chromium ships; the
replacement is <mark dir>/tree/<that path>. A destination that does not
exist fails the install: a Chromium update moved or renamed the file, and
Tark would otherwise ship the old logo without noticing.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mark  # noqa: E402


class MissingDestination(Exception):
    pass


def install(mark_dir, tree):
    entries = mark.read_manifest(os.path.join(mark_dir, 'install.txt'))
    missing = [e.dest for e in entries if not os.path.isfile(os.path.join(tree, e.dest))]
    if missing:
        raise MissingDestination('not in the tree (moved upstream?): ' + ', '.join(missing))
    for entry in entries:
        shutil.copyfile(os.path.join(mark_dir, 'tree', entry.dest), os.path.join(tree, entry.dest))
    return len(entries)


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: install_branding.py MARK_DIR TREE')
    count = install(sys.argv[1], sys.argv[2])
    print('installed %d brand files' % count)


if __name__ == '__main__':
    main()

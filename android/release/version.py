#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark for Android's release identity (A5).

    version.py REPO        prints "<version name> <version code>"

The version name is the Chromium version and Tark's revision of it
("155.0.8059.39-r1"). The version code is BUILD * 100000 + PATCH * 100 +
revision (805903901): a later Chromium is always higher, and Tark's own
revisions of one Chromium (android/release.json, 1-99) count up within it.
Play and the direct APK's update check both compare it.
"""

import json
import pathlib
import sys


def _parts(chromium, revision):
    major, minor, build, patch = (int(p) for p in chromium.split('.'))
    if not 1 <= revision <= 99:
        raise ValueError(f'revision {revision} is outside 1-99')
    if not 0 <= patch <= 999:
        raise ValueError(f'patch {patch} is outside 0-999')
    return build, patch


def version_code(chromium, revision):
    build, patch = _parts(chromium, revision)
    return build * 100000 + patch * 100 + revision


def version_name(chromium, revision):
    _parts(chromium, revision)
    return f'{chromium}-r{revision}'


def from_repo(repo):
    repo = pathlib.Path(repo)
    chromium = (repo / 'ungoogled-chromium' / 'chromium_version.txt').read_text().strip()
    revision = json.loads((repo / 'android' / 'release.json').read_text())['revision']
    return version_name(chromium, revision), version_code(chromium, revision)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    print(*from_repo(sys.argv[1]))

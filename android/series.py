#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's patch series for the Android build (A1).

    python3 android/series.py REPO OUT

OUT gets the tarka/ entries of REPO/patches/series, in order, minus
android/desktop-only-patches.txt (an entry ending in "/" is a whole folder),
then android/patches/series (Android-only
patches, as android/...). android/build.sh applies
ungoogled-chromium's own series from the submodule first, then this one.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def entries(path):
    return [l.strip() for l in path.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


def desktop_only(entry, skip):
    """Whether a series entry is left out: listed itself, or under a folder
    listed with a trailing slash (tarka/captions/)."""
    return entry in skip or any(s.endswith('/') and entry.startswith(s) for s in skip)


def series(repo):
    skip = set(entries(HERE / 'desktop-only-patches.txt'))
    shared = [e for e in entries(pathlib.Path(repo) / 'patches' / 'series')
              if e.startswith('tarka/') and not desktop_only(e, skip)]
    # Android-only patches (android/patches/), last.
    return shared + ['android/' + e for e in entries(HERE / 'patches' / 'series')]


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: series.py REPO OUT')
    out = pathlib.Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(series(sys.argv[1])) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

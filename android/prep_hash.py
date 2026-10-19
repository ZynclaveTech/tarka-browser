#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The hash of everything that shapes a prepared Android tree (A1).

    python3 android/prep_hash.py REPO

android/build.sh stamps a prepared tree (cloned, patched, substituted, Tark's
steps done) with this; a matching stamp skips straight to gn and ninja, a
different one means the tree is wiped and prepared again.
"""

import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import series  # noqa: E402

INPUTS = [
    'android/build.sh', 'android/gclient.android', 'android/desktop-only-patches.txt',
    'android/series.py', 'android/drop_gn_args_hunk.py',
    'ungoogled-chromium/chromium_version.txt', 'ungoogled-chromium/patches/series',
    'ungoogled-chromium/pruning.list', 'ungoogled-chromium/domain_substitution.list',
    'ungoogled-chromium/domain_regex.list', 'ungoogled-chromium/utils/clone.py',
    'ungoogled-chromium/utils/depot_tools.patch',
    'utils/name_substitution.py', 'utils/name_substitution_utils.py',
    'utils/domain_substitution_skip.txt', 'utils/filter_substitution_list.py',
    'utils/install_branding.py', 'utils/install_xlit.sh', 'downloads-xlit.ini',
]
GLOBS = ['resources/branding/mark/*', 'resources/fonts/inter-latin*.woff2', 'resources/xlit/**/*',
         'ungoogled-chromium/patches/**/*.patch']


def prep_hash(repo):
    repo = pathlib.Path(repo)
    files = [repo / f for f in INPUTS]
    for pattern in GLOBS:
        files += sorted(p for p in repo.glob(pattern) if p.is_file())
    files += [repo / 'patches' / e for e in series.series(repo)]
    h = hashlib.sha256()
    for f in files:
        h.update(str(f.relative_to(repo)).encode() + b'\0')
        h.update(f.read_bytes() if f.exists() else b'(missing)')
        h.update(b'\0')
    return h.hexdigest()


if __name__ == '__main__':
    print(prep_hash(sys.argv[1]))

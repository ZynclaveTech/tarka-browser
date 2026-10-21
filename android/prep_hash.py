#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The hash of everything that shapes a prepared Android tree (A1).

    python3 android/prep_hash.py [--base] REPO

android/build.sh stamps a prepared tree (cloned, patched, substituted, Tark's
steps done) with this; a matching stamp skips straight to gn and ninja.

--base: the hash of the base alone (Chromium with Android's dependencies, the
toolchains, ungoogled-chromium's core patches), which build.sh keeps as a
copy. A different base means the tree is wiped and prepared again; the same
base with a different hash means only Tark's layer is applied again
(android/layers.py).
"""

import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import series  # noqa: E402

BASE_INPUTS = [
    'android/gclient.android', 'android/drop_gn_args_hunk.py',
    'ungoogled-chromium/chromium_version.txt', 'ungoogled-chromium/patches/series',
    'ungoogled-chromium/utils/clone.py', 'ungoogled-chromium/utils/depot_tools.patch',
    'ungoogled-chromium/utils/patches.py',
]
BASE_GLOBS = ['ungoogled-chromium/patches/**/*.patch']
INPUTS = BASE_INPUTS + [
    'android/desktop-only-patches.txt', 'android/series.py', 'android/patches/series',
    'android/layers.py', 'ungoogled-chromium/pruning.list',
    'ungoogled-chromium/domain_substitution.list', 'ungoogled-chromium/domain_regex.list',
    'utils/name_substitution.py', 'utils/name_substitution_utils.py',
    'utils/domain_substitution_skip.txt', 'utils/filter_substitution_list.py',
    'utils/install_branding.py', 'utils/install_xlit.sh', 'downloads-xlit.ini',
    'downloads-tark.ini', 'utils/ublock_key.py', 'resources/ublock/key.txt',
    'android/adblock/crates.py', 'android/xlit/files.py',
]
GLOBS = BASE_GLOBS + ['resources/branding/mark/*', 'resources/fonts/inter-latin*.woff2',
                      'resources/xlit/**/*']


def prep_section(build_sh):
    """android/build.sh up to its '# --- end prepare ---' marker: the setup
    and the preparation. Editing how gn and ninja run must not force an hour
    of re-preparation. Both markers must be there (ValueError otherwise)."""
    build_sh.index('# --- prepare ---')
    return build_sh[:build_sh.index('# --- end prepare ---')]


def base_section(build_sh):
    """android/build.sh up to its '# --- end base ---' marker: the setup and
    the base's preparation, which Tark's layer comes after."""
    build_sh.index('# --- prepare ---')
    return build_sh[:build_sh.index('# --- end base ---')]


def _hash(repo, section, files):
    h = hashlib.sha256()
    h.update(section.encode() + b'\0')
    for f in files:
        h.update(str(f.relative_to(repo)).encode() + b'\0')
        h.update(f.read_bytes() if f.exists() else b'(missing)')
        h.update(b'\0')
    return h.hexdigest()


def _files(repo, inputs, globs):
    files = [repo / f for f in inputs]
    for pattern in globs:
        files += sorted(p for p in repo.glob(pattern) if p.is_file())
    return files


def base_hash(repo):
    repo = pathlib.Path(repo)
    return _hash(repo, base_section((repo / 'android' / 'build.sh').read_text()),
                 _files(repo, BASE_INPUTS, BASE_GLOBS))


def prep_hash(repo):
    repo = pathlib.Path(repo)
    files = _files(repo, INPUTS, GLOBS)
    files += [repo / ('android/patches/' + e[len('android/'):] if e.startswith('android/') else 'patches/' + e)
              for e in series.series(repo)]
    return _hash(repo, prep_section((repo / 'android' / 'build.sh').read_text()), files)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--base':
        print(base_hash(sys.argv[2]))
    elif len(sys.argv) == 2:
        print(prep_hash(sys.argv[1]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

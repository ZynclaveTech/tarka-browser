#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Assemble the folder upstream's Windows build.py runs in (W1).

    python3 windows/prepare_workdir.py REPO WORKDIR

WORKDIR gets upstream ungoogled-chromium-windows's files (windows/upstream,
with Tark's one hook in build.py), the shared ungoogled-chromium core (this
repo's submodule), Tark's patches after the Windows platform patches in one
series (minus windows/mac-only-patches.txt), Tark's filtered domain
substitution list, and windows/tark_post_patch.py. WORKDIR/build (the source
tree and download cache) is kept, so a re-run can build incrementally.
"""

import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'utils'))
import filter_substitution_list  # noqa: E402


def entries(path):
    return [l.strip() for l in path.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


def copy_tree(src, dst, ignore=None):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def prepare(repo, work):
    upstream = repo / 'windows' / 'upstream'
    work.mkdir(parents=True, exist_ok=True)
    for item in upstream.iterdir():
        if item.name == 'UPSTREAM_COMMIT':
            continue
        if item.is_dir():
            copy_tree(item, work / item.name)
        else:
            shutil.copy2(item, work / item.name)
    copy_tree(repo / 'ungoogled-chromium', work / 'ungoogled-chromium',
              ignore=shutil.ignore_patterns('.git'))
    copy_tree(repo / 'patches' / 'tarka', work / 'patches' / 'tarka')

    mac_only = set(entries(HERE / 'mac-only-patches.txt'))
    tark = [e for e in entries(repo / 'patches' / 'series')
            if e.startswith('tarka/') and e not in mac_only]
    series = entries(upstream / 'patches' / 'series') + tark
    (work / 'patches' / 'series').write_text('\n'.join(series) + '\n', encoding='utf-8')

    # build.py --tarball reads ungoogled-chromium's list, a clone build the
    # top-level one: filter both the same way.
    skip = set(entries(repo / 'utils' / 'domain_substitution_skip.txt'))
    core_list = work / 'ungoogled-chromium' / 'domain_substitution.list'
    kept = filter_substitution_list.filter_list(core_list.read_text(encoding='utf-8').splitlines(), skip)
    text = '\n'.join(kept) + '\n'
    core_list.write_text(text, encoding='utf-8')
    (work / 'domain_substitution.list').write_text(text, encoding='utf-8')

    # The targets ninja builds first (W2), so a compile error in Tark's code
    # shows within the first CI stage.
    (work / 'tark_ninja_first.txt').write_text(
        '\n'.join(entries(HERE / 'ninja-first.txt')) + '\n', encoding='utf-8')

    shutil.copy2(HERE / 'tark_post_patch.py', work / 'tark_post_patch.py')
    (work / 'tark_repo.txt').write_text(str(repo) + '\n', encoding='utf-8')
    return len(series), len(tark)


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: prepare_workdir.py REPO WORKDIR')
    total, tark = prepare(pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve())
    print(f'workdir ready: {total} patches in the Windows series, {tark} of them Tark\'s')


if __name__ == '__main__':
    main()

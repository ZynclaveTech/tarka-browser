#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's steps after patching, for the Linux build (L1).

    python3 tark_post_patch.py SOURCE_TREE

Run by the hook in upstream's scripts/build.sh (after patches and domain
substitution, before gn gen), from the workdir linux/prepare_workdir.py
made; the repo is named in tark_repo.txt next to this file. The steps every
non-Mac desktop build shares before its own (utils/tark_post_patch_common.py);
then ONNX Runtime (live captions, L2) and the captions' credits.
"""

import os
import pathlib
import sys

WORK = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path((WORK / 'tark_repo.txt').read_text(encoding='utf-8').strip())
CORE = WORK / 'ungoogled-chromium'
CACHE = WORK / 'build' / 'download_cache'
sys.path.insert(0, str(REPO / 'utils'))
import tark_post_patch_common as common  # noqa: E402
run = common.run

BASH = os.environ.get('TARK_BASH', 'bash')


def install_onnxruntime(src):
    """Microsoft's ONNX Runtime release (linux/downloads-onnxruntime.ini,
    pinned by sha256) into SRC/third_party/tark_onnxruntime, as dev.sh does
    on the Mac: components/tark_captions builds against its headers."""
    if (src / 'third_party' / 'tark_onnxruntime' / 'include' / 'onnxruntime_c_api.h').is_file():
        return
    ini = REPO / 'linux' / 'downloads-onnxruntime.ini'
    downloads = CORE / 'utils' / 'downloads.py'
    run(sys.executable, downloads, 'retrieve', '-i', ini, '-c', CACHE)
    run(sys.executable, downloads, 'unpack', '-i', ini, '-c', CACHE, src)


def write_revision(src):
    """Tark's revision (revision.txt) for the update notice, which compares it
    with gettarka.com/linux/latest.json (chrome/browser/tark_updater)."""
    revision = (REPO / 'revision.txt').read_text(encoding='utf-8').strip()
    if not revision.isdigit():
        sys.exit(f"tark: revision.txt holds '{revision}', not a number")
    header = src / 'chrome' / 'browser' / 'tark_updater' / 'tark_revision.h'
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(
        '// Written by linux/tark_post_patch.py from revision.txt.\n'
        '#ifndef CHROME_BROWSER_TARK_UPDATER_TARK_REVISION_H_\n'
        '#define CHROME_BROWSER_TARK_UPDATER_TARK_REVISION_H_\n\n'
        f'#define TARK_REVISION "{revision}"\n\n'
        '#endif  // CHROME_BROWSER_TARK_UPDATER_TARK_REVISION_H_\n', encoding='utf-8')


def main_for(src):
    common.before_platform(REPO, CORE, CACHE, WORK, src, BASH)
    install_onnxruntime(src)
    write_revision(src)
    common.after_platform(REPO, CORE, CACHE, src, BASH)
    print('tark: post-patch steps done', flush=True)


def main():
    args = sys.argv[1:]
    if args[:1] == ['--onnxruntime-only'] and len(args) == 2:
        install_onnxruntime(pathlib.Path(args[1]).resolve())
        return
    if len(args) != 1:
        sys.exit('usage: tark_post_patch.py [--onnxruntime-only] SOURCE_TREE')
    main_for(pathlib.Path(args[0]).resolve())


if __name__ == '__main__':
    main()

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
then ONNX Runtime's headers; the captions' credits join them in L2.
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
    ini = REPO / 'linux' / 'downloads-onnxruntime.ini'
    downloads = CORE / 'utils' / 'downloads.py'
    run(sys.executable, downloads, 'retrieve', '-i', ini, '-c', CACHE)
    run(sys.executable, downloads, 'unpack', '-i', ini, '-c', CACHE, src)


def main_for(src):
    common.before_platform(REPO, CORE, CACHE, WORK, src, BASH)
    install_onnxruntime(src)
    # No common.after_platform yet: the captions' credits describe ONNX
    # Runtime and the models, which Linux gets with live captions (L2).
    print('tark: post-patch steps done', flush=True)


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: tark_post_patch.py SOURCE_TREE')
    main_for(pathlib.Path(sys.argv[1]).resolve())


if __name__ == '__main__':
    main()

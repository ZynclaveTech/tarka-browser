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
ONNX Runtime and the captions' credits join them in L2.
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


def main_for(src):
    common.before_platform(REPO, CORE, CACHE, WORK, src, BASH)
    # No common.after_platform yet: the captions' credits describe ONNX
    # Runtime and the models, which Linux gets with live captions (L2).
    print('tark: post-patch steps done', flush=True)


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: tark_post_patch.py SOURCE_TREE')
    main_for(pathlib.Path(sys.argv[1]).resolve())


if __name__ == '__main__':
    main()

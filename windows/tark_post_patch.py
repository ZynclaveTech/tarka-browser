#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's steps after patching, for the Windows build (W1).

    python tark_post_patch.py SOURCE_TREE

Run by the hook in upstream's build.py (after patches and domain
substitution, before gn gen), from the workdir prepare_workdir.py made; the
repo is named in tark_repo.txt next to this file. The same steps as Tark's
macOS build.sh, minus the Mac-only ones (app.icns, Sparkle): name
substitution, the mark, Inter for WebUI, the ad blocker's crates and lists,
IndicXlit for the address bar (D1), and ONNX Runtime and the credits for
live captions (D4, W2).
"""

import os
import pathlib
import shutil
import sys

WORK = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path((WORK / 'tark_repo.txt').read_text(encoding='utf-8').strip())
CORE = WORK / 'ungoogled-chromium'
CACHE = WORK / 'build' / 'download_cache'
sys.path.insert(0, str(REPO / 'utils'))
import tark_post_patch_common as common  # noqa: E402
run = common.run

BASH = os.environ.get('TARK_BASH', r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt' else 'bash')


def install_onnxruntime(ort_dir, src):
    """ORT_DIR (include/, lib/onnxruntime.dll, LICENSE, ThirdPartyNotices.txt,
    VERSION_NUMBER) into SRC/third_party/tark_onnxruntime, where
    components/tark_captions finds the headers and GN copies the DLL from."""
    needed = ['include/onnxruntime_c_api.h', 'lib/onnxruntime.dll', 'LICENSE',
              'ThirdPartyNotices.txt', 'VERSION_NUMBER']
    if str(ort_dir) in ('', '.') or not ort_dir.is_dir():
        sys.exit('tark: TARK_ORT_DIR must name ONNX Runtime built by windows/ci/build_onnxruntime.ps1')
    missing = [n for n in needed if not (ort_dir / n).is_file()]
    if missing:
        sys.exit(f'tark: {ort_dir} lacks {missing}')
    version = (ort_dir / 'VERSION_NUMBER').read_text(encoding='utf-8').strip()
    if version != '1.31.0':
        sys.exit(f"tark: ONNX Runtime {version}, expected 1.31.0 (the Mac's version)")
    out = src / 'third_party' / 'tark_onnxruntime'
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ort_dir / 'include', out / 'include')
    (out / 'lib').mkdir(parents=True)
    shutil.copy2(ort_dir / 'lib' / 'onnxruntime.dll', out / 'lib' / 'onnxruntime.dll')
    for name in ('LICENSE', 'ThirdPartyNotices.txt', 'VERSION_NUMBER'):
        shutil.copy2(ort_dir / name, out / name)
    print(f'tark: ONNX Runtime {version} from {ort_dir}', flush=True)


def install_winsparkle(ws_dir, src):
    """WS_DIR (WinSparkle.dll, include/, COPYING, VERSION, from
    windows/ci/build_winsparkle.ps1) into SRC/third_party/tark_winsparkle,
    where GN copies the DLL from; its credits and those of what it links
    (resources/updater/credits); and Tark's revision, which the updater
    compares with the feed (chrome/browser/tark_updater/tark_revision.h)."""
    needed = ['WinSparkle.dll', 'include/winsparkle.h', 'COPYING', 'VERSION']
    if str(ws_dir) in ('', '.') or not ws_dir.is_dir():
        sys.exit('tark: TARK_WINSPARKLE_DIR must name WinSparkle built by windows/ci/build_winsparkle.ps1')
    missing = [n for n in needed if not (ws_dir / n).is_file()]
    if missing:
        sys.exit(f'tark: {ws_dir} lacks {missing}')
    version = (ws_dir / 'VERSION').read_text(encoding='utf-8').strip()
    if version != '0.9.4':
        sys.exit(f'tark: WinSparkle {version}, expected 0.9.4')
    out = src / 'third_party' / 'tark_winsparkle'
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ws_dir / 'include', out / 'include')
    shutil.copy2(ws_dir / 'WinSparkle.dll', out / 'WinSparkle.dll')
    # about:credits: tools/licenses reads a README.chromium and its LICENSE in
    # each third_party folder.
    credits = REPO / 'resources' / 'updater' / 'credits'
    for name in ('winsparkle', 'wxwidgets', 'expat', 'ed25519'):
        folder = out if name == 'winsparkle' else src / 'third_party' / f'tark_winsparkle_{name}'
        folder.mkdir(parents=True, exist_ok=True)
        for f in ('README.chromium', 'LICENSE'):
            shutil.copy2(credits / name / f, folder / f)
    revision = (REPO / 'revision.txt').read_text(encoding='utf-8').strip()
    if not revision.isdigit():
        sys.exit(f"tark: revision.txt holds '{revision}', not a number")
    header = src / 'chrome' / 'browser' / 'tark_updater' / 'tark_revision.h'
    header.write_text(
        '// Written by windows/tark_post_patch.py from revision.txt.\n'
        '#ifndef CHROME_BROWSER_TARK_UPDATER_TARK_REVISION_H_\n'
        '#define CHROME_BROWSER_TARK_UPDATER_TARK_REVISION_H_\n\n'
        f'#define TARK_REVISION "{revision}"\n\n'
        '#endif  // CHROME_BROWSER_TARK_UPDATER_TARK_REVISION_H_\n', encoding='utf-8')
    print(f'tark: WinSparkle {version} from {ws_dir}; revision {revision}', flush=True)


def main_for(src):
    common.before_platform(REPO, CORE, CACHE, WORK, src, BASH)
    # Live captions (W2): ONNX Runtime built from source with the static C
    # runtime (TARK_ORT_DIR, from windows/ci/build_onnxruntime.ps1).
    install_onnxruntime(pathlib.Path(os.environ.get('TARK_ORT_DIR', '')), src)
    # The updater (W2): WinSparkle built without OpenSSL
    # (TARK_WINSPARKLE_DIR, from windows/ci/build_winsparkle.ps1).
    install_winsparkle(pathlib.Path(os.environ.get('TARK_WINSPARKLE_DIR', '')), src)
    common.after_platform(REPO, CORE, CACHE, src, BASH)
    print('tark: post-patch steps done', flush=True)


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: tark_post_patch.py SOURCE_TREE')
    main_for(pathlib.Path(sys.argv[1]).resolve())
    if os.environ.get('TARK_STOP_BEFORE_GN') == '1':
        # The patch-only job: every patch applied and Tark's steps ran; stop
        # build.py here, before gn gen and the compile.
        print('tark: stopping before gn gen (TARK_STOP_BEFORE_GN=1)', flush=True)
        sys.exit(3)


if __name__ == '__main__':
    main()

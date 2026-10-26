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
substitution, the mark, Inter for WebUI, uBlock Origin with its fixed key,
IndicXlit for the address bar (D1), and ONNX Runtime and the credits for
live captions (D4, W2).
"""

import configparser
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

WORK = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path((WORK / 'tark_repo.txt').read_text(encoding='utf-8').strip())
CORE = WORK / 'ungoogled-chromium'
CACHE = WORK / 'build' / 'download_cache'
BASH = os.environ.get('TARK_BASH', r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt' else 'bash')


def run(*args, **kwargs):
    print('tark:', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def unpack_zips(ini, src):
    """Each .zip download in INI into SRC/output_path, minus strip_leading_dirs
    (the same layout downloads.py unpack gives)."""
    parser = configparser.ConfigParser()
    parser.read(ini, encoding='utf-8')
    for name in parser.sections():
        entry = parser[name]
        archive = CACHE / entry['download_filename']
        if archive.suffix != '.zip':
            continue
        out = src / entry['output_path']
        strip = entry.get('strip_leading_dirs', '').strip('/')
        # Extract over what is there, as downloads.py does: patches applied
        # earlier add files to this folder (uBlock's BUILD.gn).
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                path = pathlib.PurePosixPath(info.filename)
                if strip:
                    if path.parts[:1] != (strip,):
                        continue
                    path = pathlib.PurePosixPath(*path.parts[1:])
                if not path.parts or '..' in path.parts or path.is_absolute():
                    continue
                target = out.joinpath(*path.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, open(target, 'wb') as sink:
                    shutil.copyfileobj(source, sink)
        print(f'tark: unpacked {name} to {out}', flush=True)


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


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: tark_post_patch.py SOURCE_TREE')
    src = pathlib.Path(sys.argv[1]).resolve()
    py = sys.executable

    # Product name in UI strings (backup kept for a reset, as on the Mac).
    run(py, REPO / 'utils' / 'name_substitution.py', '--sub', '-t', src,
        '--backup-path', WORK / 'build' / 'namesubs.tar')
    # The mark, wherever Chromium ships a logo file the manifest names.
    run(py, REPO / 'utils' / 'install_branding.py', REPO / 'resources' / 'branding' / 'mark', src)
    # Certificate trust data: CT log list, Chrome Root Store, CRLSet (resources/trust).
    run(py, REPO / 'utils' / 'trust_data.py', 'install', src,
        '--domain-regex', CORE / 'domain_regex.list')
    # Inter for WebUI pages, served as chrome://resources/fonts/.
    fonts = src / 'ui' / 'webui' / 'resources' / 'fonts'
    fonts.mkdir(parents=True, exist_ok=True)
    for woff in (REPO / 'resources' / 'fonts').glob('inter-latin*.woff2'):
        shutil.copy2(woff, fonts / woff.name)
    # uBlock Origin's sources and the key that fixes its extension id.
    ini = REPO / 'downloads-tark.ini'
    run(py, CORE / 'utils' / 'downloads.py', 'retrieve', '-i', ini, '-c', CACHE)
    # Unpacked here with Python's zipfile: ungoogled-chromium's downloads.py
    # unpacks zips on Windows through a 7-Zip pipe that breaks ("The pipe
    # has been ended"); a zip needs no 7-Zip.
    unpack_zips(ini, src)
    run(py, REPO / 'utils' / 'ublock_key.py', src / 'third_party' / 'ublock' / 'manifest.json',
        REPO / 'resources' / 'ublock' / 'key.txt')
    # IndicXlit weights and word lists (utils/install_xlit.sh, under bash).
    env = dict(os.environ, _root_dir=REPO.as_posix(), _src_dir=src.as_posix(),
               _main_repo=CORE.as_posix(), _download_cache=CACHE.as_posix())
    run(BASH, '-c', 'source "$_root_dir/utils/install_xlit.sh" && _install_xlit', env=env)
    # Live captions (W2): ONNX Runtime built from source with the static C
    # runtime (TARK_ORT_DIR, from windows/ci/build_onnxruntime.ps1), and the
    # captions' about:credits entries, as build.sh does on the Mac.
    install_onnxruntime(pathlib.Path(os.environ.get('TARK_ORT_DIR', '')), src)
    # The updater (W2): WinSparkle built without OpenSSL
    # (TARK_WINSPARKLE_DIR, from windows/ci/build_winsparkle.ps1).
    install_winsparkle(pathlib.Path(os.environ.get('TARK_WINSPARKLE_DIR', '')), src)
    run(BASH, '-c', 'source "$_root_dir/utils/install_captions_credits.sh" && _install_captions_credits',
        env=env)
    print('tark: post-patch steps done', flush=True)
    if os.environ.get('TARK_STOP_BEFORE_GN') == '1':
        # The patch-only job: every patch applied and Tark's steps ran; stop
        # build.py here, before gn gen and the compile.
        print('tark: stopping before gn gen (TARK_STOP_BEFORE_GN=1)', flush=True)
        sys.exit(3)


if __name__ == '__main__':
    main()

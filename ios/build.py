#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark for iOS from a pinned Firefox for iOS release.

    build.py fetch    clone upstream.json's tag into build/ios/firefox-ios
    build.py patch    put the tree back to the tag, apply ios/series in order
    build.py lists    the signed ad-block list bundle from gettarka.com, verified
                      and converted to WebKit rules and a serialized adblock-rust
                      engine inside the tree
    build.py engine   adblock-rust for iOS (ios/adblock) as an xcframework
                      inside the tree
    build.py sim      bootstrap and build the Fennec scheme for the simulator

The tree is never committed: Tark's changes are the patches in ios/patches,
listed in ios/series, so moving to a new Firefox release means rebasing them.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request

IOS = pathlib.Path(__file__).resolve().parent
ROOT = IOS.parent
TREE = ROOT / 'build' / 'ios' / 'firefox-ios'
DERIVED = ROOT / 'build' / 'ios' / 'dd'
LISTS_URL = 'https://gettarka.com/lists/android/v1/'
LISTS_MAX_BYTES = 64 << 20
ADBLOCK = ROOT / 'android' / 'adblock'
TARK_LISTS = TREE / 'firefox-ios' / 'Client' / 'ContentBlocker' / 'TarkLists'
ENGINE_CRATE = IOS / 'adblock'
XCFRAMEWORK = TREE / 'BrowserKit' / 'TarkAdblockFFI.xcframework'
# Device, and the Apple-silicon simulator.
IOS_TARGETS = ('aarch64-apple-ios', 'aarch64-apple-ios-sim')


def run(*args, cwd=None):
    print('+', ' '.join(str(a) for a in args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def out(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def upstream():
    return json.loads((IOS / 'upstream.json').read_text())


def fetch():
    up = upstream()
    if not TREE.exists():
        TREE.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--depth', '1', '--branch', up['tag'], up['repo'],
            TREE)
    head = out('git', 'rev-parse', 'HEAD', cwd=TREE)
    if head != up['commit']:
        sys.exit(f'{TREE} is at {head}, upstream.json pins {up["commit"]}')


def patch():
    fetch()
    run('git', 'reset', '--quiet', '--hard', upstream()['commit'], cwd=TREE)
    run('git', 'clean', '--quiet', '-fdx', cwd=TREE)
    for line in (IOS / 'series').read_text().splitlines():
        name = line.split('#', 1)[0].strip()
        if not name:
            continue
        result = subprocess.run(['git', 'apply', '--3way', '--whitespace=nowarn',
                                 IOS / 'patches' / name], cwd=TREE)
        if result.returncode:
            sys.exit(f'patch did not apply: {name}')
        print('applied', name)


def _download(url):
    with urllib.request.urlopen(url) as response:
        data = response.read(LISTS_MAX_BYTES + 1)
    if len(data) > LISTS_MAX_BYTES:
        sys.exit(f'{url} is larger than {LISTS_MAX_BYTES} bytes')
    return data


def lists():
    # The same signed bundle Tark for Android uses; listtool converts what
    # WebKit can express (network rules, hide rules, exceptions).
    work = ROOT / 'build' / 'ios' / 'lists'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    index = work / 'latest.json'
    index.write_bytes(_download(LISTS_URL + 'latest.json'))
    # The index is not trusted until the bundle verifies: its file name only
    # picks the URL, and the download goes to a fixed local name.
    name = json.loads(index.read_text())['file']
    if not re.fullmatch(r'lists-[0-9a-f]+\.zip', name):
        sys.exit(f'unexpected bundle name in latest.json: {name!r}')
    bundle = work / 'bundle.zip'
    bundle.write_bytes(_download(LISTS_URL + name))
    run(sys.executable, ADBLOCK / 'bundle.py', 'verify', bundle, index,
        '--pubkey', ADBLOCK / 'lists_pubkey.txt')
    run('cargo', 'build', '--release', '--manifest-path', ADBLOCK / 'listtool' / 'Cargo.toml')
    listtool = ADBLOCK / 'listtool' / 'target' / 'release' / 'listtool'
    run(listtool, 'webkit', bundle, work / 'webkit')
    run(listtool, 'engine', bundle, work / 'engine')
    shutil.rmtree(TARK_LISTS, ignore_errors=True)
    TARK_LISTS.mkdir(parents=True)
    for rules in sorted((work / 'webkit').glob('tark-*.json')):
        # ContentBlocker loads bundled fxcb-*.json files as extra lists.
        shutil.copy(rules, TARK_LISTS / f'fxcb-{rules.name}')
        print('list', TARK_LISTS / f'fxcb-{rules.name}')
    # For element hiding and scriptlets in the app (TarkCosmeticFilter).
    shutil.copy(work / 'engine' / 'engine.dat', TARK_LISTS / 'tark-engine.dat')
    shutil.copy(work / 'engine' / 'resources.json', TARK_LISTS / 'tark-resources.json')


def engine():
    manifest = ENGINE_CRATE / 'Cargo.toml'
    args = []
    for target in IOS_TARGETS:
        run('cargo', 'build', '--release', '--locked', '--target', target, '--manifest-path', manifest)
        lib = ENGINE_CRATE / 'target' / target / 'release' / 'libtark_adblock_ios.a'
        args += ['-library', lib, '-headers', ENGINE_CRATE / 'include']
    shutil.rmtree(XCFRAMEWORK, ignore_errors=True)
    run('xcodebuild', '-create-xcframework', *args, '-output', XCFRAMEWORK)


def sim():
    # No -sdk: it would build the package macros (host tools) for the
    # simulator too, and the compiler then cannot run them.
    run('sh', './bootstrap.sh', cwd=TREE)
    run('xcodebuild', '-project', 'firefox-ios/Client.xcodeproj',
        '-scheme', 'Fennec',
        '-destination', 'generic/platform=iOS Simulator',
        '-derivedDataPath', DERIVED,
        '-skipMacroValidation', '-skipPackagePluginValidation',
        # Apple-silicon simulator only: TarkAdblockFFI has no x86_64 slice.
        'ARCHS=arm64', 'CODE_SIGNING_ALLOWED=NO', 'build', cwd=TREE)


if __name__ == '__main__':
    steps = {'fetch': fetch, 'patch': patch, 'lists': lists, 'engine': engine, 'sim': sim}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    steps[sys.argv[1]]()

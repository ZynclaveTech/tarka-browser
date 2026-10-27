#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark for iOS from a pinned Firefox for iOS release.

    build.py fetch    clone upstream.json's tag into build/ios/firefox-ios
    build.py patch    put the tree back to the tag, apply ios/series in order
    build.py sim      bootstrap and build the Fennec scheme for the simulator

The tree is never committed: Tark's changes are the patches in ios/patches,
listed in ios/series, so moving to a new Firefox release means rebasing them.
"""
import json
import pathlib
import subprocess
import sys

IOS = pathlib.Path(__file__).resolve().parent
ROOT = IOS.parent
TREE = ROOT / 'build' / 'ios' / 'firefox-ios'
DERIVED = ROOT / 'build' / 'ios' / 'dd'


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


def sim():
    # No -sdk: it would build the package macros (host tools) for the
    # simulator too, and the compiler then cannot run them.
    run('sh', './bootstrap.sh', cwd=TREE)
    run('xcodebuild', '-project', 'firefox-ios/Client.xcodeproj',
        '-scheme', 'Fennec',
        '-destination', 'generic/platform=iOS Simulator',
        '-derivedDataPath', DERIVED,
        '-skipMacroValidation', '-skipPackagePluginValidation',
        'CODE_SIGNING_ALLOWED=NO', 'build', cwd=TREE)


if __name__ == '__main__':
    steps = {'fetch': fetch, 'patch': patch, 'sim': sim}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    steps[sys.argv[1]]()

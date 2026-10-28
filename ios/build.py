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
    build.py xlit     the D1 transliteration engine, from the same patches the
                      Mac and Android build, with ios/xlit's //base shim and C
                      interface, as BrowserKit's TarkXlitCore target
    build.py brand    the app icon sets (for iOS before 26) rendered from
                      resources/branding/app-icon.svg; the Liquid Glass icons
                      and the home header are in ios/patches/look-tark.patch
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
XLIT = IOS / 'xlit'
XLIT_CORE = TREE / 'BrowserKit' / 'Sources' / 'TarkXlitCore'
XLIT_FILES_SWIFT = TREE / 'BrowserKit' / 'Sources' / 'TarkXlit' / 'TarkXlitFiles.swift'
# tark_xlit as Tark for Android builds it: the component, then its per-language
# word files; Android's xlit-small-products only changes the Eigen BLAS, which
# Apple platforms do not use (Accelerate).
XLIT_PATCHES = (
    ROOT / 'patches' / 'tarka' / 'omnibox-translit' / 'tark-xlit-component.patch',
    ROOT / 'android' / 'patches' / 'xlit-android-files.patch',
)
XLIT_SOURCES = ('blas.h', 'blas_accelerate.cc', 'languages.cc', 'languages.h', 'model.cc', 'model.h',
                'transliterator.cc', 'transliterator.h', 'word_list.cc', 'word_list.h')
BRAND_ICON = ROOT / 'resources' / 'branding' / 'app-icon.svg'
BRAND_INK = '#12121c'
# The icon sets the Fennec, Beta and Release builds use. Firefox's alternate
# icons are not shipped (no Settings → App Icon in Tark).
ICON_SETS = ('AppIcon', 'AppIcon_Beta', 'AppIcon_Developer')
ICONS = TREE / 'firefox-ios' / 'Client' / 'Assets' / 'AppIcons.xcassets'
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


def xlit():
    shutil.rmtree(XLIT_CORE, ignore_errors=True)
    work = ROOT / 'build' / 'ios' / 'xlit-src'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    # Its own repository: inside tarka-browser's, git apply would match the
    # patch paths against tarka-browser's root and apply nothing.
    run('git', 'init', '-q', cwd=work)
    for patch_file in XLIT_PATCHES:
        run('git', 'apply', '--exclude=components/tark_xlit/BUILD.gn',
            '--include=components/tark_xlit/*', patch_file, cwd=work)
    engine_dir = XLIT_CORE / 'engine' / 'components' / 'tark_xlit'
    engine_dir.mkdir(parents=True)
    for name in XLIT_SOURCES:
        shutil.copy(work / 'components' / 'tark_xlit' / name, engine_dir / name)
    shutil.copytree(XLIT / 'shim', XLIT_CORE / 'shim')
    shutil.copy(XLIT / 'tark_xlit_c.cc', XLIT_CORE / 'tark_xlit_c.cc')
    (XLIT_CORE / 'include').mkdir()
    shutil.copy(XLIT / 'tark_xlit_c.h', XLIT_CORE / 'include' / 'tark_xlit_c.h')
    # The files Android publishes, pinned: name -> size and sha256.
    table = json.loads((XLIT / 'files.json').read_text())
    rows = '\n'.join(f'        "{name}": (size: {f["size"]}, sha256: "{f["sha256"]}"),'
                     for name, f in sorted(table.items()))
    XLIT_FILES_SWIFT.parent.mkdir(parents=True, exist_ok=True)
    XLIT_FILES_SWIFT.write_text(f'''// Generated by ios/build.py xlit from ios/xlit/files.json. Do not edit.

enum TarkXlitFiles {{
    static let table: [String: (size: Int64, sha256: String)] = [
{rows}
    ]
}}
''')


def brand():
    # iOS masks the corners itself, and App Store Connect refuses an icon with
    # an alpha channel: the Mac icon's rounded square is drawn full-bleed and
    # flattened onto its own ink. The tinted variant is grayscale, as iOS
    # tints it. Each PNG keeps its size, so the sets' Contents.json stay as
    # they are. Needs rsvg-convert (librsvg) and magick (ImageMagick).
    square = DERIVED.parent / 'app-icon-square.svg'
    square.parent.mkdir(parents=True, exist_ok=True)
    square.write_text(BRAND_ICON.read_text().replace(' rx="226"', ''))
    # The "Open in Tark" share action has its own icon set.
    action_icons = TREE / 'firefox-ios' / 'Extensions' / 'ActionExtension' / 'Media.xcassets' / 'AppIconExtension-iOS.appiconset'
    for folder in [ICONS / f'{name}.appiconset' for name in ICON_SETS] + [action_icons]:
        for png in sorted(folder.glob('*.png')):
            size = re.search(r'pixelWidth: (\d+)', out('sips', '-g', 'pixelWidth', png)).group(1)
            run('rsvg-convert', '-w', size, '-h', size, square, '-o', png)
            gray = ('-colorspace', 'Gray') if png.stem.endswith('-tinted') else ()
            run('magick', png, '-background', BRAND_INK, '-alpha', 'remove', '-alpha', 'off', *gray, png)
            if out('sips', '-g', 'hasAlpha', png).split()[-1] != 'no':
                sys.exit(f'{png} still has an alpha channel')
    glyphs()
    # Firefox's alternate-icon previews (Settings → App Icon, removed in Tark)
    # were 120 MB of the asset catalog.
    for preview in ICONS.glob('appIconAlternate_*.imageset'):
        shutil.rmtree(preview)


# Toolbar glyphs drawn for Tark (I5d): the tabs button as a box taller than
# wide (Firefox's is wide and flat), and the menu mark filling its square.
TOOLBAR_GLYPHS = {
    'tabLarge.imageset/tabLarge.pdf':
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
        '<rect x="2.5" y="1" width="19" height="22" rx="4.5" fill="none" stroke="#000" stroke-width="2"/></svg>',
    'tarkMenuMark.imageset/tarkMenuMark.pdf':
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 44 44">'
        '<circle cx="9" cy="32" r="8" fill="#e8705a"/><circle cx="35" cy="32" r="8" fill="#4338ca"/>'
        '<circle cx="22" cy="12" r="8" fill="#e0a33a"/></svg>',
}


def glyphs():
    images = TREE / 'firefox-ios' / 'Client' / 'Assets' / 'Images.xcassets'
    for path, svg in TOOLBAR_GLYPHS.items():
        source = DERIVED.parent / (pathlib.Path(path).stem + '.svg')
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(svg)
        run('rsvg-convert', '-f', 'pdf', source, '-o', images / path)


def archive():
    # The App Store build (scheme and configuration "Firefox"). Firefox's
    # configuration names Mozilla's Bitrise profiles and "iPhone Distribution";
    # Tark signs automatically with its own team. Export re-signs for the store.
    run('sh', './bootstrap.sh', cwd=TREE)
    out_path = DERIVED.parent / 'Tark.xcarchive'
    shutil.rmtree(out_path, ignore_errors=True)
    run('xcodebuild', '-project', 'firefox-ios/Client.xcodeproj',
        '-scheme', 'Firefox', '-configuration', 'Firefox',
        '-destination', 'generic/platform=iOS',
        '-archivePath', out_path,
        '-derivedDataPath', DERIVED.parent / 'dd-release',
        '-skipMacroValidation', '-skipPackagePluginValidation',
        '-allowProvisioningUpdates',
        'DEVELOPMENT_TEAM=UMTJNNPK6C', 'CODE_SIGN_STYLE=Automatic',
        'PROVISIONING_PROFILE_SPECIFIER=', 'CODE_SIGN_IDENTITY=Apple Development',
        'archive', cwd=TREE)


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
    steps = {'fetch': fetch, 'patch': patch, 'lists': lists, 'engine': engine, 'xlit': xlit, 'brand': brand, 'sim': sim, 'archive': archive}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    steps[sys.argv[1]]()

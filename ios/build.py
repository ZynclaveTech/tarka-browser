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
    build.py translate  page translation's engine (tark_captions' translator,
                      the same patches the Mac and Android build) with upstream
                      SentencePiece and ONNX Runtime for iOS, both pinned, as
                      BrowserKit's TarkTranslateCore target
    build.py brand    the app icon sets (for iOS before 26) rendered from
                      resources/branding/app-icon.svg; the Liquid Glass icons
                      and the home header are in ios/patches/look-tark.patch
    build.py sim      bootstrap and build the Fennec scheme for the simulator

The tree is never committed: Tark's changes are the patches in ios/patches,
listed in ios/series, so moving to a new Firefox release means rebasing them.
"""
import datetime
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
TRANSLATE = IOS / 'translate'
TRANSLATE_CORE = TREE / 'BrowserKit' / 'Sources' / 'TarkTranslateCore'
ORT_XCFRAMEWORK = TREE / 'BrowserKit' / 'OnnxRuntime.xcframework'
TRANSLATE_FILES_SWIFT = TREE / 'BrowserKit' / 'Sources' / 'TarkTranslate' / 'TarkTranslateFiles.swift'
# Microsoft's onnxruntime-c pod: a static xcframework (no 1.31.0 for iOS yet).
ORT_URL = 'https://download.onnxruntime.ai/pod-archive-onnxruntime-c-1.30.0.zip'
ORT_SHA256 = 'e6f1670c14406fd9f082bb400ab197a9b0a9646058ca6366e440642e2b54a2ea'
# The release before SentencePiece needed all of abseil; it bundles
# protobuf-lite and the bit of abseil it uses (Chromium's copy uses Chromium's).
SPM_URL = 'https://github.com/google/sentencepiece/archive/refs/tags/v0.2.0.tar.gz'
SPM_SHA256 = '9970f0a0afee1648890293321665e5b2efa04eaec9f1671fcf8048f456f5bb86'
# The translator's files and what they include (asr_model has the language
# codes and brings the mel frontend).
TRANSLATE_SOURCES = ('translation_engine', 'indic_text', 'english_text', 'model_source', 'ort_runtime',
                     'asr_model', 'mel_frontend')
SPM_RUNTIME = ('bpe_model', 'char_model', 'error', 'filesystem', 'model_factory', 'model_interface',
               'normalizer', 'sentencepiece_processor', 'unigram_model', 'util', 'word_model')
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


def _fetch_pinned(url, sha256, dest):
    # Kept between runs; re-downloaded only when missing or different.
    import hashlib
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha256:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.part')
    with urllib.request.urlopen(url) as response, open(tmp, 'wb') as out:
        shutil.copyfileobj(response, out)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if digest != sha256:
        tmp.unlink()
        sys.exit(f'{url}: sha256 {digest}, expected {sha256}')
    tmp.replace(dest)


def translate():
    work = ROOT / 'build' / 'ios'
    # ONNX Runtime: the pinned pod, unpacked into BrowserKit as a binary target.
    ort_zip = work / 'onnxruntime' / 'ort.zip'
    _fetch_pinned(ORT_URL, ORT_SHA256, ort_zip)
    ort = work / 'onnxruntime' / 'x'
    shutil.rmtree(ort, ignore_errors=True)
    run('unzip', '-q', ort_zip, '-d', ort)
    shutil.rmtree(ORT_XCFRAMEWORK, ignore_errors=True)
    shutil.copytree(ort / 'onnxruntime.xcframework', ORT_XCFRAMEWORK, symlinks=True)
    # SentencePiece: the pinned release.
    spm_tar = work / 'sentencepiece-0.2.0.tar.gz'
    _fetch_pinned(SPM_URL, SPM_SHA256, spm_tar)
    spm = work / 'sentencepiece-0.2.0'
    shutil.rmtree(spm, ignore_errors=True)
    run('tar', 'xzf', spm_tar, '-C', work)
    # The translator: every tark_captions patch in the Mac's series order, in a
    # repository of its own (as xlit).
    src = work / 'translate-src'
    shutil.rmtree(src, ignore_errors=True)
    src.mkdir(parents=True)
    run('git', 'init', '-q', cwd=src)
    for line in (ROOT / 'patches' / 'series').read_text().splitlines():
        if line.startswith('tarka/captions/'):
            run('git', 'apply', '--include=components/tark_captions/*', ROOT / 'patches' / line, cwd=src)
    # iOS only: ORT-format models used from their mapped files (memory).
    run('git', 'apply', TRANSLATE / 'engine-ort-format.patch', cwd=src)
    # The target: engine, SentencePiece's runtime, pffft, the shim, the C interface.
    shutil.rmtree(TRANSLATE_CORE, ignore_errors=True)
    engine = TRANSLATE_CORE / 'engine' / 'components' / 'tark_captions'
    engine.mkdir(parents=True)
    for name in TRANSLATE_SOURCES:
        for ext in ('.cc', '.h'):
            shutil.copy(src / 'components' / 'tark_captions' / (name + ext), engine)
    shutil.copytree(TRANSLATE / 'third_party' / 'pffft', TRANSLATE_CORE / 'engine' / 'third_party' / 'pffft')
    spm_out = TRANSLATE_CORE / 'spm'
    (spm_out / 'src' / 'builtin_pb').mkdir(parents=True)
    for header in (spm / 'src').glob('*.h'):
        shutil.copy(header, spm_out / 'src')
    for name in SPM_RUNTIME:
        shutil.copy(spm / 'src' / (name + '.cc'), spm_out / 'src')
    for f in (spm / 'src' / 'builtin_pb').iterdir():
        shutil.copy(f, spm_out / 'src' / 'builtin_pb')
    for part in ('protobuf-lite', 'absl', 'darts_clone', 'esaxx'):
        shutil.copytree(spm / 'third_party' / part, spm_out / 'third_party' / part)
    # protobuf-lite's Windows file is not part of an Apple build.
    (spm_out / 'third_party' / 'protobuf-lite' / 'io_win32.cc').unlink()
    shutil.copy(spm / 'LICENSE', spm_out / 'LICENSE')
    (spm_out / 'config.h').write_text('#pragma once\n#define VERSION "0.2.0"\n'
                                      '#define PACKAGE "sentencepiece"\n#define PACKAGE_STRING "sentencepiece"\n')
    shutil.copytree(TRANSLATE / 'shim', TRANSLATE_CORE / 'shim')
    shutil.copytree(ort / 'Headers', TRANSLATE_CORE / 'ort')
    shutil.copy(TRANSLATE / 'tark_translate_c.cc', TRANSLATE_CORE)
    (TRANSLATE_CORE / 'include').mkdir()
    shutil.copy(TRANSLATE / 'tark_translate_c.h', TRANSLATE_CORE / 'include')
    # The model files Android publishes, pinned: "<direction>/<file>" -> size
    # and sha256 (TarkTranslateModels downloads and checks them).
    table = json.loads((TRANSLATE / 'files.json').read_text())
    rows = '\n'.join(f'        "{name}": (size: {f["size"]}, sha256: "{f["sha256"]}"),'
                     for name, f in sorted(table.items()))
    TRANSLATE_FILES_SWIFT.parent.mkdir(parents=True, exist_ok=True)
    TRANSLATE_FILES_SWIFT.write_text(f'''// Generated by ios/build.py translate from ios/translate/files.json. Do not edit.

enum TarkTranslateFiles {{
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
    # Firefox's alternate app icons (Settings → App Icon is gone in Tark, but
    # the icons still ship): each becomes Tark's icon.
    alternates = sorted(ICONS.glob('AppIcon_Alt_*.appiconset'))
    for folder in [ICONS / f'{name}.appiconset' for name in ICON_SETS] + alternates + [action_icons]:
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
    debrand()


# Firefox's artwork that ships in the app (logos, the fox illustrations, the
# Firefox favicon): each becomes Tark's mark. App Review rejected a build
# under 4.1(a) "copycat" for Firefox's branding (stickers, widget name).
FIREFOX_IMAGESETS = ('faviconFox', 'foxConfirmation', 'foxDefaultBrowser', 'foxWithStars',
                     # (fxHomeHeaderLogoBall/Text are Tark's mark and wordmark
                     # already, from look-tark.patch: not here.)
                     'logoFirefoxLarge',
                     'onboardingFoxyWindow', 'firefoxLoader', 'firefox-jp', 'Icon-Small', 'splash',
                     # The fox in Firefox's illustrations (onboarding, empty and
                     # error states, the protections panel) and Pocket's logo;
                     # found by rendering every image in the app.
                     'onboardingSyncWithIconsBrandRefresh', 'onboardingSyncWithIconsJapan',
                     'onboardingToolbarIconBottomJapanSelected', 'onboardingToolbarIconTopJapanSelected',
                     'onboardingWelcomeBrandRefresh', 'onboardingWelcomeJapan', 'onboardingWelcome',
                     'onboardingDock', 'onboardingNotification', 'onboardingSearchWidget',
                     'onboardingSetDefaultSteps', 'noInternetConnection', 'securityError', 'kitCircle',
                     'kitOnboardingNotifications', 'kitOnboardingSync', 'homepage-pocket',
                     'noBookmarksInFolder', 'noBookmarksInRoot', 'picShieldCheckmark',
                     'protectionPanelAlert', 'protectionPanelOff', 'protectionPanelOn')
# Names of Mozilla's products and of Mozilla in the app's text. No word
# boundaries: some languages join the name to the next letter.
FIREFOX_WORDS = re.compile(r'Firefox|Mozilla|Fennec', re.I)
FIREFOX_SITE = re.compile(r'firefox\.com', re.I)


def tarkify(text):
    return FIREFOX_WORDS.sub('Tark', FIREFOX_SITE.sub('gettarka.com', text))
# Only the text, never the keys (code looks strings up by key): the value of
# a "key" = "value"; line, and <string> elements in a .stringsdict.
STRINGS_VALUE = re.compile(r'^(\s*"(?:[^"\\]|\\.)*"\s*=\s*")((?:[^"\\]|\\.)*)(")', re.M)
STRINGSDICT_VALUE = re.compile(r'(<string>)([^<]*)(</string>)')


def debrand():
    mark_svg = DERIVED.parent / 'tark-mark.svg'
    mark_svg.write_text(TOOLBAR_GLYPHS['tarkMenuMark.imageset/tarkMenuMark.pdf'].replace(
        'width="24" height="24"', 'width="88" height="88"'))
    mark_pdf = DERIVED.parent / 'tark-mark.pdf'
    run('rsvg-convert', '-f', 'pdf', mark_svg, '-o', mark_pdf)
    contents = json.dumps({'images': [{'filename': 'tarkMark.pdf', 'idiom': 'universal'}],
                           'info': {'author': 'xcode', 'version': 1},
                           'properties': {'preserves-vector-representation': True}}, indent=2)
    shipped = [TREE / 'firefox-ios', TREE / 'BrowserKit' / 'Sources']
    for root in shipped:
        for name in FIREFOX_IMAGESETS:
            for imageset in root.rglob(f'{name}.imageset'):
                if 'Tests' in imageset.parts:
                    continue
                for f in imageset.iterdir():
                    f.unlink()
                shutil.copy(mark_pdf, imageset / 'tarkMark.pdf')
                (imageset / 'Contents.json').write_text(contents)
    # Firefox's fox GIFs (pull-to-refresh easter egg, a hero image) and the
    # intro video (a phone showing Firefox's icon): Tark's mark instead.
    mark_png = DERIVED.parent / 'tark-mark.png'
    run('rsvg-convert', '-w', '240', '-h', '240', mark_svg, '-o', mark_png)
    for gif in ('easterEggGif.gif', 'kitHeroGif.gif'):
        run('magick', mark_png, TREE / 'firefox-ios' / 'Client' / 'Assets' / gif)
    run('ffmpeg', '-loglevel', 'error', '-y', '-loop', '1', '-i', mark_png, '-t', '1',
        '-vf', 'pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x13141f,format=yuv420p', '-c:v', 'libx264',
        TREE / 'BrowserKit' / 'Sources' / 'OnboardingKit' / 'IntroVideo.mp4')
    # The app's text, every language: Firefox / Mozilla → Tark.
    for root in shipped:
        for path in list(root.rglob('*.strings')) + list(root.rglob('*.stringsdict')):
            if any(part.endswith('Tests') for part in path.parts):
                continue
            raw = path.read_bytes()
            encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8'
            text = raw.decode(encoding)
            pattern = STRINGSDICT_VALUE if path.suffix == '.stringsdict' else STRINGS_VALUE
            new = pattern.sub(lambda m: m.group(1) + tarkify(m.group(2)) + m.group(3), text)
            if new != text:
                path.write_bytes(new.encode(encoding))
    # Sentences in code (English fallbacks, translator comments, debug-menu
    # text): any Swift string literal with a space that names Firefox/Mozilla.
    # Script identifiers (window.__firefox__) are code, not text, and stay.
    swift_value = re.compile(r'(")((?:[^"\\\n]|\\.)* (?:[^"\\\n]|\\.)*)(")')
    for root in shipped:
        for path in root.rglob('*.swift'):
            if any(part.endswith('Tests') for part in path.parts):
                continue
            text = path.read_text()
            if not FIREFOX_WORDS.search(text):
                continue
            # Never a lookup key: key: "...", or the first argument of
            # NSLocalizedString( / MZLocalizedString(.
            def rewrite(m, text=text):
                before = text[max(0, m.start() - 40):m.start()]
                if '__firefox' in m.group(2) or re.search(r'(key:\s*|LocalizedString\(\s*)$', before):
                    return m.group(0)
                return m.group(1) + tarkify(m.group(2)) + m.group(3)
            new = swift_value.sub(rewrite, text)
            if new != text:
                path.write_text(new)
    # Mozilla's experiment data and Firefox's test pages ship in the app.
    (TREE / 'firefox-ios' / 'Client' / 'Experiments' / 'initial_experiments.json').write_text('{"data": []}\n')
    # Firefox's UI-test pages (test-fixtures, "The Book of Mozilla", ...) were
    # copied into every build; not into the App Store build.
    project = TREE / 'firefox-ios' / 'Client.xcodeproj' / 'project.pbxproj'
    text = project.read_text()
    copy = 'shellScript = "fixtures=\\"${SRCROOT}/../test-fixtures\\"\\n'
    if copy in text:
        project.write_text(text.replace(copy, copy[:15] + '[ \\"$CONFIGURATION\\" = Firefox ] && exit 0\\n' + copy[15:]))
    # The search widget's name in the widget gallery.
    for config in [TREE / 'firefox-ios' / 'Client.xcodeproj' / 'project.pbxproj',
                   *(TREE / 'firefox-ios' / 'Client' / 'Configuration').glob('*.xcconfig')]:
        text = config.read_text()
        config.write_text(text.replace('Firefox - Search', 'Tark - Search'))


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
        # Each upload needs a higher build number: the UTC minute it was built.
        'TARK_BUILD=' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M'),
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
    steps = {'fetch': fetch, 'patch': patch, 'lists': lists, 'engine': engine, 'xlit': xlit, 'translate': translate, 'brand': brand, 'sim': sim, 'archive': archive}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    steps[sys.argv[1]]()

#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's caption engine for Android, from the Mac's patches.

    python3 android/captions/engine.py build [REPO]   write android/patches/captions-engine.patch
    python3 android/captions/engine.py check [REPO]   exit 1 if it is out of date

The Android series leaves patches/tarka/captions/ out (their browser and
Views code is the Mac's), but the engine they build, components/tark_captions,
is the same on both. This takes only that folder's hunks from the captions
patches, in series order, applies them to an empty tree and writes the
result as one patch of new files, plus the root gn_all line that makes gn
load the folder on Android. utils/tests/test_android_captions.py fails when
the Android patch and the Mac's patches disagree.
"""

import pathlib
import re
import subprocess
import sys
import tempfile

COMPONENT = 'components/tark_captions/'
CAPTIONS = 'tarka/captions/'
OUT = pathlib.Path('android') / 'patches' / 'captions-engine.patch'
# Root BUILD.gn: gn loads a folder only when something names it.
GN_ALL = '''--- a/BUILD.gn
+++ b/BUILD.gn
@@ -102,6 +102,7 @@
       "//codelabs",
       "//components:components_unittests",
       "//components/gwp_asan:gwp_asan_unittests",
+      "//components/tark_captions:host_unittests",
       "//infra/orchestrator:orchestrator_all",
       "//net:net_unittests",
       "//sandbox:sandbox_unittests",
'''


def captions_patches(repo):
    series = (repo / 'patches' / 'series').read_text(encoding='utf-8').splitlines()
    return [repo / 'patches' / e.strip() for e in series
            if e.strip().startswith(CAPTIONS) and not e.strip().startswith('#')]


def component_sections(patch_text):
    """The patch's per-file sections whose target is in the component."""
    sections = re.split(r'(?m)^(?=--- )', patch_text)
    keep = []
    for section in sections:
        m = re.match(r'--- \S+\n\+\+\+ b/(\S+)', section)
        if m and m.group(1).startswith(COMPONENT):
            keep.append(section if section.endswith('\n') else section + '\n')
    return keep


def component_files(repo):
    """{path: text} of the component once every captions patch is applied."""
    repo = pathlib.Path(repo)
    with tempfile.TemporaryDirectory() as tmp:
        tree = pathlib.Path(tmp)
        for patch in captions_patches(repo):
            sections = component_sections(patch.read_text(encoding='utf-8'))
            if not sections:
                continue
            r = subprocess.run(['patch', '-p1', '-s', '-N', '--no-backup-if-mismatch', '-d', str(tree)],
                               input=''.join(sections), capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f'{patch.name}: {r.stdout}{r.stderr}')
        return {str(p.relative_to(tree)): p.read_text(encoding='utf-8')
                for p in sorted(tree.rglob('*')) if p.is_file()}


def new_file_hunk(path, text):
    lines = text.splitlines(keepends=True)
    out = [f'--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n']
    out += ['+' + line for line in lines]
    if lines and not lines[-1].endswith('\n'):
        out.append('\n\\ No newline at end of file\n')
    return ''.join(out)


def build(repo):
    files = component_files(repo)
    return GN_ALL + ''.join(new_file_hunk(path, text) for path, text in files.items())


def main():
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ('build', 'check'):
        sys.exit(__doc__)
    repo = pathlib.Path(sys.argv[2] if len(sys.argv) == 3 else pathlib.Path(__file__).resolve().parents[2])
    text = build(repo)
    out = repo / OUT
    if sys.argv[1] == 'check':
        if not out.exists() or out.read_text(encoding='utf-8') != text:
            sys.exit(f'{OUT} is out of date: run android/captions/engine.py build')
        return
    out.write_text(text, encoding='utf-8')
    print(f'wrote {OUT}: {len(files_in(text))} files')


def files_in(text):
    return re.findall(r'^\+\+\+ b/(\S+)', text, re.M)


if __name__ == '__main__':
    main()

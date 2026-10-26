#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's Windows build in two layers, as on Android (W1).

    python layered_build.py WORKDIR [--fresh] [--patch-only] [--jobs N]

Run in the workdir prepare_workdir.py made. The base (the Chromium tarball,
pruned, the Windows downloads, ungoogled-chromium's core patches and the
Windows platform patches) is made by upstream's build.py with
TARK_PHASE=base and kept as a copy, build/src-base, stamped with the hash of
its inputs. Tark's layer (Tark's patches, domain substitution and
tark_post_patch.py) is applied again on every run: android/layers.py puts
back the base wherever the last layer changed it, build.py applies the layer
(TARK_PHASE=layer), and every file that comes out as the last build had it
keeps that build's time. build/src/out is kept, so ninja (build.py with
TARK_PHASE=build) rebuilds only what the layer changed. A different base
wipes the tree and its copy and makes them again, but keeps out: the
tarball's files keep its times, so ninja recompiles only what the new base
and the layer changed. --fresh wipes out too.
"""

import argparse
import hashlib
import os
import pathlib
import shutil
import stat
import subprocess
import sys

# What the base is made from, relative to the workdir. Tark's patches and its
# hook are the layer, not the base.
BASE_FILES = [
    'ungoogled-chromium/chromium_version.txt', 'ungoogled-chromium/downloads.ini',
    'ungoogled-chromium/pruning.list', 'ungoogled-chromium/patches/series',
    'ungoogled-chromium/utils/patches.py', 'ungoogled-chromium/utils/prune_binaries.py',
    'ungoogled-chromium/utils/downloads.py', 'downloads.ini', 'pruning.list', 'build.py',
]
BASE_GLOBS = ['ungoogled-chromium/patches/**/*.patch', 'patches/ungoogled-chromium/**/*.patch']

# The base's copy: times kept (layers.py compares them; /COPY:DAT, and
# /DCOPY:DAT for folders) and symbolic links copied as links (/SL: Chromium's
# tree has some, and following them is refused).
ROBOCOPY_FLAGS = ['/MIR', '/SL', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/NFL', '/NDL', '/NP', '/MT:32']


def _platform_series(work):
    """patches/series without Tark's entries: the Windows platform patches."""
    lines = (work / 'patches' / 'series').read_text(encoding='utf-8').splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith(('#', 'tarka/'))]


def base_hash(work):
    work = pathlib.Path(work)
    files = [work / f for f in BASE_FILES]
    for pattern in BASE_GLOBS:
        files += sorted(p for p in work.glob(pattern) if p.is_file())
    h = hashlib.sha256()
    for f in files:
        h.update(str(f.relative_to(work)).replace('\\', '/').encode() + b'\0')
        h.update(f.read_bytes() if f.exists() else b'(missing)')
        h.update(b'\0')
    h.update('\n'.join(_platform_series(work)).encode())
    return h.hexdigest()


def _make_writable_and_retry(func, path, exc):
    """rmtree's onexc: git's objects are read-only, which Windows refuses
    to delete; make the entry (and its folder) writable and try again."""
    for p in (os.path.dirname(path), path):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass
    func(path)


def _rmtree(path):
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=lambda f, p, e: _make_writable_and_retry(f, p, e[1]))


def _system_runner(work, jobs):
    repo = pathlib.Path((work / 'tark_repo.txt').read_text(encoding='utf-8').strip())
    layers = repo / 'android' / 'layers.py'
    src, base = work / 'build' / 'src', work / 'build' / 'src-base'
    record = work / 'build' / 'layers.json'
    keep = work / 'build' / 'out-keep'

    def run(step, env=None):
        print(f'tark: {step} {(env or {}).get("TARK_PHASE", "")}'.rstrip(), flush=True)
        if step == 'build.py':
            subprocess.run([sys.executable, 'build.py', '--tarball', '-j', str(jobs)], cwd=work,
                           env={**os.environ, **(env or {})}, check=True)
        elif step == 'copy-base':
            # Exit codes below 8 mean success.
            code = subprocess.run(['robocopy', str(src), str(base), *ROBOCOPY_FLAGS,
                                   '/XD', str(src / 'out')]).returncode
            if code >= 8:
                raise subprocess.CalledProcessError(code, 'robocopy')
        elif step in ('reset', 'settle'):
            subprocess.run([sys.executable, str(layers), step, str(base), str(src), str(record)], check=True)
        elif step == 'stash-out':
            if (src / 'out').is_dir() and not keep.exists():
                (src / 'out').rename(keep)
        elif step == 'restore-out':
            if keep.is_dir():
                if (src / 'out').exists():
                    _rmtree(src / 'out')
                keep.rename(src / 'out')
        elif step == 'wipe':
            for p in (src, base):
                if p.exists():
                    _rmtree(p)
            for f in ('base.stamp', 'layers.json', 'namesubs.tar'):
                (work / 'build' / f).unlink(missing_ok=True)
        else:
            raise ValueError(step)
    return run


def run(work, fresh=False, patch_only=False, jobs=64, runner=None):
    work = pathlib.Path(work)
    runner = runner or _system_runner(work, jobs)
    build = work / 'build'
    build.mkdir(parents=True, exist_ok=True)
    stamp = build / 'base.stamp'
    want = base_hash(work)
    have = stamp.read_text().strip() if stamp.exists() else None
    if not fresh and have == want and (build / 'src-base').is_dir():
        runner('reset')
    else:
        # Anything left from an earlier run (a tree patched by its layer, or
        # one cut short before its stamp) is never patched again.
        wipe = have is not None or fresh or (build / 'src').exists() or (build / 'src-base').exists()
        keep_out = wipe and not fresh
        if keep_out:
            runner('stash-out')
        if wipe:
            runner('wipe')
        stamp.unlink(missing_ok=True)
        runner('build.py', env={'TARK_PHASE': 'base'})
        runner('copy-base')
        if keep_out:
            runner('restore-out')
        stamp.write_text(want + '\n')
    # The layer is applied again: an earlier run's name-substitution backup is
    # stale (name_substitution.py refuses to overwrite it).
    (build / 'namesubs.tar').unlink(missing_ok=True)
    runner('build.py', env={'TARK_PHASE': 'layer'})
    runner('settle')
    if not patch_only:
        runner('build.py', env={'TARK_PHASE': 'build'})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('work')
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--patch-only', action='store_true')
    ap.add_argument('--jobs', type=int, default=64)
    args = ap.parse_args(argv)
    run(args.work, args.fresh, args.patch_only, args.jobs)


if __name__ == '__main__':
    main()

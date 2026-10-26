#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's layer of a prepared Android tree, put back and applied again.

    layers.py reset BASE SRC RECORD
    layers.py settle BASE SRC RECORD

android/build.sh keeps the base (Chromium, its toolchains and
ungoogled-chromium's core patches) as a copy, BASE, beside the tree, SRC.
Tark's layer (Tark's series, domain and name substitution, Tark's steps) is
whatever in SRC differs from BASE; out/ is not part of the tree.

reset: records every file of the layer (sha256 and time) in RECORD, then puts
back the base wherever SRC differs: changed and deleted files come back from
BASE, added ones go. What comes back is written now, so it is newer than any
object built from the layer it replaces: a reset cut short still rebuilds.

A layer that never settled (its run stopped, say on a patch that did not
apply) is not recorded: its files carry that run's times, and recording them
over the last build's would make every later build recompile them. RECORD's
'.settled' file marks a settled layer.

settle, after the layer is applied again: a file of the new layer with the
same contents as in RECORD gets its time back, and ninja keeps what was built
from it; any other file of the layer is dated now. Domain and name
substitution rewrite thousands of files on every run, nearly all of them as
they were: without this, every build would be close to a full one.
"""

import hashlib
import json
import os
import pathlib
import shutil
import stat
import sys
import time


def _sig(path):
    """What makes two entries the same: a regular file's size, time and
    mode; a link's target. None for a folder (compared entry by entry)."""
    st = os.lstat(path)
    if stat.S_ISDIR(st.st_mode):
        return None
    if stat.S_ISLNK(st.st_mode):
        return ('link', os.readlink(path))
    if stat.S_ISREG(st.st_mode):
        return ('file', st.st_size, st.st_mtime_ns, stat.S_IMODE(st.st_mode))
    return ('other', st.st_mode)


def _names(path):
    try:
        return set(os.listdir(path))
    except (FileNotFoundError, NotADirectoryError):
        return set()


def footprint(base, src):
    """The relative paths, sorted, where SRC differs from BASE: a folder only
    on one side is listed once, not file by file. SRC's top-level out/ is
    left out."""
    base, src = pathlib.Path(base), pathlib.Path(src)
    found = []
    stack = ['']
    while stack:
        rel = stack.pop()
        b_names, s_names = _names(base / rel), _names(src / rel)
        for name in b_names | s_names:
            if rel == '' and name == 'out':
                continue
            path = f'{rel}/{name}' if rel else name
            if name not in b_names or name not in s_names:
                found.append(path)
                continue
            b, s = _sig(base / path), _sig(src / path)
            if b is None and s is None:
                stack.append(path)
            elif b != s:
                found.append(path)
    return sorted(found)


def _files(root, rel):
    """The regular files at or under root/rel, relative to root."""
    top = root / rel
    if top.is_symlink() or not top.exists():
        return
    if top.is_file():
        yield rel
        return
    for dirpath, dirnames, filenames in os.walk(top):
        for name in filenames:
            path = pathlib.Path(dirpath) / name
            if not path.is_symlink() and path.is_file():
                yield str(path.relative_to(root))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif os.path.lexists(path):
        path.unlink()


def _put_back(base, src, rel):
    """SRC's rel as in BASE (or gone), every file written now: copyfile and
    copymode, never copy2, which would carry the base's time over."""
    b, s = base / rel, src / rel
    _remove(s)
    if b.is_symlink():
        os.symlink(os.readlink(b), s)
    elif b.is_dir():
        shutil.copytree(b, s, symlinks=True, copy_function=shutil.copy)
    elif b.exists():
        shutil.copy(b, s)


def _settled(record):
    return record.with_name(record.name + '.settled')


def reset(base, src, record):
    base, src, record = pathlib.Path(base), pathlib.Path(src), pathlib.Path(record)
    changed = footprint(base, src)
    settled = _settled(record)
    if settled.exists() or not record.exists():
        files = {}
        for rel in changed:
            for f in _files(src, rel):
                files[f] = [_sha256(src / f), os.lstat(src / f).st_mtime_ns]
        partial = record.with_name(record.name + '.part')
        partial.write_text(json.dumps(files, sort_keys=True))
        os.replace(partial, record)
    # The layer about to be applied has not settled yet.
    settled.unlink(missing_ok=True)
    for rel in changed:
        _put_back(base, src, rel)
    return changed


def settle(base, src, record):
    base, src, record = pathlib.Path(base), pathlib.Path(src), pathlib.Path(record)
    last = json.loads(record.read_text()) if record.exists() else {}
    now = time.time_ns()
    kept = dated = 0
    for rel in footprint(base, src):
        for f in _files(src, rel):
            was = last.get(f)
            if was and was[0] == _sha256(src / f):
                os.utime(src / f, ns=(now, was[1]))
                kept += 1
            else:
                os.utime(src / f, ns=(now, now))
                dated += 1
    _settled(record).touch()
    return kept, dated


def main(argv):
    if len(argv) != 5 or argv[1] not in ('reset', 'settle'):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[1] == 'reset':
        changed = reset(*argv[2:5])
        print(f'layers: put back {len(changed)} paths of the last Tark layer')
    else:
        kept, dated = settle(*argv[2:5])
        print(f'layers: {kept} files as the last build had them, {dated} changed')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

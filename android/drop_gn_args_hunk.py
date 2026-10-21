#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Drop the gclient_gn_args_file hunk from a copy of ungoogled's
depot_tools.patch (A1).

    python3 android/drop_gn_args_hunk.py DEPOT_TOOLS_PATCH

That hunk makes gclient_gn_args_file an absolute path, which the
depot_tools Chromium 155 pins rejects ("Must be a relative path"). Tark's
Android layout keeps .gclient beside a solution named src, so the relative
path is already right. Fails if the hunk is not found exactly once.
"""

import pathlib
import re
import sys

MARK = 'self._gn_args_file = r"UC_OUT"'


def drop(text):
    hunks = re.split(r'(?m)^(?=@@ |--- a/)', text)
    keep = [h for h in hunks if MARK not in h]
    if len(hunks) - len(keep) != 1:
        raise SystemExit(f'expected one hunk with {MARK!r}, found {len(hunks) - len(keep)}')
    return ''.join(keep)


def main():
    path = pathlib.Path(sys.argv[1])
    path.write_text(drop(path.read_text(encoding='utf-8')), encoding='utf-8')


if __name__ == '__main__':
    main()

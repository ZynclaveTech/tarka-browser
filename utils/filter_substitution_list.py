#!/usr/bin/env python3
"""Writes ungoogled-chromium's domain_substitution.list without the files
Tark needs left alone (utils/domain_substitution_skip.txt): the ones that
carry the Chrome Web Store's hosts, so installs and update checks reach the
store. Everything else is still substituted.

usage: filter_substitution_list.py SRC_LIST SKIP_FILE OUT_LIST
"""
import sys


def filter_list(lines, skip):
    """lines minus the paths in skip; a skip path not in lines is an error,
    because a typo would otherwise leave every file substituted unnoticed."""
    present = {line.strip() for line in lines}
    missing = sorted(skip - present)
    if missing:
        raise ValueError("not in domain_substitution.list: " + ", ".join(missing))
    return [line for line in lines if line.strip() not in skip]


def main(src, skip_file, out):
    lines = open(src).read().splitlines(keepends=True)
    skip = {l.strip() for l in open(skip_file).read().splitlines() if l.strip() and not l.startswith("#")}
    open(out, "w").write("".join(filter_list(lines, skip)))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])

# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's steps after patching that every non-Mac desktop build shares (L1).

windows/tark_post_patch.py and linux/tark_post_patch.py call these, around
their own platform steps: name substitution, the mark, trust data, Inter for
WebUI, the ad blocker's crates and lists, IndicXlit (before), and the
captions' credits (after the libraries they describe).
"""

import os
import pathlib
import shutil
import subprocess
import sys


def run(*args, **kwargs):
    print('tark:', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def xlit_env(repo, core, cache, src):
    return dict(os.environ, _root_dir=repo.as_posix(), _src_dir=src.as_posix(),
                _main_repo=core.as_posix(), _download_cache=cache.as_posix())


def before_platform(repo, core, cache, work, src, bash):
    py = sys.executable
    # Product name in UI strings (backup kept for a reset, as on the Mac).
    run(py, repo / 'utils' / 'name_substitution.py', '--sub', '-t', src,
        '--backup-path', work / 'build' / 'namesubs.tar')
    # The mark, wherever Chromium ships a logo file the manifest names.
    run(py, repo / 'utils' / 'install_branding.py', repo / 'resources' / 'branding' / 'mark', src)
    # Certificate trust data: CT log list, Chrome Root Store, CRLSet (resources/trust).
    run(py, repo / 'utils' / 'trust_data.py', 'install', src,
        '--domain-regex', core / 'domain_regex.list')
    # Inter for WebUI pages, served as chrome://resources/fonts/.
    fonts = src / 'ui' / 'webui' / 'resources' / 'fonts'
    fonts.mkdir(parents=True, exist_ok=True)
    for woff in (repo / 'resources' / 'fonts').glob('inter-latin*.woff2'):
        shutil.copy2(woff, fonts / woff.name)
    # The ad blocker: adblock-rust's crates (pinned sha256) and its built-in
    # list bundle, checked against Tark's list-signing key
    # (utils/adblock_lists.py; TARK_LISTS_DIR stands in for gettarka.com).
    run(py, repo / 'android' / 'adblock' / 'crates.py', src, '--cache', cache / 'crates')
    lists_dir = os.environ.get('TARK_LISTS_DIR')
    run(py, repo / 'utils' / 'adblock_lists.py', src / 'chrome' / 'browser' / 'tark_adblock' / 'lists.zip',
        *(['--lists-dir', lists_dir] if lists_dir else []))
    # IndicXlit weights and word lists (utils/install_xlit.sh, under bash).
    run(bash, '-c', 'source "$_root_dir/utils/install_xlit.sh" && _install_xlit',
        env=xlit_env(repo, core, cache, src))


def after_platform(repo, core, cache, src, bash):
    # The captions' about:credits entries, as build.sh does on the Mac.
    run(bash, '-c', 'source "$_root_dir/utils/install_captions_credits.sh" && _install_captions_credits',
        env=xlit_env(repo, core, cache, src))

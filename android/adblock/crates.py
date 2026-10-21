#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Places adblock-rust and its new dependencies into Chromium's vendored
crates (A2, spec §4).

    python3 android/adblock/crates.py SRC [--cache DIR]

android/patches/adblock-crates.patch adds the crates to Chromium's
Cargo.toml, Cargo.lock and gnrt_config.toml, with the BUILD.gn files gnrt
generates for them; this puts their sources in
third_party/rust/chromium_crates_io/vendor/<name>-<epoch>, as gnrt vendor
does, but checks every .crate against the sha256 pinned here (gnrt checks
nothing) and applies the crate's patches from chromium_crates_io/patches/.
Runs after domain substitution, which never sees these files.
"""

import argparse
import hashlib
import io
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# name, version, sha256 of the .crate (the crates.io index's cksum).
CRATES = [
    ('adblock', '0.13.3', 'f44b96a666a23c12acad7c688bfe8638a7094e7eabe765b09a6864ab991c676d'),
    ('arrayvec', '0.7.8', 'd3fb67a6e08acf24fdeccbac2cb6ac4305825bd1f117462e0e6f2f193345ad56'),
    ('flatbuffers', '25.12.19', '35f6839d7b3b98adde531effaf34f0c2badc6f4735d26fe74709d8e513a96ef3'),
    ('idna', '1.1.0', '3b0875f23caa03898994f6ddc501886a45c7d3d62d04d2d90788d47be1b1e4de'),
    ('idna_adapter', '1.2.2', 'cb68373c0d6620ef8105e855e7745e18b0d00d3bdb07fb532e434244cdb9a714'),
    ('percent-encoding', '2.3.2', '9b4f627cb1b25917193a259e49bdad08f671f8d9708acfd5fe0a8c1455d87220'),
    ('precomputed-hash', '0.1.1', '925383efa346730478fb4838dbe9137d2a47675ad789c546d150a6e1dd4ab31c'),
    ('rustc-hash', '2.1.3', '6b1e7f9a428571be2dc5bc0505c13fb6bf936822b894ec87abf8a08a4e51742d'),
    ('rustc_version', '0.4.1', 'cfcb3a22ef46e85b45de6ee7e79d063319ebb6594faafcf1c225ea92ab6e9b92'),
    ('seahash', '4.1.0', '1c107b6f4780854c8b126e228ea8869f4d7b71260f962fefb57b996b8959ba6b'),
    ('semver', '1.0.28', '8a7852d02fc848982e0c167ef163aaff9cd91dc640ba85e263cb1ce46fae51cd'),
]
CIO = 'third_party/rust/chromium_crates_io'


def epoch(version):
    """gnrt's epoch: the semver-compatible part, as in vendor/<name>-<epoch>."""
    major, minor, patch = version.split('.')[:3]
    if major != '0':
        return f'v{major}'
    if minor != '0':
        return f'v0_{minor}'
    return f'v0_0_{patch}'


def download(name, version, cache):
    path = pathlib.Path(cache) / f'{name}-{version}.crate'
    if not path.is_file():
        url = f'https://static.crates.io/crates/{name}/{name}-{version}.crate'
        req = urllib.request.Request(url, headers={'User-Agent': 'Tark-build/1 (+https://gettarka.com)'})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.read())
    return path.read_bytes()


def place(src, name, version, sha256, data):
    """Checks a .crate and unpacks it into the vendor folder, with its
    patches applied. Raises ValueError on a checksum mismatch."""
    src = pathlib.Path(src)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f'{name} {version}: sha256 is not the pinned one')
    dirname = f'{name}-{epoch(version)}'
    dest = src / CIO / 'vendor' / dirname
    with tempfile.TemporaryDirectory(dir=src / CIO) as tmp:
        tarfile.open(fileobj=io.BytesIO(data), mode='r:gz').extractall(tmp, filter='data')
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(pathlib.Path(tmp) / f'{name}-{version}'), dest)
    (dest / '.cargo-checksum.json').write_text('{"files":{}}\n')
    pdir = src / CIO / 'patches' / dirname
    if pdir.is_dir():
        for p in sorted(pdir.glob('*.diff')):
            subprocess.run(['git', 'apply', '-p1', str(p)], cwd=src, check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('src')
    ap.add_argument('--cache', default=str(pathlib.Path(__file__).resolve().parents[2] / 'build' / 'crates'))
    args = ap.parse_args(argv)
    for name, version, sha256 in CRATES:
        place(args.src, name, version, sha256, download(name, version, args.cache))
        print(f'{name} {version}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

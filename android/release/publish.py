#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Publishes a signed Tark for Android APK on gettarka.com (A5).

    publish.py APK [--for-real]

Writes the index the app's daily update check reads
(gettarka.com/android/v1/latest.json, chrome/browser/tark_update) and prints
the three steps, in order:
  1. the APK, under a name no earlier release had, never over an existing
     one (--if-none-match), cached for a year;
  2. the index, cached for five minutes;
  3. a CloudFront invalidation of the index alone.
With --for-real it runs them: a production change, only with the user's OK.
It refuses an APK not signed by Tark's release key (cert_sha256.txt), one
that is not com.gettarka.tarka, and a version code not newer than the one
gettarka.com offers now.
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sign  # noqa: E402

APK_PREFIX = 'https://gettarka.com/android/v1/'
BUCKET = 'tark-site-967555169405'
DISTRIBUTION = 'E1F37RZV3Y8TAK'
PACKAGE = 'com.gettarka.tarka'
CERT_FILE = HERE / 'cert_sha256.txt'


def index_for(apk, version_name, version_code):
    if not sign._VERSION_NAME.fullmatch(version_name):
        raise ValueError(f'{version_name!r} is not a Tark version name')
    data = pathlib.Path(apk).read_bytes()
    return {
        'version_code': int(version_code),
        'version_name': version_name,
        'url': f'{APK_PREFIX}tark-{version_name}.apk',
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
    }


def _apk_cert(apk):
    out = subprocess.run([sign._build_tool('apksigner'), 'verify', '--print-certs', str(apk)],
                         capture_output=True, text=True, check=True).stdout
    return re.findall(r'certificate SHA-256 digest: ([0-9a-f]{64})', out)


def live_code(url=APK_PREFIX + 'latest.json'):
    """The version code gettarka.com offers now, or 0 when there is no index yet."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return int(json.load(response)['version_code'])
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return 0
        raise


def publish(apk, index, bucket=BUCKET, cert_file=CERT_FILE, live_code=0, dry_run=True):
    want = pathlib.Path(cert_file).read_text().strip()
    if _apk_cert(apk) != [want]:
        raise ValueError(f'{apk} is not signed by the release certificate alone ({want})')
    if index['version_code'] <= live_code:
        raise ValueError(f"version code {index['version_code']} is not newer than the live {live_code}")
    name = index['url'][len(APK_PREFIX):]
    with tempfile.TemporaryDirectory() as tmp:
        index_file = pathlib.Path(tmp) / 'latest.json'
        index_file.write_text(json.dumps(index, indent=1) + '\n')
        commands = _commands(apk, name, index_file, bucket)
        if not dry_run:
            for command in commands:
                subprocess.run(command, check=True)
    return commands


def _commands(apk, name, index_file, bucket):
    return [
        ['aws', 's3api', 'put-object', '--bucket', bucket, '--key', f'android/v1/{name}', '--body', str(apk),
         '--if-none-match', '*', '--content-type', 'application/vnd.android.package-archive',
         '--cache-control', 'public, max-age=31536000, immutable'],
        ['aws', 's3', 'cp', str(index_file), f's3://{bucket}/android/v1/latest.json',
         '--content-type', 'application/json', '--cache-control', 'public, max-age=300'],
        ['aws', 'cloudfront', 'create-invalidation', '--distribution-id', DISTRIBUTION,
         '--paths', '/android/v1/latest.json'],
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('apk')
    parser.add_argument('--for-real', action='store_true')
    args = parser.parse_args(argv)
    package, code, name = sign._badging(args.apk)
    if package != PACKAGE:
        raise ValueError(f'{args.apk} is {package}, not {PACKAGE}')
    index = index_for(args.apk, name, code)
    for command in publish(args.apk, index, live_code=live_code(), dry_run=not args.for_real):
        print(' '.join(command))
    print(json.dumps(index, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())

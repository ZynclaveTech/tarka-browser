#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Signs a Tark for Android release with the release key, on this Mac (A5).

    sign.py APK AAB OUTDIR

The build machine's ChromePublic.apk and ChromePublic.aab carry Chromium's
debug key. The APK is signed again with apksigner (v1-v3; v4 off), the app
bundle with jarsigner after its old signature files are dropped (Play takes
one signer). Both must have the same package and version. Writes
OUTDIR/tark-<version name>.apk and .aab and prints the APK's sha256 and the
certificate's sha256. Key and password come from ~/.config/tark/
(android/release/keygen.sh); the password is passed to the tools as a file,
never on a command line.
"""

import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

SDK = pathlib.Path.home() / 'Library' / 'Android' / 'sdk'
KEYSTORE = pathlib.Path.home() / '.config' / 'tark' / 'android-release.p12'
PASSFILE = pathlib.Path.home() / '.config' / 'tark' / 'android-release.pass'
ALIAS = 'tark'
# The signature files of an old signer: jarsigner adds its own beside them.
_VERSION_NAME = re.compile(r'\d+\.\d+\.\d+\.\d+-r\d{1,2}')
_SIGNATURE = re.compile(r'^META-INF/([^/]+\.(SF|RSA|DSA|EC)|MANIFEST\.MF)$', re.IGNORECASE)


def _build_tool(name):
    return str(sorted((SDK / 'build-tools').glob('*'))[-1] / name)


def _badging(apk_like):
    out = subprocess.run([_build_tool('aapt2'), 'dump', 'badging', str(apk_like)],
                         capture_output=True, text=True, check=True).stdout
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", out)
    if not m:
        raise ValueError(f'no package line in {apk_like}')
    return m.group(1), int(m.group(2)), m.group(3)


def _bundle_badging(aab):
    """The base module's manifest, read as a proto-format APK."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(aab) as bundle:
        probe = pathlib.Path(tmp) / 'base.apk'
        with zipfile.ZipFile(probe, 'w') as out:
            out.writestr('AndroidManifest.xml', bundle.read('base/manifest/AndroidManifest.xml'))
            out.writestr('resources.pb', bundle.read('base/resources.pb'))
        return _badging(probe)


def _cert_sha256_of_keystore(keystore, passfile):
    out = subprocess.run(['keytool', '-list', '-v', '-keystore', str(keystore), '-alias', ALIAS,
                          '-storepass:file', str(passfile)], capture_output=True, text=True, check=True).stdout
    line = next(l for l in out.splitlines() if l.strip().startswith('SHA256:'))
    return line.split(':', 1)[1].strip().replace(':', '').lower()


def sign_apk(apk_in, apk_out, keystore=KEYSTORE, passfile=PASSFILE):
    subprocess.run([_build_tool('apksigner'), 'sign', '--ks', str(keystore), '--ks-key-alias', ALIAS,
                    # PKCS12: the key's password is the store's. Given one file twice,
                    # apksigner would read the key's from its second line.
                    '--ks-pass', f'file:{passfile}',
                    '--v4-signing-enabled', 'false', '--out', str(apk_out), str(apk_in)],
                   check=True, capture_output=True)
    out = subprocess.run([_build_tool('apksigner'), 'verify', '--print-certs', str(apk_out)],
                         capture_output=True, text=True, check=True).stdout
    digests = re.findall(r'certificate SHA-256 digest: ([0-9a-f]{64})', out)
    if digests != [_cert_sha256_of_keystore(keystore, passfile)]:
        raise ValueError(f'{apk_out} is not signed by the release key alone')
    pathlib.Path(str(apk_out) + '.idsig').unlink(missing_ok=True)
    return digests[0]


def sign_aab(aab_in, aab_out, keystore=KEYSTORE, passfile=PASSFILE):
    with zipfile.ZipFile(aab_in) as src, zipfile.ZipFile(aab_out, 'w') as dst:
        for info in src.infolist():
            if not _SIGNATURE.match(info.filename):
                dst.writestr(info, src.read(info))
    subprocess.run(['jarsigner', '-sigalg', 'SHA256withRSA', '-digestalg', 'SHA-256', '-keystore', str(keystore),
                    '-storepass:file', str(passfile), '-keypass:file', str(passfile), '-sigfile', 'TARK',
                    str(aab_out), ALIAS], check=True, capture_output=True)
    # Not -strict: Android signing certificates are self-signed, which
    # -strict counts as an error.
    verified = subprocess.run(['jarsigner', '-verify', str(aab_out)], capture_output=True, text=True).stdout
    if 'jar verified.' not in verified:
        raise ValueError(f'{aab_out} does not verify: {verified.strip()}')
    out = subprocess.run(['keytool', '-printcert', '-jarfile', str(aab_out)],
                         capture_output=True, text=True, check=True).stdout
    digests = [l.split(':', 1)[1].strip().replace(':', '').lower() for l in out.splitlines()
               if l.strip().startswith('SHA256:')]
    if digests != [_cert_sha256_of_keystore(keystore, passfile)]:
        raise ValueError(f'{aab_out} is not signed by the release key alone')
    return digests[0]


def release(apk, aab, outdir, keystore=KEYSTORE, passfile=PASSFILE):
    package, code, name = _badging(apk)
    if _bundle_badging(aab) != (package, code, name):
        raise ValueError(f'the APK and the bundle differ in package or version: {apk}, {aab}')
    # The file names come from the APK's own version name: only Tark's shape
    # (android/release/version.py) is used, and a release is never replaced.
    if not _VERSION_NAME.fullmatch(name):
        raise ValueError(f'unexpected version name {name!r} in {apk}')
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    apk_out = outdir / f'tark-{name}.apk'
    for out in (apk_out, outdir / f'tark-{name}.aab'):
        if out.exists():
            raise ValueError(f'{out} exists; a release is never overwritten')
    cert = sign_apk(apk, apk_out, keystore, passfile)
    if sign_aab(aab, outdir / f'tark-{name}.aab', keystore, passfile) != cert:
        raise ValueError('the APK and the bundle came out with different certificates')
    return {'version_name': name, 'version_code': code, 'cert_sha256': cert,
            'apk_sha256': hashlib.sha256(apk_out.read_bytes()).hexdigest(), 'apk_size': apk_out.stat().st_size}


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    r = release(*argv[1:4])
    print(f"{r['version_name']} {r['version_code']}\napk_sha256 {r['apk_sha256']}\ncert_sha256 {r['cert_sha256']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

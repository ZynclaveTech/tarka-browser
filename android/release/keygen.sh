#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   android/release/keygen.sh "ORGANISATION"
#
# Makes Tark for Android's release key (A5) on this Mac: the app signing key
# for Play App Signing ("use my own key") and the direct APK's key. RSA 4096,
# PKCS12, alias tark, valid 10,000 days. The key and its password stay in
# ~/.config/tark/ (mode 600); nothing secret is printed. Losing it strands
# every install: back it up offline before using it.
set -euo pipefail
org="${1:?usage: $0 ORGANISATION}"
dir="$HOME/.config/tark"
key="$dir/android-release.p12"
pass="$dir/android-release.pass"
for f in "$key" "$pass"; do
  if [[ -e $f ]]; then
    echo "$f exists; not overwriting the release key" >&2
    exit 1
  fi
done
mkdir -p "$dir"
chmod 700 "$dir"
umask 077
openssl rand -base64 32 > "$pass"
keytool -genkeypair -keyalg RSA -keysize 4096 -validity 10000 -alias tark -storetype PKCS12 \
  -keystore "$key" -storepass:file "$pass" -dname "CN=Tark, O=$org" >/dev/null 2>&1
chmod 600 "$key" "$pass"
fingerprint=$(keytool -list -v -keystore "$key" -storepass:file "$pass" | awk '/SHA256:/ {print $2; exit}')
cat <<MSG
Tark's Android release key is in $key
(its password in $pass; both mode 600).
Certificate SHA-256: $fingerprint

Back up both files offline now (for example on two encrypted USB drives kept
apart). Every Play and direct install of Tark trusts this key; without it no
update can ever be signed again.
MSG

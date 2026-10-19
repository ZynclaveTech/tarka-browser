#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   utils/package_dmg.sh APP OUT.dmg
#
# Packages a signed APP into an APFS disk image with an /Applications link
# (M5). It replaces chrome/installer/mac/pkg-dmg, whose HFS hybrid image
# gives every file a com.apple.FinderInfo attribute: an app dragged out of
# it fails `codesign --verify --deep --strict` ("resource fork, Finder
# information, or similar detritus not allowed"), which Gatekeeper can
# report as a damaged app. The app is copied without extended attributes,
# and the image is checked before it is kept.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 APP OUT.dmg" >&2
  exit 2
fi
app="${1%/}"
out="$2"
name="$(basename "$app" .app)"

stage="$(mktemp -d)"
mount=""
cleanup() {
  [[ -z "$mount" ]] || hdiutil detach -quiet "$mount" || true
  rm -rf "$stage"
}
trap cleanup EXIT

ditto --noextattr --norsrc "$app" "$stage/$name.app"
# Refuse an app whose signature is already broken: notarization would fail
# later, or worse, an ad-hoc build would ship as "damaged".
codesign --verify --deep --strict "$stage/$name.app"
ln -s /Applications "$stage/Applications"

rm -f "$out"
if ! hdiutil create -quiet -volname "$name" -srcfolder "$stage" \
    -fs APFS -format ULFO "$out"; then
  rm -f "$out"
  exit 1
fi

# Check what a person will drag out of the image.
mount="$(hdiutil attach -nobrowse -readonly "$out" | awk -F'\t' '/\/Volumes\//{print $NF}')"
detritus="$(find "$mount/$name.app" -xattrname com.apple.FinderInfo | head -1)"
if [[ -n "$detritus" ]] || ! codesign --verify --deep --strict "$mount/$name.app"; then
  echo "error: the app inside $out does not verify (${detritus:-signature})" >&2
  hdiutil detach -quiet "$mount" || true
  mount=""
  rm -f "$out"
  exit 1
fi
echo "packaged $out"

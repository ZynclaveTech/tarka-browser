#!/usr/bin/env bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Tark (D4 Phase 3): puts libtark_apple_speech.dylib, the Swift library over
# macOS 26's speech and translation (built by Xcode's swiftc in the GN action
# //chrome/browser/tark_captions/apple:tark_apple_speech), into Tark.app's
# Frameworks. sign_and_package_app.sh signs it with the app.
#
#   install_apple_speech.sh APP DYLIB
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 APP DYLIB" >&2
  exit 2
fi
app="${1%/}"
source_dylib="$2"
dylib_name="libtark_apple_speech.dylib"

if [[ ! -f "$source_dylib" || -L "$source_dylib" ]]; then
  echo "error: $source_dylib is missing or a link" >&2
  exit 1
fi
archs="$(lipo -archs "$source_dylib")"
if [[ "$archs" != "arm64" ]]; then
  echo "error: $dylib_name is '$archs', expected arm64 only" >&2
  exit 1
fi
# Built for macOS 26: the speech APIs it calls exist only there.
minos="$(vtool -show-build "$source_dylib" | awk '$1 == "minos" {print $2}' | head -1)"
if [[ "${minos%%.*}" -lt 26 ]]; then
  echo "error: $dylib_name is built for macOS $minos, expected 26 or later" >&2
  exit 1
fi

frameworks="$app/Contents/Frameworks"
mkdir -p "$frameworks"
cp -f "$source_dylib" "$frameworks/$dylib_name"
chmod 755 "$frameworks/$dylib_name"
echo "installed $dylib_name into $frameworks"

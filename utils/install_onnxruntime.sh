#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   utils/install_onnxruntime.sh APP ONNXRUNTIME_RELEASE_DIR
#
# Puts ONNX Runtime into APP for live captions (D4), before signing: copies
# the release's versioned dylib (lib/libonnxruntime.1.31.0.dylib, not its
# links) into Contents/Frameworks. The speech utility process dlopen()s it
# by that path (components/tark_captions/ort_runtime.cc), so nothing links
# against it. sign_and_package_app.sh then signs it with Tark's identity:
# helpers run with library validation, so Microsoft's own signature (another
# team) would not load there. arm64 only, like Tark.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 APP ONNXRUNTIME_RELEASE_DIR" >&2
  exit 2
fi
app="${1%/}"
release="${2%/}"
dylib_name="libonnxruntime.1.31.0.dylib"
source_dylib="$release/lib/$dylib_name"

if [[ ! -f "$source_dylib" || -L "$source_dylib" ]]; then
  echo "error: $source_dylib is missing or a link" >&2
  exit 1
fi
archs="$(lipo -archs "$source_dylib")"
if [[ "$archs" != "arm64" ]]; then
  echo "error: $dylib_name is '$archs', expected arm64 only" >&2
  exit 1
fi

frameworks="$app/Contents/Frameworks"
mkdir -p "$frameworks"
cp -f "$source_dylib" "$frameworks/$dylib_name"
chmod 755 "$frameworks/$dylib_name"
echo "installed $dylib_name into $frameworks"

#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   ort.sh OUT_DIR
#
# Tark for Android's live captions: the official ONNX Runtime Android AAR
# from Maven Central, pinned by version and sha256. OUT_DIR
# (third_party/tark_onnxruntime) gets include/ (the C API headers the engine
# compiles against), arm64-v8a/libonnxruntime.so (stored in the APK and
# loaded at run time by the captions process) and README.chromium, LICENSE
# and ThirdPartyNotices.txt for Tark's credits (android/captions/onnxruntime).
set -euo pipefail
VERSION=1.31.0
SHA256=72683787a80d0608a3121b967d8e1239aef48286826661c953211626690540a7
URL=https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/$VERSION/onnxruntime-android-$VERSION.aar
HERE=$(cd "$(dirname "$0")" && pwd)

out=${1:?usage: ort.sh OUT_DIR}
mkdir -p "$out"
aar=$out/onnxruntime-android-$VERSION.aar
if [[ ! -f $aar ]] || ! echo "$SHA256  $aar" | sha256sum -c --quiet - 2>/dev/null; then
  curl -fsSL -o "$aar.part" "$URL"
  echo "$SHA256  $aar.part" | sha256sum -c --quiet - || { echo "ort.sh: sha256 mismatch" >&2; rm -f "$aar.part"; exit 1; }
  mv "$aar.part" "$aar"
fi
rm -rf "$out/include" "$out/arm64-v8a"
python3 - "$aar" "$out" <<'PY'
import pathlib, sys, zipfile
aar, out = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(aar) as z:
    for name in z.namelist():
        if name.startswith('headers/') and name.endswith('.h'):
            dest = out / 'include' / pathlib.Path(name).name
        elif name == 'jni/arm64-v8a/libonnxruntime.so':
            dest = out / 'arm64-v8a' / 'libonnxruntime.so'
        else:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(z.read(name))
PY
for f in README.chromium LICENSE ThirdPartyNotices.txt; do
  cp "$HERE/onnxruntime/$f" "$out/$f"
done
echo "onnxruntime $VERSION arm64-v8a: $(stat -c %s "$out/arm64-v8a/libonnxruntime.so" 2>/dev/null || stat -f %z "$out/arm64-v8a/libonnxruntime.so") bytes"

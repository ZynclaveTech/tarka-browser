#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# build.sh <mac|sim|dev>: tark_captions' translator (from build.py's
# translate-src), upstream SentencePiece 0.2.0 with its bundled protobuf-lite,
# the //base shim and the C interface, linked with ONNX Runtime's static
# xcframework into translate_check (a command-line test for mac and sim).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARK="$(cd "$HERE/../.." && pwd)"
SRC_ROOT="${TRANSLATE_SRC_ROOT:-$TARK/build/ios/translate-src}"
SPM="${SPM_SRC:-$TARK/build/ios/sentencepiece-0.2.0}"
ORT="$TARK/build/ios/onnxruntime/x"
# pffft (the speech model's FFT, which asr_model.cc brings along), vendored.
PFFFT="$HERE/third_party/pffft/src"
case "$1" in
  mac) SDK=macosx; TARGET=arm64-apple-macos14.0; SLICE=macos-arm64_x86_64; UIKIT=() ;;
  sim) SDK=iphonesimulator; TARGET=arm64-apple-ios17.0-simulator; SLICE=ios-arm64_x86_64-simulator; UIKIT=(-framework UIKit) ;;
  dev) SDK=iphoneos; TARGET=arm64-apple-ios17.0; SLICE=ios-arm64; UIKIT=(-framework UIKit) ;;  # ONNX Runtime for iOS uses UIDevice
  *) echo "usage: build.sh mac|sim|dev" >&2; exit 2 ;;
esac
OUT="$HERE/out/$1"
mkdir -p "$OUT"
SYSROOT=$(xcrun --sdk $SDK --show-sdk-path)
COMMON=(-target $TARGET -isysroot "$SYSROOT" -O2 -DNDEBUG)
# SentencePiece's own warnings are upstream's; Tark's files build with -Werror.
SPM_FLAGS=("${COMMON[@]}" -std=c++17 -DHAVE_PTHREAD=1 -w
           -I"$SPM" -I"$SPM/src" -I"$SPM/src/builtin_pb" -I"$SPM/third_party" -I"$SPM/third_party/protobuf-lite")
TARK_FLAGS=("${COMMON[@]}" -std=c++20 -Wall -Wextra -Werror -Wno-unused-parameter
            -I"$HERE/shim" -I"$SRC_ROOT" -I"$HERE" -I"$ORT/Headers"
            -I"$SPM/src" -I"$SPM/third_party" -I"$SPM" -I"$PFFFT/../../..")
[ -f "$SPM/config.h" ] || printf '#pragma once\n#define VERSION "0.2.0"\n#define PACKAGE "sentencepiece"\n#define PACKAGE_STRING "sentencepiece"\n' > "$SPM/config.h"

OBJS=()
# macOS's bash 3.2 has no namerefs: one helper per flag set.
object() { echo "$OUT/$(echo "$1" | tr '/' '_' | sed 's/\.cc$/.o/')"; }
spm() { xcrun clang++ "${SPM_FLAGS[@]}" -c "$1" -o "$(object "$1")"; OBJS+=("$(object "$1")"); }
tark() { xcrun clang++ "${TARK_FLAGS[@]}" -c "$1" -o "$(object "$1")"; OBJS+=("$(object "$1")"); }
for f in bpe_model char_model error filesystem model_factory model_interface normalizer \
         sentencepiece_processor unigram_model util word_model; do
  spm "$SPM/src/$f.cc"
done
for f in sentencepiece sentencepiece_model; do spm "$SPM/src/builtin_pb/$f.pb.cc"; done
for f in arena arenastring bytestream coded_stream common extension_set generated_enum_util \
         generated_message_table_driven_lite generated_message_util implicit_weak_message int128 \
         message_lite parse_context repeated_field status statusor stringpiece stringprintf \
         structurally_valid strutil time wire_format_lite zero_copy_stream zero_copy_stream_impl \
         zero_copy_stream_impl_lite; do
  spm "$SPM/third_party/protobuf-lite/$f.cc"
done
spm "$SPM/third_party/absl/flags/flag.cc"
xcrun clang "${COMMON[@]}" -w -c "$PFFFT/pffft.c" -o "$OUT/pffft.o"
OBJS+=("$OUT/pffft.o")
# asr_model has the language codes; it brings mel_frontend and pffft.
for f in translation_engine indic_text english_text model_source ort_runtime asr_model mel_frontend; do
  tark "$SRC_ROOT/components/tark_captions/$f.cc"
done
tark "$HERE/tark_translate_c.cc"
tark "$HERE/translate_check.cc"
xcrun clang++ "${COMMON[@]}" "${OBJS[@]}" "$ORT/onnxruntime.xcframework/$SLICE/onnxruntime.framework/onnxruntime" \
  -licucore -framework Foundation -framework CoreML -framework Network "${UIKIT[@]}" -Wl,-dead_strip \
  -o "$OUT/translate_check"
ls -la "$OUT/translate_check"

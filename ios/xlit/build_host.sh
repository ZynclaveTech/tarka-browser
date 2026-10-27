#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
# Builds the tark_xlit engine with the //base shim for the Mac host (plain
# clang++, Accelerate) and runs golden_check. Exit status is golden_check's.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TARK="$(cd "$HERE/../.." && pwd)"
SRC_ROOT="${XLIT_SRC_ROOT:-$TARK/build/ios/xlit-src}"
MODEL="${XLIT_MODEL:-$TARK/build/src/third_party/indicxlit/xlit-model.bin}"
WORDS_DIR="${XLIT_WORDS_DIR:-$TARK/build/ios/xlit-files}"
GOLDEN="${XLIT_GOLDEN:-$TARK/resources/xlit/golden.tsv}"
OUT="${XLIT_OUT:-$HERE/out}"

ENGINE="$SRC_ROOT/components/tark_xlit"
SOURCES=(
  "$ENGINE/model.cc"
  "$ENGINE/word_list.cc"
  "$ENGINE/transliterator.cc"
  "$ENGINE/languages.cc"
  "$ENGINE/blas_accelerate.cc"
  "$HERE/shim/base_shim.cc"
  "$HERE/tark_xlit_c.cc"
  "$HERE/golden_check.cc"
)

mkdir -p "$OUT"
# The same flags as BrowserKit's TarkXlitCore target: Apple's classic CBLAS
# (the new LAPACK headers need iOS 16.4; Tark for iOS supports 15), with its
# deprecation warning off.
FLAGS=(-std=c++20 -O2 -Wall -Wextra -Werror -Wno-unused-parameter
       -Wno-deprecated-declarations
       -I "$HERE/shim" -I "$SRC_ROOT" -I "$HERE")
OBJS=()
for src in "${SOURCES[@]}"; do
  obj="$OUT/$(basename "${src%.cc}").o"
  clang++ "${FLAGS[@]}" -c "$src" -o "$obj"
  OBJS+=("$obj")
done
clang++ "${OBJS[@]}" -framework Accelerate -o "$OUT/golden_check"

"$OUT/golden_check" "$MODEL" "$GOLDEN" "$WORDS_DIR"

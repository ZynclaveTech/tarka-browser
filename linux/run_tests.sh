#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   linux/run_tests.sh SRC REPORT
#
# L2: builds and runs Tark's own unit tests on Linux, in upstream's build
# image after the browser build: captions (with ONNX Runtime itself loaded,
# as Windows' verify.ps1 does), the speech service, transliteration. Each
# program's results go to REPORT/<name>.xml and its output to REPORT/<name>.log;
# any failure, or a program that runs no test, fails the script.
set -uo pipefail
src=$1; report=$2
out=$src/out/Default
mkdir -p "$report"
programs="tark_captions_unittests tark_speech_unittests tark_xlit_unittests"
ninja -C "$out" $programs || exit 1

fails=0
run() {  # NAME PROGRAM ARGS...
  local name=$1 program=$2; shift 2
  "$out/$program" --gtest_output="xml:$report/$name.xml" "$@" > "$report/$name.log" 2>&1
  local code=$?
  if (( code != 0 )) || ! grep -q '^\[  PASSED  \] [1-9]' "$report/$name.log"; then
    echo "FAIL $name (exit $code)"; fails=$((fails + 1))
  else
    echo "ok $name: $(grep '^\[  PASSED  \]' "$report/$name.log")"
  fi
}
run captions tark_captions_unittests
run speech tark_speech_unittests
run xlit tark_xlit_unittests
# ONNX Runtime itself, loaded from where the browser loads it, running a real
# model (Silero VAD, as Windows' verify.ps1 does). None may be skipped.
models=$report/models
mkdir -p "$models"
if curl -sSfL -o "$models/silero_vad.onnx" https://gettarka.com/models/captions/v1/silero_vad.onnx &&
    echo "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3  $models/silero_vad.onnx" | sha256sum -c --quiet; then
  TARK_CAPTIONS_ORT=$out/libonnxruntime.so.1 TARK_CAPTIONS_MODELS=$models \
    run onnxruntime tark_captions_unittests --gtest_filter='OrtRuntimeTest.*' --single-process-tests
  if grep -q '\[  SKIPPED \]' "$report/onnxruntime.log" ||
      ! grep -qE '^\[  PASSED  \] ([3-9]|[1-9][0-9]+) test' "$report/onnxruntime.log"; then
    echo "FAIL onnxruntime: a test was skipped or fewer than 3 ran"; fails=$((fails + 1))
  fi
else
  echo "FAIL onnxruntime: could not fetch silero_vad.onnx with the expected sha256"; fails=$((fails + 1))
fi
rm -rf "$models"
exit $(( fails > 0 ))

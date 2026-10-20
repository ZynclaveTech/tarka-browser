# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Sourced by dev.sh (setup) and build.sh; defines _install_captions_credits
# (D4, live captions). The caller sets _root_dir and _src_dir, and has
# unpacked ONNX Runtime into third_party/tark_onnxruntime.
#
# about:credits lists what live captions run on: tools/licenses finds a
# README.chromium (and its LICENSE) in each third_party folder. ONNX Runtime
# keeps its release's LICENSE; the models and the ported code bring theirs.

_install_captions_credits() {
  local credits="$_root_dir/resources/captions/credits"
  local third_party="$_src_dir/third_party"

  cp "$credits/onnxruntime/README.chromium" "$third_party/tark_onnxruntime/"
  mkdir -p "$third_party/tark_indicconformer" "$third_party/tark_silero_vad"
  cp "$credits/indicconformer/README.chromium" "$credits/indicconformer/LICENSE" \
    "$third_party/tark_indicconformer/"
  cp "$credits/silero_vad/README.chromium" "$credits/silero_vad/LICENSE" \
    "$third_party/tark_silero_vad/"
  # Phase 2: the translation model and the MIT code the text steps are
  # ported from.
  local name
  # Phase 3: the spoken-language-ID model.
  for name in indictrans2 indicnlp indictranstoolkit sacremoses voxlingua_ecapa; do
    mkdir -p "$third_party/tark_$name"
    cp "$credits/$name/README.chromium" "$credits/$name/LICENSE" "$third_party/tark_$name/"
  done
}

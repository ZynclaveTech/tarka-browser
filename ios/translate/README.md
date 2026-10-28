# Page translation's engine for iOS

`tark_captions`' translator (IndicTrans2 200M distilled, int8, greedy) — the
C++ Tark for Mac and Android ship — compiled for iOS outside Chromium:

- `tark_translate_c.{h,cc}` — the C interface Swift uses. One translator
  holds one direction's model; destroying it frees the memory (Tark keeps one
  model in memory at a time).
- `shim/` — the slice of Chromium's `//base` the translator uses, ICU's
  character properties from iOS's own `libicucore`, and SentencePiece's
  include path. Started from the captions spike's shim.
- `third_party/pffft/` — vendored (the speech frontend in `asr_model.cc`,
  which also has the language codes, needs it).
- `build.sh mac|sim|dev` — builds `translate_check` (sentences on stdin,
  translations and times out) from `build.py translate`'s sources:
  `build/ios/translate-src` (the Mac patches), SentencePiece 0.2.0 and ONNX
  Runtime 1.30.0 (both pinned in build.py).

`build.py translate` puts the same files into BrowserKit's
`TarkTranslateCore` target (`ios/patches/translate-engine.patch`).

Known: only Hindi, Tamil and Bengali exist in the engine today (the design
asks for all 22); ONNX Runtime 1.30.0 for iOS is built for iOS 15.1 while
Tark supports 15.0.

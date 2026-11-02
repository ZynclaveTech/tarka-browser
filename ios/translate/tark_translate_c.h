// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// Tark for iOS: page translation's C interface to tark_captions'
// TranslationEngine (IndicTrans2 200M distilled, int8, greedy). One
// translator holds one direction's model; destroying it frees the memory, so
// Indian ↔ Indian translates every sentence into English, then swaps models
// (Tark keeps one model in memory at a time). Not thread-safe; one sentence
// at a time per translator.
#ifndef TARK_TRANSLATE_C_H_
#define TARK_TRANSLATE_C_H_

#ifdef __cplusplus
extern "C" {
#endif

typedef struct TarkTranslator TarkTranslator;

typedef enum {
  TARK_TRANSLATE_INDIC_TO_ENGLISH = 0,  // models_dir/it2_indic_en
  TARK_TRANSLATE_ENGLISH_TO_INDIC = 1,  // models_dir/it2_en_indic
} TarkTranslateDirection;

// The direction's model loads on the first sentence. Null if ONNX Runtime
// is unavailable.
TarkTranslator* tark_translator_create(const char* models_dir, TarkTranslateDirection direction);
void tark_translator_destroy(TarkTranslator* translator);

// `text` (UTF-8) translated: from `language` ("hi", "ta", "bn") into
// English, or from English into `language`. Free the result with
// tark_translate_free. Null when the model is missing or fails; "" for a
// blank sentence.
char* tark_translator_translate(TarkTranslator* translator, const char* text, const char* language);
void tark_translate_free(char* text);

#ifdef __cplusplus
}
#endif

#endif  // TARK_TRANSLATE_C_H_

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "tark_translate_c.h"

#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <optional>
#include <string>

#include "base/files/file_path.h"
#include "components/tark_captions/model_source.h"
#include "components/tark_captions/ort_runtime.h"
#include "components/tark_captions/translation_engine.h"

using tark_captions::TranslationDirection;

struct TarkTranslator {
  std::unique_ptr<tark_captions::TranslationEngine> engine;
  TarkTranslateDirection direction;
};

TarkTranslator* tark_translator_create(const char* models_dir, TarkTranslateDirection direction) {
  const bool to_english = direction == TARK_TRANSLATE_INDIC_TO_ENGLISH;
  // Only this direction's folder, so the engine never loads the other model.
  std::map<TranslationDirection, std::unique_ptr<tark_captions::ModelSource>> sources;
  sources[to_english ? TranslationDirection::kIndicToEnglish : TranslationDirection::kEnglishToIndic] =
      std::make_unique<tark_captions::DirectorySource>(
          base::FilePath(models_dir).Append(to_english ? "it2_indic_en" : "it2_en_indic"));
  // ONNX Runtime is linked into the app; the path is not used (the shim's
  // native_library hands back the linked API).
  auto engine = tark_captions::TranslationEngine::Create(
      tark_captions::OrtRuntime::Load(base::FilePath("linked")), std::move(sources));
  if (!engine) {
    return nullptr;
  }
  return new TarkTranslator{std::move(engine), direction};
}

void tark_translator_destroy(TarkTranslator* translator) {
  delete translator;
}

char* tark_translator_translate(TarkTranslator* translator, const char* text, const char* language) {
  if (!translator || !text || !language) {
    return nullptr;
  }
  std::optional<std::string> out;
  if (translator->direction == TARK_TRANSLATE_INDIC_TO_ENGLISH) {
    out = translator->engine->TranslateFrom(text, language, tark_captions::Target::kEnglish);
  } else {
    std::optional<tark_captions::Target> target = tark_captions::TargetFromCode(language);
    if (!target) {
      return nullptr;
    }
    out = translator->engine->TranslateEnglish(text, *target);
  }
  if (!out) {
    return nullptr;
  }
  return strdup(out->c_str());
}

void tark_translate_free(char* text) {
  free(text);
}

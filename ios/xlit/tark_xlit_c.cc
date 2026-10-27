// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "tark_xlit_c.h"

#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/files/file_path.h"
#include "base/files/memory_mapped_file.h"
#include "base/strings/utf_string_conversions.h"
#include "components/tark_xlit/languages.h"
#include "components/tark_xlit/model.h"
#include "components/tark_xlit/transliterator.h"
#include "components/tark_xlit/word_list.h"

struct TarkXlit {
  std::mutex mutex;
  std::unique_ptr<tark_xlit::Transliterator> transliterator;
};

namespace {

char* CopyToMalloc(const std::string& text) {
  char* out = static_cast<char*>(std::malloc(text.size() + 1));
  if (out) {
    std::memcpy(out, text.c_str(), text.size() + 1);
  }
  return out;
}

// Tags and CLDR names are plain text without quotes or backslashes, so they
// go into the JSON as they are.
void AppendLanguage(std::string& json, const tark_xlit::Language& language) {
  if (json.size() > 1) {
    json += ",";
  }
  json += "{\"tag\":\"" + std::string(language.tag) + "\",\"name\":\"" +
          base::UTF16ToUTF8(language.native_name) + "\"}";
}

}  // namespace

extern "C" {

TarkXlit* tark_xlit_new(const char* model_path,
                         const char* const* word_paths,
                         size_t n) {
  if (!model_path || (n > 0 && !word_paths)) {
    return nullptr;
  }
  // As LoadResourcesFromDirectory(): the model is converted into memory, so
  // its mapping is dropped after Load().
  std::unique_ptr<tark_xlit::Model> model;
  {
    base::MemoryMappedFile model_file;
    if (!model_file.Initialize(base::FilePath(model_path))) {
      return nullptr;
    }
    model = tark_xlit::Model::Load(model_file.bytes());
  }
  if (!model) {
    return nullptr;
  }
  std::unique_ptr<tark_xlit::WordList> words;
  if (n > 0) {
    std::vector<std::unique_ptr<base::MemoryMappedFile>> files;
    for (size_t i = 0; i < n; ++i) {
      if (!word_paths[i]) {
        return nullptr;
      }
      auto file = std::make_unique<base::MemoryMappedFile>();
      if (!file->Initialize(base::FilePath(word_paths[i]))) {
        return nullptr;
      }
      files.push_back(std::move(file));
    }
    words = tark_xlit::WordList::Load(std::move(files));
    if (!words) {
      return nullptr;
    }
  }
  auto handle = std::make_unique<TarkXlit>();
  handle->transliterator = std::make_unique<tark_xlit::Transliterator>(
      std::move(model), std::move(words));
  return handle.release();
}

char* tark_xlit_phrase(TarkXlit* handle, const char* input, const char* tag) {
  if (!handle || !input || !tag) {
    return nullptr;
  }
  const std::u16string text = base::UTF8ToUTF16(input);
  std::optional<std::u16string> out;
  {
    std::lock_guard<std::mutex> lock(handle->mutex);
    out = handle->transliterator->Phrase(text, tag);
  }
  return out ? CopyToMalloc(base::UTF16ToUTF8(*out)) : nullptr;
}

int tark_xlit_looks_transliterable(const char* text) {
  return text && tark_xlit::LooksTransliterable(base::UTF8ToUTF16(text)) ? 1
                                                                         : 0;
}

char* tark_xlit_row_languages(const char* accept_languages) {
  std::string json = "[";
  for (const tark_xlit::Language* language :
       tark_xlit::RowLanguages(accept_languages ? accept_languages : "")) {
    AppendLanguage(json, *language);
  }
  json += "]";
  return CopyToMalloc(json);
}

char* tark_xlit_all_languages(void) {
  std::string json = "[";
  for (const tark_xlit::Language& language : tark_xlit::AllLanguages()) {
    AppendLanguage(json, language);
  }
  json += "]";
  return CopyToMalloc(json);
}

char* tark_xlit_wikipedia_language(const char* query,
                                   const char* accept_languages) {
  if (!query) {
    return nullptr;
  }
  return CopyToMalloc(tark_xlit::WikipediaLanguage(
      base::UTF8ToUTF16(query), accept_languages ? accept_languages : ""));
}

void tark_xlit_string_free(char* text) {
  std::free(text);
}

void tark_xlit_free(TarkXlit* handle) {
  delete handle;
}

}  // extern "C"

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// C interface to Tark's transliteration engine (components/tark_xlit), for
// Swift. All strings are UTF-8, NUL-terminated.
//
// Thread safety: a handle is safe to use from any thread. Each handle holds
// one Transliterator (whose Phrase() fills a cache) behind its own mutex, so
// concurrent calls on one handle are serialised. For parallel work, make one
// handle per thread. tark_xlit_free must not race with other calls on the
// same handle.
#ifndef TARK_XLIT_C_H_
#define TARK_XLIT_C_H_

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Named TarkXlit, not tark_xlit: C++ already has a namespace tark_xlit.
typedef struct TarkXlit TarkXlit;

// Loads the TXLM model at `model_path` (read and converted into memory; the
// file is closed again) and the `n` TXLW word-list files at `word_paths`
// (memory-mapped for the handle's lifetime; one per language as
// xlit-words-<tag>.bin, a tag in several files is read from the first).
// `n` may be 0: then no word stays English and candidates are not rescored.
// NULL on a missing or invalid file. Blocks on file IO and converts the whole
// model (tens of milliseconds): do not call on the main thread.
TarkXlit* tark_xlit_new(const char* model_path,
                         const char* const* word_paths,
                         size_t n);

// `input` written in the script of the language `tag` (an IndicXlit tag such
// as "hi", "ta", "gom"); see Transliterator::Phrase. A malloc'd string to be
// released with tark_xlit_string_free, or NULL when `input` does not look like
// transliterable Latin text, when nothing in it changed, or on a NULL
// argument.
char* tark_xlit_phrase(TarkXlit* handle, const char* input, const char* tag);

// 1 when `text` might be an Indian-language word or phrase typed in Latin
// letters (tark_xlit::LooksTransliterable), else 0. Needs no handle.
int tark_xlit_looks_transliterable(const char* text);

// The languages to offer rows for, best first, from an accept-languages
// list such as "hi-IN,en-GB,ta" (tark_xlit::RowLanguages): a JSON array of
// {"tag": "hi", "name": "हिन्दी"}. Empty array when none is Indian. Release
// with tark_xlit_string_free.
char* tark_xlit_row_languages(const char* accept_languages);

// The Wikipedia language code for `query` (tark_xlit::WikipediaLanguage): "en"
// for Latin text, else the first language in `accept_languages` written in the
// query's script, else that script's default. Release with
// tark_xlit_string_free; NULL on a NULL query.
char* tark_xlit_wikipedia_language(const char* query,
                                   const char* accept_languages);
void tark_xlit_string_free(char* text);
void tark_xlit_free(TarkXlit* handle);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // TARK_XLIT_C_H_

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// C interface to adblock-rust for Tark for iOS. Strings are NUL-terminated
// UTF-8; free every returned string with tark_string_free.

#ifndef TARK_ADBLOCK_H_
#define TARK_ADBLOCK_H_

#include <stddef.h>
#include <stdint.h>

typedef struct TarkEngine TarkEngine;

TarkEngine *tark_engine_new(const uint8_t *dat, size_t dat_len, const char *resources_json);
void tark_engine_free(TarkEngine *engine);
char *tark_url_cosmetic_resources(const TarkEngine *engine, const char *url);
char *tark_hidden_class_id_selectors(const TarkEngine *engine, const char *classes_json,
                                     const char *ids_json, const char *exceptions_json);
void tark_string_free(char *s);

#endif  // TARK_ADBLOCK_H_

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/json/json_reader.h: a strict RFC 8259 parser (no
// comments, no trailing commas, UTF-8 validated, nesting at most 200 deep).
#ifndef TARK_SHIM_BASE_JSON_JSON_READER_H_
#define TARK_SHIM_BASE_JSON_JSON_READER_H_

#include <optional>
#include <string_view>

#include "base/values.h"

namespace base {

enum JSONParserOptions {
  JSON_PARSE_RFC = 0,
};

class JSONReader {
 public:
  // The value `json` holds, or nullopt when it is not valid JSON.
  static std::optional<Value> Read(std::string_view json,
                                   int options = JSON_PARSE_RFC);
  // As Read(), but nullopt also when the root is not an object.
  static std::optional<DictValue> ReadDict(std::string_view json,
                                           int options = JSON_PARSE_RFC);
};

}  // namespace base

#endif  // TARK_SHIM_BASE_JSON_JSON_READER_H_

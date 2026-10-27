// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/strings/string_number_conversions.h (NumberToString
// for integers, the only conversion the engine sources use).
#ifndef TARK_SHIM_BASE_STRINGS_STRING_NUMBER_CONVERSIONS_H_
#define TARK_SHIM_BASE_STRINGS_STRING_NUMBER_CONVERSIONS_H_

#include <concepts>
#include <string>

namespace base {
template <std::integral T>
std::string NumberToString(T value) {
  return std::to_string(value);
}
}  // namespace base

#endif  // TARK_SHIM_BASE_STRINGS_STRING_NUMBER_CONVERSIONS_H_

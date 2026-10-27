// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/strings/string_view_util.h.
#ifndef TARK_SHIM_BASE_STRINGS_STRING_VIEW_UTIL_H_
#define TARK_SHIM_BASE_STRINGS_STRING_VIEW_UTIL_H_

#include <cstdint>
#include <string_view>

#include "base/containers/span.h"

namespace base {

template <size_t N>
std::string_view as_string_view(span<const uint8_t, N> bytes) {
  return std::string_view(reinterpret_cast<const char*>(bytes.data()),
                          bytes.size());
}
template <size_t N>
std::string_view as_string_view(span<const char, N> chars) {
  return std::string_view(chars.data(), chars.size());
}

}  // namespace base

#endif  // TARK_SHIM_BASE_STRINGS_STRING_VIEW_UTIL_H_

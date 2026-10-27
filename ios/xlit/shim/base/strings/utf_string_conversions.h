// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/strings/utf_string_conversions.h. Like Chromium, an
// invalid sequence (bad UTF-8, lone surrogate) becomes U+FFFD.
#ifndef TARK_SHIM_BASE_STRINGS_UTF_STRING_CONVERSIONS_H_
#define TARK_SHIM_BASE_STRINGS_UTF_STRING_CONVERSIONS_H_

#include <string>
#include <string_view>

namespace base {
std::u16string UTF8ToUTF16(std::string_view utf8);
std::string UTF16ToUTF8(std::u16string_view utf16);
}  // namespace base

#endif  // TARK_SHIM_BASE_STRINGS_UTF_STRING_CONVERSIONS_H_

// Tark iOS: UTF-8 <-> UTF-16 as Chromium does it (invalid input becomes U+FFFD).
#pragma once
#include <string>
#include <string_view>
#include "base/strings/utf_string_conversion_utils.h"
namespace base {
inline std::u16string UTF8ToUTF16(std::string_view s) {
  std::u16string out;
  for (size_t i = 0; i < s.size(); ++i) {
    base_icu::UChar32 c;
    if (!ReadUnicodeCharacter(s, &i, &c)) { c = 0xFFFD; }
    if (c < 0x10000) {
      out.push_back(static_cast<char16_t>(c));
    } else {
      c -= 0x10000;
      out.push_back(static_cast<char16_t>(0xD800 + (c >> 10)));
      out.push_back(static_cast<char16_t>(0xDC00 + (c & 0x3FF)));
    }
  }
  return out;
}
inline std::string UTF16ToUTF8(std::u16string_view s) {
  std::string out;
  for (size_t i = 0; i < s.size(); ++i) {
    uint32_t c = s[i];
    if (c >= 0xD800 && c < 0xDC00 && i + 1 < s.size() && s[i + 1] >= 0xDC00 && s[i + 1] < 0xE000) {
      c = 0x10000 + ((c - 0xD800) << 10) + (s[i + 1] - 0xDC00);
      ++i;
    } else if (c >= 0xD800 && c < 0xE000) {
      c = 0xFFFD;
    }
    WriteUnicodeCharacter(static_cast<base_icu::UChar32>(c), &out);
  }
  return out;
}
}  // namespace base

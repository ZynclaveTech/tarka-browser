// Tark iOS: Chromium's UTF-8 code point reader and writer.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
namespace base_icu {
using UChar32 = int32_t;
}
namespace base {
inline bool IsValidCodepoint(uint32_t c) { return c < 0xD800u || (c >= 0xE000u && c <= 0x10FFFFu); }
// Reads the code point starting at *index; leaves *index on its last byte.
// An invalid sequence consumes one byte and returns false.
inline bool ReadUnicodeCharacter(std::string_view s, size_t* index, base_icu::UChar32* out) {
  const auto b = [&](size_t i) { return static_cast<uint8_t>(s[i]); };
  const size_t i = *index;
  const uint8_t lead = b(i);
  int len = lead < 0x80 ? 1 : (lead & 0xE0) == 0xC0 ? 2 : (lead & 0xF0) == 0xE0 ? 3 : (lead & 0xF8) == 0xF0 ? 4 : 0;
  if (len == 0 || i + len > s.size()) { *out = 0xFFFD; return false; }
  uint32_t c = len == 1 ? lead : lead & (0xFF >> (len + 1));
  for (int k = 1; k < len; ++k) {
    if ((b(i + k) & 0xC0) != 0x80) { *out = 0xFFFD; return false; }
    c = (c << 6) | (b(i + k) & 0x3F);
  }
  static constexpr uint32_t kMin[] = {0, 0, 0x80, 0x800, 0x10000};
  if (c < kMin[len] || !IsValidCodepoint(c)) { *out = 0xFFFD; return false; }
  *index = i + len - 1;
  *out = static_cast<base_icu::UChar32>(c);
  return true;
}
inline size_t WriteUnicodeCharacter(base_icu::UChar32 cp, std::string* out) {
  const uint32_t c = static_cast<uint32_t>(cp);
  const size_t before = out->size();
  if (c < 0x80) {
    out->push_back(static_cast<char>(c));
  } else if (c < 0x800) {
    out->push_back(static_cast<char>(0xC0 | (c >> 6)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  } else if (c < 0x10000) {
    out->push_back(static_cast<char>(0xE0 | (c >> 12)));
    out->push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  } else {
    out->push_back(static_cast<char>(0xF0 | (c >> 18)));
    out->push_back(static_cast<char>(0x80 | ((c >> 12) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  }
  return out->size() - before;
}
}  // namespace base

#pragma once
#include <string>
#include <string_view>
namespace base {
enum TrimPositions { TRIM_NONE = 0, TRIM_LEADING = 1, TRIM_TRAILING = 2, TRIM_ALL = 3 };
template <class Str, class View>
inline void ReplaceSubstringsAfterOffsetT(Str* s, size_t offset, View find, View with) {
  if (find.empty()) { return; }
  for (size_t p = s->find(find, offset); p != std::string::npos; p = s->find(find, p + with.size())) {
    s->replace(p, find.size(), with);
  }
}
inline void ReplaceSubstringsAfterOffset(std::string* s, size_t offset, std::string_view find, std::string_view with) {
  ReplaceSubstringsAfterOffsetT(s, offset, find, with);
}
inline void ReplaceSubstringsAfterOffset(std::u16string* s, size_t offset, std::u16string_view find,
                                         std::u16string_view with) {
  ReplaceSubstringsAfterOffsetT(s, offset, find, with);
}
// Chromium's kWhitespaceUTF16: Unicode White_Space.
inline constexpr char16_t kWhitespaceUTF16[] =
    u"\u0009\u000A\u000B\u000C\u000D\u0020\u0085\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    u"\u2006\u2007\u2008\u2009\u200A\u2028\u2029\u202F\u205F\u3000";
inline std::u16string_view TrimWhitespace(std::u16string_view s, TrimPositions where) {
  const std::u16string_view ws(kWhitespaceUTF16);
  size_t b = 0, e = s.size();
  if (where & TRIM_LEADING) { while (b < e && ws.find(s[b]) != std::u16string_view::npos) { ++b; } }
  if (where & TRIM_TRAILING) { while (e > b && ws.find(s[e - 1]) != std::u16string_view::npos) { --e; } }
  return s.substr(b, e - b);
}
inline std::string_view TrimWhitespaceASCII(std::string_view s, TrimPositions where) {
  auto ws = [](char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'; };
  size_t b = 0, e = s.size();
  if (where & TRIM_LEADING) { while (b < e && ws(s[b])) { ++b; } }
  if (where & TRIM_TRAILING) { while (e > b && ws(s[e - 1])) { --e; } }
  return s.substr(b, e - b);
}
}  // namespace base

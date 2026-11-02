// Tark iOS: base::SplitString for UTF-16 text on any of a set of separators.
#pragma once
#include <string>
#include <string_view>
#include <vector>
#include "base/strings/string_util.h"
namespace base {
enum WhitespaceHandling { KEEP_WHITESPACE, TRIM_WHITESPACE };
enum SplitResult { SPLIT_WANT_ALL, SPLIT_WANT_NONEMPTY };
inline std::vector<std::u16string> SplitString(std::u16string_view input, std::u16string_view separators,
                                               WhitespaceHandling whitespace, SplitResult result) {
  std::vector<std::u16string> out;
  size_t start = 0;
  while (start != std::u16string_view::npos) {
    const size_t end = input.find_first_of(separators, start);
    std::u16string_view piece = end == std::u16string_view::npos ? input.substr(start) : input.substr(start, end - start);
    if (whitespace == TRIM_WHITESPACE) { piece = TrimWhitespace(piece, TRIM_ALL); }
    if (result == SPLIT_WANT_ALL || !piece.empty()) { out.emplace_back(piece); }
    start = end == std::u16string_view::npos ? end : end + 1;
  }
  return out;
}
}  // namespace base

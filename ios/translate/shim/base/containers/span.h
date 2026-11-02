// Tark iOS: base::span is std::span (C++20).
#pragma once
#include <cstdint>
#include <span>
#include <string_view>
namespace base {
template <class T, std::size_t E = std::dynamic_extent>
using span = std::span<T, E>;
inline std::string_view as_string_view(std::span<const uint8_t> bytes) {
  return std::string_view(reinterpret_cast<const char*>(bytes.data()), bytes.size());
}
}  // namespace base

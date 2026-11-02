// Tark iOS: base::MakeFixedFlatSet, a constexpr set of a few values with contains().
#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
namespace base {
template <class T, size_t N>
struct fixed_flat_set {
  std::array<T, N> items;
  constexpr bool contains(const T& v) const {
    return std::find(items.begin(), items.end(), v) != items.end();
  }
};
template <class T, size_t N>
constexpr fixed_flat_set<T, N> MakeFixedFlatSet(const T (&values)[N]) {
  fixed_flat_set<T, N> set{};
  for (size_t i = 0; i < N; ++i) {
    set.items[i] = values[i];
  }
  return set;
}
}  // namespace base

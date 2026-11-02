// Tark iOS: base::flat_map as the translator uses it (built once from pairs, then looked up).
#pragma once
#include <functional>
#include <map>
#include <utility>
#include <vector>
namespace base {
template <class Key, class Mapped, class Compare = std::less<>>
class flat_map : public std::map<Key, Mapped, Compare> {
 public:
  flat_map() = default;
  explicit flat_map(std::vector<std::pair<Key, Mapped>> items)
      : std::map<Key, Mapped, Compare>(items.begin(), items.end()) {}
};
}  // namespace base

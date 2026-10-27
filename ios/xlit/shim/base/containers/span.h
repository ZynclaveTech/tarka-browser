// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Minimal stand-in for Chromium's //base/containers/span.h: std::span plus
// the base::span members the engine calls (sized first/last, take_first,
// copy_from), with first/last/subspan returning base::span.
#ifndef TARK_SHIM_BASE_CONTAINERS_SPAN_H_
#define TARK_SHIM_BASE_CONTAINERS_SPAN_H_

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <ranges>
#include <span>
#include <type_traits>

#include "base/check.h"

namespace base {

inline constexpr size_t dynamic_extent = std::dynamic_extent;

template <typename T, size_t Extent = dynamic_extent>
class span : public std::span<T, Extent> {
  using Base = std::span<T, Extent>;

 public:
  using Base::Base;
  constexpr span() noexcept
    requires(Extent == dynamic_extent || Extent == 0)
  = default;
  constexpr span(const Base& other) noexcept : Base(other) {}

  template <size_t Count>
  constexpr span<T, Count> first() const {
    CHECK(Count <= this->size());
    return span<T, Count>(this->data(), Count);
  }
  constexpr span<T> first(size_t count) const {
    CHECK(count <= this->size());
    return span<T>(this->data(), count);
  }
  template <size_t Count>
  constexpr span<T, Count> last() const {
    CHECK(Count <= this->size());
    return span<T, Count>(this->data() + this->size() - Count, Count);
  }
  constexpr span<T> last(size_t count) const {
    CHECK(count <= this->size());
    return span<T>(this->data() + this->size() - count, count);
  }
  // Chromium CHECKs the bounds; std::span leaves them undefined.
  constexpr span<T> subspan(size_t offset,
                            size_t count = dynamic_extent) const {
    CHECK(offset <= this->size());
    if (count == dynamic_extent) {
      count = this->size() - offset;
    }
    CHECK(count <= this->size() - offset);
    return span<T>(this->data() + offset, count);
  }

  // Removes and returns the first `Count` elements.
  template <size_t Count>
  constexpr span<T, Count> take_first()
    requires(Extent == dynamic_extent)
  {
    const span<T, Count> out = first<Count>();
    *this = subspan(Count);
    return out;
  }
  constexpr span<T> take_first(size_t count)
    requires(Extent == dynamic_extent)
  {
    const span<T> out = first(count);
    *this = subspan(count);
    return out;
  }

  // Copies `other`, which must have the same size, into this span.
  template <typename R>
  constexpr void copy_from(const R& other)
    requires(!std::is_const_v<T>)
  {
    CHECK(std::ranges::size(other) == this->size());
    std::ranges::copy(other, this->begin());
  }
};

template <typename T, size_t N>
span(T (&)[N]) -> span<T, N>;
template <typename R>
span(R&&) -> span<std::remove_reference_t<std::ranges::range_reference_t<R>>>;
template <typename T>
span(T*, size_t) -> span<T>;

template <typename T, size_t N>
span<const uint8_t> as_bytes(span<T, N> s) {
  return span<const uint8_t>(reinterpret_cast<const uint8_t*>(s.data()),
                             s.size_bytes());
}

}  // namespace base

template <typename T, size_t N>
inline constexpr bool std::ranges::enable_borrowed_range<base::span<T, N>> =
    true;
template <typename T, size_t N>
inline constexpr bool std::ranges::enable_view<base::span<T, N>> = true;

#endif  // TARK_SHIM_BASE_CONTAINERS_SPAN_H_

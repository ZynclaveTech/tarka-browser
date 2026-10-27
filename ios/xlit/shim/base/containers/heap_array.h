// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/containers/heap_array.h: an owned, fixed-size buffer.
#ifndef TARK_SHIM_BASE_CONTAINERS_HEAP_ARRAY_H_
#define TARK_SHIM_BASE_CONTAINERS_HEAP_ARRAY_H_

#include <algorithm>
#include <cstddef>
#include <memory>
#include <utility>

#include "base/check.h"
#include "base/containers/span.h"

namespace base {

template <typename T>
class HeapArray {
 public:
  HeapArray() = default;
  HeapArray(HeapArray&& other) noexcept
      : data_(std::move(other.data_)), size_(std::exchange(other.size_, 0)) {}
  HeapArray& operator=(HeapArray&& other) noexcept {
    data_ = std::move(other.data_);
    size_ = std::exchange(other.size_, 0);
    return *this;
  }

  // Value-initialised (zeroed) elements.
  static HeapArray WithSize(size_t size) {
    return HeapArray(std::make_unique<T[]>(size), size);
  }
  // Default-initialised elements (uninitialised for trivial T).
  static HeapArray Uninit(size_t size) {
    return HeapArray(std::make_unique_for_overwrite<T[]>(size), size);
  }
  static HeapArray CopiedFrom(span<const T> that) {
    HeapArray out = Uninit(that.size());
    std::ranges::copy(that, out.data());
    return out;
  }

  T* data() { return data_.get(); }
  const T* data() const { return data_.get(); }
  size_t size() const { return size_; }
  bool empty() const { return size_ == 0; }
  T* begin() { return data(); }
  T* end() { return data() + size_; }
  const T* begin() const { return data(); }
  const T* end() const { return data() + size_; }
  T& operator[](size_t i) {
    CHECK(i < size_);
    return data_[i];
  }
  const T& operator[](size_t i) const {
    CHECK(i < size_);
    return data_[i];
  }

  span<T> as_span() { return span<T>(data(), size_); }
  span<const T> as_span() const { return span<const T>(data(), size_); }
  span<T> subspan(size_t offset, size_t count = dynamic_extent) {
    return as_span().subspan(offset, count);
  }
  span<const T> subspan(size_t offset, size_t count = dynamic_extent) const {
    return as_span().subspan(offset, count);
  }
  span<T> first(size_t count) { return as_span().first(count); }
  span<const T> first(size_t count) const { return as_span().first(count); }

 private:
  HeapArray(std::unique_ptr<T[]> data, size_t size)
      : data_(std::move(data)), size_(size) {}

  std::unique_ptr<T[]> data_;
  size_t size_ = 0;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_CONTAINERS_HEAP_ARRAY_H_

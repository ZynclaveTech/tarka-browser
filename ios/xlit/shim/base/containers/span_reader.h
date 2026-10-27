// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/containers/span_reader.h (the members used).
#ifndef TARK_SHIM_BASE_CONTAINERS_SPAN_READER_H_
#define TARK_SHIM_BASE_CONTAINERS_SPAN_READER_H_

#include <cstddef>
#include <cstdint>
#include <optional>

#include "base/containers/span.h"
#include "base/numerics/byte_conversions.h"

namespace base {

template <typename T>
class SpanReader {
 public:
  explicit SpanReader(span<T> buffer) : buffer_(buffer) {}

  std::optional<span<T>> Read(size_t n) {
    if (n > buffer_.size()) {
      return std::nullopt;
    }
    num_read_ += n;
    return buffer_.take_first(n);
  }
  template <size_t N>
  std::optional<span<T, N>> Read() {
    if (N > buffer_.size()) {
      return std::nullopt;
    }
    num_read_ += N;
    return buffer_.template take_first<N>();
  }

  bool ReadU16LittleEndian(uint16_t& value) {
    const auto bytes = Read<2>();
    if (!bytes) {
      return false;
    }
    value = U16FromLittleEndian(*bytes);
    return true;
  }
  bool ReadU32LittleEndian(uint32_t& value) {
    const auto bytes = Read<4>();
    if (!bytes) {
      return false;
    }
    value = U32FromLittleEndian(*bytes);
    return true;
  }

  size_t remaining() const { return buffer_.size(); }
  span<T> remaining_span() const { return buffer_; }
  size_t num_read() const { return num_read_; }

 private:
  span<T> buffer_;
  size_t num_read_ = 0;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_CONTAINERS_SPAN_READER_H_

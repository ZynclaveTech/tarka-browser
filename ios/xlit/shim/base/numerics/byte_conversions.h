// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/numerics/byte_conversions.h (the readers used).
#ifndef TARK_SHIM_BASE_NUMERICS_BYTE_CONVERSIONS_H_
#define TARK_SHIM_BASE_NUMERICS_BYTE_CONVERSIONS_H_

#include <cstdint>

#include "base/containers/span.h"

namespace base {

constexpr uint16_t U16FromLittleEndian(span<const uint8_t, 2> bytes) {
  return static_cast<uint16_t>(bytes[0] | (bytes[1] << 8));
}
constexpr uint32_t U32FromLittleEndian(span<const uint8_t, 4> bytes) {
  return static_cast<uint32_t>(bytes[0]) |
         (static_cast<uint32_t>(bytes[1]) << 8) |
         (static_cast<uint32_t>(bytes[2]) << 16) |
         (static_cast<uint32_t>(bytes[3]) << 24);
}

}  // namespace base

#endif  // TARK_SHIM_BASE_NUMERICS_BYTE_CONVERSIONS_H_

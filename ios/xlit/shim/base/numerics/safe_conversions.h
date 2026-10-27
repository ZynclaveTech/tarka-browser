// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/numerics/safe_conversions.h (checked_cast only).
#ifndef TARK_SHIM_BASE_NUMERICS_SAFE_CONVERSIONS_H_
#define TARK_SHIM_BASE_NUMERICS_SAFE_CONVERSIONS_H_

#include <utility>

#include "base/check.h"

namespace base {

// Integral-to-integral cast that aborts when `value` does not fit.
template <typename Dst, typename Src>
constexpr Dst checked_cast(Src value) {
  CHECK(std::in_range<Dst>(value));
  return static_cast<Dst>(value);
}

}  // namespace base

#endif  // TARK_SHIM_BASE_NUMERICS_SAFE_CONVERSIONS_H_

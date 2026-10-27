// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/memory/raw_span.h: a plain span (no MiraclePtr).
#ifndef TARK_SHIM_BASE_MEMORY_RAW_SPAN_H_
#define TARK_SHIM_BASE_MEMORY_RAW_SPAN_H_

#include "base/containers/span.h"

namespace base {
template <typename T, size_t Extent = dynamic_extent>
using raw_span = span<T, Extent>;
}  // namespace base

#endif  // TARK_SHIM_BASE_MEMORY_RAW_SPAN_H_

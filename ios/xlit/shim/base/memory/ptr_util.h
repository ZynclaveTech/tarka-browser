// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/memory/ptr_util.h.
#ifndef TARK_SHIM_BASE_MEMORY_PTR_UTIL_H_
#define TARK_SHIM_BASE_MEMORY_PTR_UTIL_H_

#include <memory>

namespace base {
template <typename T>
std::unique_ptr<T> WrapUnique(T* ptr) {
  return std::unique_ptr<T>(ptr);
}
}  // namespace base

#endif  // TARK_SHIM_BASE_MEMORY_PTR_UTIL_H_

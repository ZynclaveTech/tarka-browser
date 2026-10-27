// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/memory/raw_ptr.h: a plain pointer wrapper (no
// MiraclePtr/BackupRefPtr protection).
#ifndef TARK_SHIM_BASE_MEMORY_RAW_PTR_H_
#define TARK_SHIM_BASE_MEMORY_RAW_PTR_H_

#include <cstddef>

namespace base {

template <typename T>
class raw_ptr {
 public:
  constexpr raw_ptr() noexcept = default;
  constexpr raw_ptr(std::nullptr_t) noexcept {}
  constexpr raw_ptr(T* p) noexcept : p_(p) {}
  constexpr raw_ptr& operator=(T* p) noexcept {
    p_ = p;
    return *this;
  }
  constexpr T* get() const noexcept { return p_; }
  constexpr T* operator->() const noexcept { return p_; }
  constexpr T& operator*() const noexcept { return *p_; }
  constexpr explicit operator bool() const noexcept { return p_ != nullptr; }
  constexpr operator T*() const noexcept { return p_; }

 private:
  T* p_ = nullptr;
};

}  // namespace base

using base::raw_ptr;

#endif  // TARK_SHIM_BASE_MEMORY_RAW_PTR_H_

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/memory/scoped_refptr.h: an intrusive pointer calling
// T::AddRef() / T::Release().
#ifndef TARK_SHIM_BASE_MEMORY_SCOPED_REFPTR_H_
#define TARK_SHIM_BASE_MEMORY_SCOPED_REFPTR_H_

#include <cstddef>
#include <type_traits>
#include <utility>

template <typename T>
class scoped_refptr {
 public:
  constexpr scoped_refptr() noexcept = default;
  constexpr scoped_refptr(std::nullptr_t) noexcept {}
  scoped_refptr(T* p) : ptr_(p) {
    if (ptr_) {
      ptr_->AddRef();
    }
  }
  scoped_refptr(const scoped_refptr& other) : scoped_refptr(other.ptr_) {}
  template <typename U>
    requires std::is_convertible_v<U*, T*>
  scoped_refptr(const scoped_refptr<U>& other) : scoped_refptr(other.get()) {}
  scoped_refptr(scoped_refptr&& other) noexcept
      : ptr_(std::exchange(other.ptr_, nullptr)) {}
  template <typename U>
    requires std::is_convertible_v<U*, T*>
  scoped_refptr(scoped_refptr<U>&& other) noexcept : ptr_(other.release()) {}
  ~scoped_refptr() {
    if (ptr_) {
      ptr_->Release();
    }
  }
  scoped_refptr& operator=(scoped_refptr other) noexcept {
    std::swap(ptr_, other.ptr_);
    return *this;
  }

  T* get() const { return ptr_; }
  T* operator->() const { return ptr_; }
  T& operator*() const { return *ptr_; }
  explicit operator bool() const { return ptr_ != nullptr; }
  // Hands over the reference without releasing it.
  T* release() { return std::exchange(ptr_, nullptr); }

 private:
  T* ptr_ = nullptr;
};

#endif  // TARK_SHIM_BASE_MEMORY_SCOPED_REFPTR_H_

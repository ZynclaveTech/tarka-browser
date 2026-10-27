// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/no_destructor.h: constructs T once, never destroys it.
#ifndef TARK_SHIM_BASE_NO_DESTRUCTOR_H_
#define TARK_SHIM_BASE_NO_DESTRUCTOR_H_

#include <new>
#include <utility>

namespace base {

template <typename T>
class NoDestructor {
 public:
  template <typename... Args>
  explicit NoDestructor(Args&&... args) {
    new (storage_) T(std::forward<Args>(args)...);
  }
  NoDestructor(const NoDestructor&) = delete;
  NoDestructor& operator=(const NoDestructor&) = delete;
  ~NoDestructor() = default;

  T& operator*() { return *get(); }
  const T& operator*() const { return *get(); }
  T* operator->() { return get(); }
  const T* operator->() const { return get(); }
  T* get() { return std::launder(reinterpret_cast<T*>(storage_)); }
  const T* get() const {
    return std::launder(reinterpret_cast<const T*>(storage_));
  }

 private:
  alignas(T) unsigned char storage_[sizeof(T)];
};

}  // namespace base

#endif  // TARK_SHIM_BASE_NO_DESTRUCTOR_H_

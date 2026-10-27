// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/functional/bind.h: BindRepeating with leading bound
// arguments, and Unretained (a raw pointer the callback does not own).
#ifndef TARK_SHIM_BASE_FUNCTIONAL_BIND_H_
#define TARK_SHIM_BASE_FUNCTIONAL_BIND_H_

#include <functional>
#include <tuple>
#include <utility>

#include "base/functional/callback.h"

namespace base {

template <typename T>
struct UnretainedWrapper {
  T* ptr;
};

template <typename T>
UnretainedWrapper<T> Unretained(T* ptr) {
  return UnretainedWrapper<T>{ptr};
}

namespace internal {
template <typename T>
const T& Unwrap(const T& value) {
  return value;
}
template <typename T>
T* Unwrap(const UnretainedWrapper<T>& wrapper) {
  return wrapper.ptr;
}
}  // namespace internal

// Returns a callable that converts to any matching RepeatingCallback.
template <typename F, typename... Bound>
auto BindRepeating(F&& f, Bound&&... bound) {
  return [f = std::forward<F>(f),
          ... bound = std::forward<Bound>(bound)](auto&&... rest) {
    return std::invoke(f, internal::Unwrap(bound)...,
                       std::forward<decltype(rest)>(rest)...);
  };
}

}  // namespace base

#endif  // TARK_SHIM_BASE_FUNCTIONAL_BIND_H_

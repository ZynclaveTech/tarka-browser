// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/functional/callback.h: RepeatingCallback over
// std::function (copyable, Run() may be called any number of times).
#ifndef TARK_SHIM_BASE_FUNCTIONAL_CALLBACK_H_
#define TARK_SHIM_BASE_FUNCTIONAL_CALLBACK_H_

#include <functional>
#include <utility>

#include "base/check.h"

namespace base {

template <typename Signature>
class RepeatingCallback;

template <typename R, typename... Args>
class RepeatingCallback<R(Args...)> {
 public:
  RepeatingCallback() = default;
  template <typename F>
    requires(!std::is_same_v<std::decay_t<F>, RepeatingCallback> &&
             std::is_invocable_r_v<R, F&, Args...>)
  RepeatingCallback(F&& f) : function_(std::forward<F>(f)) {}

  R Run(Args... args) const {
    CHECK(function_);
    return function_(std::forward<Args>(args)...);
  }
  bool is_null() const { return !function_; }
  explicit operator bool() const { return static_cast<bool>(function_); }

 private:
  std::function<R(Args...)> function_;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_FUNCTIONAL_CALLBACK_H_

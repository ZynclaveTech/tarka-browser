// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/memory/ref_counted.h: RefCountedThreadSafe (atomic
// count, deletes on the last Release) and MakeRefCounted.
#ifndef TARK_SHIM_BASE_MEMORY_REF_COUNTED_H_
#define TARK_SHIM_BASE_MEMORY_REF_COUNTED_H_

#include <atomic>
#include <utility>

#include "base/memory/scoped_refptr.h"

namespace base {

template <typename T>
class RefCountedThreadSafe {
 public:
  RefCountedThreadSafe(const RefCountedThreadSafe&) = delete;
  RefCountedThreadSafe& operator=(const RefCountedThreadSafe&) = delete;

  void AddRef() const { count_.fetch_add(1, std::memory_order_relaxed); }
  void Release() const {
    if (count_.fetch_sub(1, std::memory_order_acq_rel) == 1) {
      delete static_cast<const T*>(this);
    }
  }
  bool HasOneRef() const {
    return count_.load(std::memory_order_acquire) == 1;
  }

 protected:
  RefCountedThreadSafe() = default;
  ~RefCountedThreadSafe() = default;

 private:
  mutable std::atomic<int> count_{0};
};

template <typename T, typename... Args>
scoped_refptr<T> MakeRefCounted(Args&&... args) {
  return scoped_refptr<T>(new T(std::forward<Args>(args)...));
}

}  // namespace base

#endif  // TARK_SHIM_BASE_MEMORY_REF_COUNTED_H_

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/synchronization/lock.h over std::mutex.
#ifndef TARK_SHIM_BASE_SYNCHRONIZATION_LOCK_H_
#define TARK_SHIM_BASE_SYNCHRONIZATION_LOCK_H_

#include <mutex>

namespace base {

class Lock {
 public:
  Lock() = default;
  Lock(const Lock&) = delete;
  Lock& operator=(const Lock&) = delete;
  void Acquire() { mutex_.lock(); }
  void Release() { mutex_.unlock(); }
  bool Try() { return mutex_.try_lock(); }

 private:
  std::mutex mutex_;
};

class AutoLock {
 public:
  explicit AutoLock(Lock& lock) : lock_(lock) { lock_.Acquire(); }
  AutoLock(const AutoLock&) = delete;
  AutoLock& operator=(const AutoLock&) = delete;
  ~AutoLock() { lock_.Release(); }

 private:
  Lock& lock_;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_SYNCHRONIZATION_LOCK_H_

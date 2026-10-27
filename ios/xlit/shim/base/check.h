// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Minimal standalone stand-in for Chromium's //base/check.h. CHECK failures
// print the condition and location to stderr and abort(), in every build.
#ifndef TARK_SHIM_BASE_CHECK_H_
#define TARK_SHIM_BASE_CHECK_H_

#include <cstdio>
#include <cstdlib>
#include <sstream>

namespace base::internal {

class FatalStream {
 public:
  FatalStream(const char* file, int line, const char* what) {
    stream_ << file << ":" << line << ": Check failed: " << what << ". ";
  }
  FatalStream(const FatalStream&) = delete;
  FatalStream& operator=(const FatalStream&) = delete;
  [[noreturn]] ~FatalStream() {
    std::fprintf(stderr, "%s\n", stream_.str().c_str());
    std::abort();
  }
  template <typename T>
  const FatalStream& operator<<(const T& value) const {
    stream_ << value;
    return *this;
  }

 private:
  mutable std::ostringstream stream_;
};

// Lowers the precedence so that `CHECK(x) << "message"` binds the stream first.
struct Voidify {
  void operator&(const FatalStream&) {}
};

}  // namespace base::internal

#define CHECK(condition)                    \
  (condition) ? static_cast<void>(0)        \
              : ::base::internal::Voidify() & \
                    ::base::internal::FatalStream(__FILE__, __LINE__, #condition)

#define DCHECK(condition) CHECK(condition)
#define NOTREACHED() \
  ::base::internal::Voidify() & ::base::internal::FatalStream(__FILE__, __LINE__, "NOTREACHED")

#endif  // TARK_SHIM_BASE_CHECK_H_

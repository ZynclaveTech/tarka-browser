// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/path_service.h. There is no path provider outside
// Chromium: Get() always fails, so LoadFromBundle() returns nullptr. iOS
// loads the model and word lists by explicit path (tark_xlit_c.h).
#ifndef TARK_SHIM_BASE_PATH_SERVICE_H_
#define TARK_SHIM_BASE_PATH_SERVICE_H_

#include "base/base_paths.h"
#include "base/files/file_path.h"

namespace base {
class PathService {
 public:
  static bool Get(int key, FilePath* path) {
    static_cast<void>(key);
    static_cast<void>(path);
    return false;
  }
};
}  // namespace base

#endif  // TARK_SHIM_BASE_PATH_SERVICE_H_

// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/files/file_util.h (PathExists only).
#ifndef TARK_SHIM_BASE_FILES_FILE_UTIL_H_
#define TARK_SHIM_BASE_FILES_FILE_UTIL_H_

#include "base/files/file_path.h"

namespace base {
bool PathExists(const FilePath& path);
}  // namespace base

#endif  // TARK_SHIM_BASE_FILES_FILE_UTIL_H_

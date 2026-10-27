// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/base_paths.h: only the keys the engine names.
#ifndef TARK_SHIM_BASE_BASE_PATHS_H_
#define TARK_SHIM_BASE_BASE_PATHS_H_

namespace base {
enum BasePathKey {
  DIR_ASSETS = 1,
};
}  // namespace base

#endif  // TARK_SHIM_BASE_BASE_PATHS_H_

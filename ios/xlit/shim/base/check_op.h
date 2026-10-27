// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Minimal stand-in for Chromium's //base/check_op.h.
#ifndef TARK_SHIM_BASE_CHECK_OP_H_
#define TARK_SHIM_BASE_CHECK_OP_H_

#include "base/check.h"

#define TARK_SHIM_CHECK_OP(a, op, b)                                         \
  ((a)op(b)) ? static_cast<void>(0)                                          \
             : ::base::internal::Voidify() &                                 \
                   ::base::internal::FatalStream(__FILE__, __LINE__,         \
                                                 #a " " #op " " #b)          \
                       << "(" << (a) << " vs. " << (b) << ") "

#define CHECK_EQ(a, b) TARK_SHIM_CHECK_OP(a, ==, b)
#define CHECK_NE(a, b) TARK_SHIM_CHECK_OP(a, !=, b)
#define CHECK_LT(a, b) TARK_SHIM_CHECK_OP(a, <, b)
#define CHECK_LE(a, b) TARK_SHIM_CHECK_OP(a, <=, b)
#define CHECK_GT(a, b) TARK_SHIM_CHECK_OP(a, >, b)
#define CHECK_GE(a, b) TARK_SHIM_CHECK_OP(a, >=, b)
#define DCHECK_EQ(a, b) CHECK_EQ(a, b)
#define DCHECK_NE(a, b) CHECK_NE(a, b)
#define DCHECK_LT(a, b) CHECK_LT(a, b)
#define DCHECK_LE(a, b) CHECK_LE(a, b)
#define DCHECK_GT(a, b) CHECK_GT(a, b)
#define DCHECK_GE(a, b) CHECK_GE(a, b)

#endif  // TARK_SHIM_BASE_CHECK_OP_H_

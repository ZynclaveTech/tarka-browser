// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/memory/stack_allocated.h. Chromium enforces this with a
// clang plugin; here it is only an annotation.
#ifndef TARK_SHIM_BASE_MEMORY_STACK_ALLOCATED_H_
#define TARK_SHIM_BASE_MEMORY_STACK_ALLOCATED_H_

#define STACK_ALLOCATED() static_assert(true, "STACK_ALLOCATED")

#endif  // TARK_SHIM_BASE_MEMORY_STACK_ALLOCATED_H_

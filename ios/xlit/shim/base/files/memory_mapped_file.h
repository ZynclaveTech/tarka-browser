// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/files/memory_mapped_file.h: a read-only mmap(2) of a
// whole file.
#ifndef TARK_SHIM_BASE_FILES_MEMORY_MAPPED_FILE_H_
#define TARK_SHIM_BASE_FILES_MEMORY_MAPPED_FILE_H_

#include <cstddef>
#include <cstdint>

#include "base/containers/span.h"
#include "base/files/file_path.h"

namespace base {

class MemoryMappedFile {
 public:
  MemoryMappedFile() = default;
  MemoryMappedFile(const MemoryMappedFile&) = delete;
  MemoryMappedFile& operator=(const MemoryMappedFile&) = delete;
  ~MemoryMappedFile();

  // Maps `path` read-only. False if the file cannot be opened or mapped, or
  // if this object already holds a mapping. An empty file maps to an empty,
  // valid span.
  bool Initialize(const FilePath& path);

  bool IsValid() const { return valid_; }
  span<const uint8_t> bytes() const { return span<const uint8_t>(data_, length_); }
  const uint8_t* data() const { return data_; }
  size_t length() const { return length_; }

 private:
  const uint8_t* data_ = nullptr;
  size_t length_ = 0;
  bool valid_ = false;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_FILES_MEMORY_MAPPED_FILE_H_

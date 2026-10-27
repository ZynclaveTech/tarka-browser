// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/files/file_enumerator.h: non-recursive listing of one
// directory, matching each entry's name against a fnmatch(3) pattern.
#ifndef TARK_SHIM_BASE_FILES_FILE_ENUMERATOR_H_
#define TARK_SHIM_BASE_FILES_FILE_ENUMERATOR_H_

#include <cstddef>
#include <string>
#include <vector>

#include "base/files/file_path.h"

namespace base {

class FileEnumerator {
 public:
  enum FileType { FILES = 1 << 0, DIRECTORIES = 1 << 1 };

  // Lists `root` once, up front. `recursive` must be false (the engine never
  // recurses; this shim does not implement it).
  FileEnumerator(const FilePath& root,
                 bool recursive,
                 int file_type,
                 const FilePath::StringType& pattern);
  FileEnumerator(const FileEnumerator&) = delete;
  FileEnumerator& operator=(const FileEnumerator&) = delete;
  ~FileEnumerator();

  // The next match, or an empty path when there are no more.
  FilePath Next();

 private:
  std::vector<FilePath> entries_;
  size_t next_ = 0;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_FILES_FILE_ENUMERATOR_H_

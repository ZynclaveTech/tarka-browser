// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/files/file_path.h (POSIX: CharType is char).
#ifndef TARK_SHIM_BASE_FILES_FILE_PATH_H_
#define TARK_SHIM_BASE_FILES_FILE_PATH_H_

#include <string>
#include <string_view>

#define FILE_PATH_LITERAL(x) x

namespace base {

class FilePath {
 public:
  using CharType = char;
  using StringType = std::string;

  FilePath() = default;
  explicit FilePath(std::string_view path) : path_(path) {}

  const std::string& value() const { return path_; }
  bool empty() const { return path_.empty(); }

  // `component` appended with one separator.
  FilePath Append(std::string_view component) const {
    if (path_.empty() || path_.back() == '/') {
      return FilePath(path_ + std::string(component));
    }
    return FilePath(path_ + "/" + std::string(component));
  }
  FilePath AppendASCII(std::string_view component) const {
    return Append(component);
  }
  FilePath BaseName() const {
    const size_t slash = path_.rfind('/');
    return slash == std::string::npos ? *this
                                      : FilePath(path_.substr(slash + 1));
  }

  friend bool operator==(const FilePath&, const FilePath&) = default;
  friend auto operator<=>(const FilePath& a, const FilePath& b) {
    return a.path_ <=> b.path_;
  }

 private:
  std::string path_;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_FILES_FILE_PATH_H_

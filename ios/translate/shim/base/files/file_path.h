// Tark iOS: the slice of base::FilePath tark_captions uses.
#pragma once
#include <ostream>
#include <string>
#include <string_view>
namespace base {
class FilePath {
 public:
  FilePath() = default;
  explicit FilePath(std::string path) : path_(std::move(path)) {}
  const std::string& value() const { return path_; }
  bool empty() const { return path_.empty(); }
  FilePath AppendASCII(std::string_view name) const {
    if (path_.empty() || path_.back() == '/') { return FilePath(path_ + std::string(name)); }
    return FilePath(path_ + "/" + std::string(name));
  }
  FilePath Append(std::string_view name) const { return AppendASCII(name); }
 private:
  std::string path_;
};
inline std::ostream& operator<<(std::ostream& o, const FilePath& p) { return o << p.value(); }
}  // namespace base

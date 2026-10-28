// Tark iOS: whole-file reads.
#pragma once
#include <sys/stat.h>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <optional>
#include <vector>
#include "base/files/file_path.h"
namespace base {
inline bool PathExists(const FilePath& path) {
  struct stat s;
  return stat(path.value().c_str(), &s) == 0;
}
inline std::optional<std::vector<uint8_t>> ReadFileToBytes(const FilePath& path) {
  std::ifstream in(path.value(), std::ios::binary);
  if (!in) { return std::nullopt; }
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}
}  // namespace base

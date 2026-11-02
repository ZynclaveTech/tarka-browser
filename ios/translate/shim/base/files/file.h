// Tark iOS: base::File as an owned descriptor (MappedFilesSource only).
#pragma once
#include <unistd.h>
#include <utility>
namespace base {
class File {
 public:
  File() = default;
  explicit File(int fd) : fd_(fd) {}
  File(File&& o) noexcept : fd_(std::exchange(o.fd_, -1)) {}
  File& operator=(File&& o) noexcept { if (this != &o) { Close(); fd_ = std::exchange(o.fd_, -1); } return *this; }
  ~File() { Close(); }
  bool IsValid() const { return fd_ >= 0; }
  int TakePlatformFile() { return std::exchange(fd_, -1); }
 private:
  void Close() { if (fd_ >= 0) { close(fd_); fd_ = -1; } }
  int fd_ = -1;
};
}  // namespace base

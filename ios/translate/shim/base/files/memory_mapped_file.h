// Tark iOS: read-only whole-file mapping.
#pragma once
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstdint>
#include "base/containers/span.h"
#include "base/files/file.h"
namespace base {
class MemoryMappedFile {
 public:
  MemoryMappedFile() = default;
  MemoryMappedFile(const MemoryMappedFile&) = delete;
  MemoryMappedFile& operator=(const MemoryMappedFile&) = delete;
  ~MemoryMappedFile() { if (data_) { munmap(data_, size_); } }
  bool Initialize(File file) {
    const int fd = file.TakePlatformFile();
    struct stat s;
    if (fd < 0 || fstat(fd, &s) != 0 || s.st_size <= 0) { if (fd >= 0) { close(fd); } return false; }
    void* p = mmap(nullptr, s.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (p == MAP_FAILED) { return false; }
    data_ = static_cast<uint8_t*>(p);
    size_ = static_cast<size_t>(s.st_size);
    return true;
  }
  span<const uint8_t> bytes() const { return span<const uint8_t>(data_, size_); }
 private:
  uint8_t* data_ = nullptr;
  size_t size_ = 0;
};
}  // namespace base

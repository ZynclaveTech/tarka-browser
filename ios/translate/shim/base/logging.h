// Tark iOS: LOG(ERROR) to stderr, one line per statement.
#pragma once
#include <iostream>
#include <sstream>
namespace base_shim {
struct LogLine {
  std::ostringstream s;
  ~LogLine() { std::cerr << "tark_captions: " << s.str() << std::endl; }
};
}
#define LOG(severity) base_shim::LogLine().s

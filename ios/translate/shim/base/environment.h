// Tark iOS: process environment.
#pragma once
#include <stdlib.h>
#include <memory>
#include <string>
namespace base {
class Environment {
 public:
  static std::unique_ptr<Environment> Create() { return std::make_unique<Environment>(); }
  bool SetVar(const std::string& name, const std::string& value) { return setenv(name.c_str(), value.c_str(), 1) == 0; }
};
}  // namespace base

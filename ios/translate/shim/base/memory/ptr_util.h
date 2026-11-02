#pragma once
#include <memory>
namespace base {
template <class T>
std::unique_ptr<T> WrapUnique(T* p) { return std::unique_ptr<T>(p); }
}

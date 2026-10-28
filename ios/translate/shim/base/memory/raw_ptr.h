// Tark iOS: raw_ptr is a plain pointer (no MiraclePtr outside Chromium).
#pragma once
#include <utility>
template <class T>
class raw_ptr {
 public:
  raw_ptr() = default;
  raw_ptr(T* p) : p_(p) {}  // NOLINT: implicit, as base's.
  raw_ptr& operator=(T* p) { p_ = p; return *this; }
  T* get() const { return p_; }
  T* operator->() const { return p_; }
  T& operator*() const { return *p_; }
  operator T*() const { return p_; }  // NOLINT
  explicit operator bool() const { return p_ != nullptr; }
  T* ExtractAsDangling() { return std::exchange(p_, nullptr); }
 private:
  T* p_ = nullptr;
};

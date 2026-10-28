// Tark iOS: a strict RFC 8259 reader into base::Value (UTF-8 in and out).
#pragma once
#include <cmath>
#include <cstdlib>
#include <optional>
#include <string>
#include <string_view>
#include "base/values.h"
namespace base {
enum JSONParserOptions { JSON_PARSE_RFC = 0 };
class JSONReader {
 public:
  static std::optional<Value> Read(std::string_view json, int /*options*/ = JSON_PARSE_RFC) {
    JSONReader r(json);
    r.Space();
    std::optional<Value> v = r.Parse(0);
    r.Space();
    if (!v || r.p_ != r.s_.size()) { return std::nullopt; }
    return v;
  }
 private:
  explicit JSONReader(std::string_view s) : s_(s) {}
  void Space() { while (p_ < s_.size() && (s_[p_] == ' ' || s_[p_] == '\t' || s_[p_] == '\n' || s_[p_] == '\r')) { ++p_; } }
  bool Eat(char c) { Space(); if (p_ < s_.size() && s_[p_] == c) { ++p_; return true; } return false; }
  bool Word(std::string_view w) { if (s_.substr(p_, w.size()) == w) { p_ += w.size(); return true; } return false; }
  std::optional<Value> Parse(int depth) {
    if (depth > 64) { return std::nullopt; }
    Space();
    if (p_ >= s_.size()) { return std::nullopt; }
    const char c = s_[p_];
    if (c == '{') {
      ++p_;
      DictValue d;
      if (Eat('}')) { return Value(std::move(d)); }
      do {
        Space();
        std::optional<std::string> key = String();
        if (!key || !Eat(':')) { return std::nullopt; }
        std::optional<Value> v = Parse(depth + 1);
        if (!v) { return std::nullopt; }
        d.Set(std::move(*key), std::move(*v));
      } while (Eat(','));
      if (!Eat('}')) { return std::nullopt; }
      return Value(std::move(d));
    }
    if (c == '[') {
      ++p_;
      ListValue l;
      if (Eat(']')) { return Value(std::move(l)); }
      do {
        std::optional<Value> v = Parse(depth + 1);
        if (!v) { return std::nullopt; }
        l.push_back(std::move(*v));
      } while (Eat(','));
      if (!Eat(']')) { return std::nullopt; }
      return Value(std::move(l));
    }
    if (c == '"') {
      std::optional<std::string> s = String();
      return s ? std::optional<Value>(Value(std::move(*s))) : std::nullopt;
    }
    if (Word("true")) { return Value(true); }
    if (Word("false")) { return Value(false); }
    if (Word("null")) { return Value(); }
    return Number();
  }
  std::optional<Value> Number() {
    const size_t start = p_;
    if (p_ < s_.size() && s_[p_] == '-') { ++p_; }
    bool fraction = false;
    while (p_ < s_.size() && (isdigit(static_cast<unsigned char>(s_[p_])) || s_[p_] == '.' || s_[p_] == 'e' ||
                              s_[p_] == 'E' || s_[p_] == '+' || (s_[p_] == '-' && p_ > start))) {
      if (!isdigit(static_cast<unsigned char>(s_[p_]))) { fraction = true; }
      ++p_;
    }
    if (p_ == start) { return std::nullopt; }
    const std::string text(s_.substr(start, p_ - start));
    char* end = nullptr;
    const double d = std::strtod(text.c_str(), &end);
    if (end != text.c_str() + text.size() || !std::isfinite(d)) { return std::nullopt; }
    if (!fraction && d >= -2147483648.0 && d <= 2147483647.0) { return Value(static_cast<int>(d)); }
    return Value(d);
  }
  void AppendUtf8(std::string* out, uint32_t cp) {
    if (cp < 0x80) { out->push_back(static_cast<char>(cp)); }
    else if (cp < 0x800) { out->push_back(static_cast<char>(0xC0 | (cp >> 6))); out->push_back(static_cast<char>(0x80 | (cp & 0x3F))); }
    else if (cp < 0x10000) { out->push_back(static_cast<char>(0xE0 | (cp >> 12))); out->push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F))); out->push_back(static_cast<char>(0x80 | (cp & 0x3F))); }
    else { out->push_back(static_cast<char>(0xF0 | (cp >> 18))); out->push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F))); out->push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F))); out->push_back(static_cast<char>(0x80 | (cp & 0x3F))); }
  }
  std::optional<uint32_t> Hex4() {
    if (p_ + 4 > s_.size()) { return std::nullopt; }
    uint32_t v = 0;
    for (int i = 0; i < 4; ++i) {
      const char h = s_[p_++];
      v <<= 4;
      if (h >= '0' && h <= '9') { v |= h - '0'; } else if (h >= 'a' && h <= 'f') { v |= h - 'a' + 10; }
      else if (h >= 'A' && h <= 'F') { v |= h - 'A' + 10; } else { return std::nullopt; }
    }
    return v;
  }
  std::optional<std::string> String() {
    if (p_ >= s_.size() || s_[p_] != '"') { return std::nullopt; }
    ++p_;
    std::string out;
    while (p_ < s_.size()) {
      const char c = s_[p_++];
      if (c == '"') { return out; }
      if (static_cast<unsigned char>(c) < 0x20) { return std::nullopt; }
      if (c != '\\') { out.push_back(c); continue; }
      if (p_ >= s_.size()) { return std::nullopt; }
      const char e = s_[p_++];
      switch (e) {
        case '"': out.push_back('"'); break;
        case '\\': out.push_back('\\'); break;
        case '/': out.push_back('/'); break;
        case 'b': out.push_back('\b'); break;
        case 'f': out.push_back('\f'); break;
        case 'n': out.push_back('\n'); break;
        case 'r': out.push_back('\r'); break;
        case 't': out.push_back('\t'); break;
        case 'u': {
          std::optional<uint32_t> cp = Hex4();
          if (!cp) { return std::nullopt; }
          if (*cp >= 0xD800 && *cp <= 0xDBFF) {
            if (!Word("\\u")) { return std::nullopt; }
            std::optional<uint32_t> lo = Hex4();
            if (!lo || *lo < 0xDC00 || *lo > 0xDFFF) { return std::nullopt; }
            *cp = 0x10000 + ((*cp - 0xD800) << 10) + (*lo - 0xDC00);
          } else if (*cp >= 0xDC00 && *cp <= 0xDFFF) {
            return std::nullopt;
          }
          AppendUtf8(&out, *cp);
          break;
        }
        default: return std::nullopt;
      }
    }
    return std::nullopt;
  }
  std::string_view s_;
  size_t p_ = 0;
};
}  // namespace base

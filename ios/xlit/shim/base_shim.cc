// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Out-of-line parts of the //base shim: Value accessors, the JSON parser,
// UTF-8 <-> UTF-16 conversion and the POSIX file helpers.

#include <dirent.h>
#include <fcntl.h>
#include <fnmatch.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <string>

#include "base/check.h"
#include "base/files/file_enumerator.h"
#include "base/files/file_util.h"
#include "base/files/memory_mapped_file.h"
#include "base/json/json_reader.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"

namespace base {

// --- Values -----------------------------------------------------------------

DictValue::DictValue() = default;
DictValue::DictValue(DictValue&&) noexcept = default;
DictValue& DictValue::operator=(DictValue&&) noexcept = default;
DictValue::~DictValue() = default;

const Value* DictValue::Find(std::string_view key) const {
  const auto it = map_.find(key);
  return it == map_.end() ? nullptr : it->second.get();
}
std::optional<bool> DictValue::FindBool(std::string_view key) const {
  const Value* v = Find(key);
  return v ? v->GetIfBool() : std::nullopt;
}
std::optional<int> DictValue::FindInt(std::string_view key) const {
  const Value* v = Find(key);
  return v ? v->GetIfInt() : std::nullopt;
}
std::optional<double> DictValue::FindDouble(std::string_view key) const {
  const Value* v = Find(key);
  return v ? v->GetIfDouble() : std::nullopt;
}
const std::string* DictValue::FindString(std::string_view key) const {
  const Value* v = Find(key);
  return v ? v->GetIfString() : nullptr;
}
const DictValue* DictValue::FindDict(std::string_view key) const {
  const Value* v = Find(key);
  return v ? v->GetIfDict() : nullptr;
}
const ListValue* DictValue::FindList(std::string_view key) const {
  const Value* v = Find(key);
  return v ? v->GetIfList() : nullptr;
}
void DictValue::Set(std::string key, Value value) {
  map_.insert_or_assign(std::move(key),
                        std::make_unique<Value>(std::move(value)));
}

ListValue::ListValue() = default;
ListValue::ListValue(ListValue&&) noexcept = default;
ListValue& ListValue::operator=(ListValue&&) noexcept = default;
ListValue::~ListValue() = default;
bool ListValue::empty() const {
  return values_.empty();
}
size_t ListValue::size() const {
  return values_.size();
}
const Value& ListValue::operator[](size_t index) const {
  CHECK(index < values_.size());
  return values_[index];
}
std::vector<Value>::const_iterator ListValue::begin() const {
  return values_.begin();
}
std::vector<Value>::const_iterator ListValue::end() const {
  return values_.end();
}
void ListValue::Append(Value value) {
  values_.push_back(std::move(value));
}

std::optional<bool> Value::GetIfBool() const {
  const bool* b = std::get_if<bool>(&data_);
  return b ? std::optional<bool>(*b) : std::nullopt;
}
std::optional<int> Value::GetIfInt() const {
  const int* i = std::get_if<int>(&data_);
  return i ? std::optional<int>(*i) : std::nullopt;
}
std::optional<double> Value::GetIfDouble() const {
  if (const double* d = std::get_if<double>(&data_)) {
    return *d;
  }
  if (const int* i = std::get_if<int>(&data_)) {
    return static_cast<double>(*i);
  }
  return std::nullopt;
}

// --- UTF conversion ---------------------------------------------------------

namespace {

constexpr char32_t kReplacement = 0xFFFD;

// Decodes one code point at `i` (advancing it); kReplacement and one byte on
// an invalid, overlong, surrogate or truncated sequence.
char32_t DecodeUtf8(std::string_view s, size_t& i, bool& valid) {
  const auto byte = [&](size_t k) { return static_cast<uint8_t>(s[k]); };
  const uint8_t b0 = byte(i);
  valid = true;
  if (b0 < 0x80) {
    ++i;
    return b0;
  }
  size_t length = 0;
  char32_t cp = 0;
  char32_t min = 0;
  if ((b0 & 0xE0) == 0xC0) {
    length = 2, cp = b0 & 0x1F, min = 0x80;
  } else if ((b0 & 0xF0) == 0xE0) {
    length = 3, cp = b0 & 0x0F, min = 0x800;
  } else if ((b0 & 0xF8) == 0xF0) {
    length = 4, cp = b0 & 0x07, min = 0x10000;
  } else {
    valid = false;
    ++i;
    return kReplacement;
  }
  if (i + length > s.size()) {
    valid = false;
    ++i;
    return kReplacement;
  }
  for (size_t k = 1; k < length; ++k) {
    if ((byte(i + k) & 0xC0) != 0x80) {
      valid = false;
      ++i;
      return kReplacement;
    }
    cp = (cp << 6) | (byte(i + k) & 0x3F);
  }
  if (cp < min || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
    valid = false;
    ++i;
    return kReplacement;
  }
  i += length;
  return cp;
}

void AppendUtf8(char32_t cp, std::string& out) {
  if (cp < 0x80) {
    out.push_back(static_cast<char>(cp));
  } else if (cp < 0x800) {
    out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else if (cp < 0x10000) {
    out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else {
    out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  }
}

void AppendUtf16(char32_t cp, std::u16string& out) {
  if (cp < 0x10000) {
    out.push_back(static_cast<char16_t>(cp));
  } else {
    cp -= 0x10000;
    out.push_back(static_cast<char16_t>(0xD800 + (cp >> 10)));
    out.push_back(static_cast<char16_t>(0xDC00 + (cp & 0x3FF)));
  }
}

}  // namespace

std::u16string UTF8ToUTF16(std::string_view utf8) {
  std::u16string out;
  out.reserve(utf8.size());
  bool valid = true;
  for (size_t i = 0; i < utf8.size();) {
    AppendUtf16(DecodeUtf8(utf8, i, valid), out);
  }
  return out;
}

std::string UTF16ToUTF8(std::u16string_view utf16) {
  std::string out;
  out.reserve(utf16.size() * 3);
  for (size_t i = 0; i < utf16.size(); ++i) {
    char32_t cp = utf16[i];
    if (cp >= 0xD800 && cp <= 0xDBFF && i + 1 < utf16.size() &&
        utf16[i + 1] >= 0xDC00 && utf16[i + 1] <= 0xDFFF) {
      cp = 0x10000 + ((cp - 0xD800) << 10) + (utf16[i + 1] - 0xDC00);
      ++i;
    } else if (cp >= 0xD800 && cp <= 0xDFFF) {
      cp = kReplacement;
    }
    AppendUtf8(cp, out);
  }
  return out;
}

// --- JSON -------------------------------------------------------------------

namespace {

constexpr int kMaxDepth = 200;

class JsonParser {
 public:
  explicit JsonParser(std::string_view json) : s_(json) {}

  std::optional<Value> ParseDocument() {
    // A UTF-8 byte-order mark is skipped, as Chromium does.
    if (s_.starts_with("\xEF\xBB\xBF")) {
      pos_ = 3;
    }
    std::optional<Value> value = ParseValue(0);
    SkipWhitespace();
    if (!value || pos_ != s_.size()) {
      return std::nullopt;
    }
    return value;
  }

 private:
  void SkipWhitespace() {
    while (pos_ < s_.size() && (s_[pos_] == ' ' || s_[pos_] == '\t' ||
                                s_[pos_] == '\n' || s_[pos_] == '\r')) {
      ++pos_;
    }
  }
  bool Consume(std::string_view token) {
    if (s_.substr(pos_).starts_with(token)) {
      pos_ += token.size();
      return true;
    }
    return false;
  }

  std::optional<Value> ParseValue(int depth) {
    if (depth > kMaxDepth) {
      return std::nullopt;
    }
    SkipWhitespace();
    if (pos_ >= s_.size()) {
      return std::nullopt;
    }
    switch (s_[pos_]) {
      case '{':
        return ParseObject(depth);
      case '[':
        return ParseArray(depth);
      case '"': {
        std::optional<std::string> text = ParseString();
        return text ? std::optional<Value>(Value(std::move(*text)))
                    : std::nullopt;
      }
      case 't':
        return Consume("true") ? std::optional<Value>(Value(true))
                               : std::nullopt;
      case 'f':
        return Consume("false") ? std::optional<Value>(Value(false))
                                : std::nullopt;
      case 'n':
        return Consume("null") ? std::optional<Value>(Value())
                               : std::nullopt;
      default:
        return ParseNumber();
    }
  }

  std::optional<Value> ParseObject(int depth) {
    ++pos_;  // '{'
    DictValue dict;
    SkipWhitespace();
    if (Consume("}")) {
      return Value(std::move(dict));
    }
    while (true) {
      SkipWhitespace();
      if (pos_ >= s_.size() || s_[pos_] != '"') {
        return std::nullopt;
      }
      std::optional<std::string> key = ParseString();
      if (!key) {
        return std::nullopt;
      }
      SkipWhitespace();
      if (!Consume(":")) {
        return std::nullopt;
      }
      std::optional<Value> value = ParseValue(depth + 1);
      if (!value) {
        return std::nullopt;
      }
      dict.Set(std::move(*key), std::move(*value));
      SkipWhitespace();
      if (Consume("}")) {
        return Value(std::move(dict));
      }
      if (!Consume(",")) {
        return std::nullopt;
      }
    }
  }

  std::optional<Value> ParseArray(int depth) {
    ++pos_;  // '['
    ListValue list;
    SkipWhitespace();
    if (Consume("]")) {
      return Value(std::move(list));
    }
    while (true) {
      std::optional<Value> value = ParseValue(depth + 1);
      if (!value) {
        return std::nullopt;
      }
      list.Append(std::move(*value));
      SkipWhitespace();
      if (Consume("]")) {
        return Value(std::move(list));
      }
      if (!Consume(",")) {
        return std::nullopt;
      }
    }
  }

  std::optional<uint32_t> ParseHex4() {
    if (pos_ + 4 > s_.size()) {
      return std::nullopt;
    }
    uint32_t value = 0;
    for (int k = 0; k < 4; ++k) {
      const char c = s_[pos_++];
      value <<= 4;
      if (c >= '0' && c <= '9') {
        value |= static_cast<uint32_t>(c - '0');
      } else if (c >= 'a' && c <= 'f') {
        value |= static_cast<uint32_t>(c - 'a' + 10);
      } else if (c >= 'A' && c <= 'F') {
        value |= static_cast<uint32_t>(c - 'A' + 10);
      } else {
        return std::nullopt;
      }
    }
    return value;
  }

  // At the opening quote. Strict: control characters must be escaped, and
  // the bytes must be valid UTF-8.
  std::optional<std::string> ParseString() {
    ++pos_;  // '"'
    std::string out;
    while (pos_ < s_.size()) {
      const char c = s_[pos_];
      if (c == '"') {
        ++pos_;
        return out;
      }
      if (static_cast<uint8_t>(c) < 0x20) {
        return std::nullopt;
      }
      if (c != '\\') {
        bool valid = true;
        const size_t start = pos_;
        DecodeUtf8(s_, pos_, valid);
        if (!valid) {
          return std::nullopt;
        }
        out.append(s_.substr(start, pos_ - start));
        continue;
      }
      ++pos_;
      if (pos_ >= s_.size()) {
        return std::nullopt;
      }
      const char e = s_[pos_++];
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
          std::optional<uint32_t> unit = ParseHex4();
          if (!unit) {
            return std::nullopt;
          }
          char32_t cp = *unit;
          if (cp >= 0xD800 && cp <= 0xDBFF) {
            // A high surrogate must be followed by an escaped low one.
            if (!Consume("\\u")) {
              return std::nullopt;
            }
            std::optional<uint32_t> low = ParseHex4();
            if (!low || *low < 0xDC00 || *low > 0xDFFF) {
              return std::nullopt;
            }
            cp = 0x10000 + ((cp - 0xD800) << 10) + (*low - 0xDC00);
          } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
            return std::nullopt;
          }
          AppendUtf8(cp, out);
          break;
        }
        default:
          return std::nullopt;
      }
    }
    return std::nullopt;  // unterminated
  }

  // RFC 8259 number grammar. An integer without fraction or exponent that
  // fits in int is an int; anything else a finite double.
  std::optional<Value> ParseNumber() {
    const size_t start = pos_;
    const auto digit = [&] {
      return pos_ < s_.size() && s_[pos_] >= '0' && s_[pos_] <= '9';
    };
    bool integer = true;
    if (pos_ < s_.size() && s_[pos_] == '-') {
      ++pos_;
    }
    if (!digit()) {
      return std::nullopt;
    }
    if (s_[pos_] == '0') {
      ++pos_;
      if (digit()) {
        return std::nullopt;  // leading zero
      }
    } else {
      while (digit()) {
        ++pos_;
      }
    }
    if (pos_ < s_.size() && s_[pos_] == '.') {
      integer = false;
      ++pos_;
      if (!digit()) {
        return std::nullopt;
      }
      while (digit()) {
        ++pos_;
      }
    }
    if (pos_ < s_.size() && (s_[pos_] == 'e' || s_[pos_] == 'E')) {
      integer = false;
      ++pos_;
      if (pos_ < s_.size() && (s_[pos_] == '+' || s_[pos_] == '-')) {
        ++pos_;
      }
      if (!digit()) {
        return std::nullopt;
      }
      while (digit()) {
        ++pos_;
      }
    }
    const std::string_view text = s_.substr(start, pos_ - start);
    if (integer) {
      int value = 0;
      const auto [end, error] =
          std::from_chars(text.data(), text.data() + text.size(), value);
      if (error == std::errc() && end == text.data() + text.size()) {
        return Value(value);
      }
    }
    // strtod is locale-dependent in theory; JSON numbers use '.', and the C
    // locale (the default for a process that never calls setlocale) agrees.
    const std::string copy(text);
    char* end = nullptr;
    const double value = std::strtod(copy.c_str(), &end);
    if (end != copy.c_str() + copy.size() || !std::isfinite(value)) {
      return std::nullopt;
    }
    return Value(value);
  }

  std::string_view s_;
  size_t pos_ = 0;
};

}  // namespace

std::optional<Value> JSONReader::Read(std::string_view json, int options) {
  static_cast<void>(options);
  return JsonParser(json).ParseDocument();
}

std::optional<DictValue> JSONReader::ReadDict(std::string_view json,
                                              int options) {
  std::optional<Value> value = Read(json, options);
  if (!value) {
    return std::nullopt;
  }
  DictValue* dict = value->GetIfDict();
  if (!dict) {
    return std::nullopt;
  }
  return std::move(*dict);
}

// --- Files ------------------------------------------------------------------

bool PathExists(const FilePath& path) {
  return access(path.value().c_str(), F_OK) == 0;
}

FileEnumerator::FileEnumerator(const FilePath& root,
                               bool recursive,
                               int file_type,
                               const FilePath::StringType& pattern) {
  CHECK(!recursive);
  DIR* dir = opendir(root.value().c_str());
  if (!dir) {
    return;
  }
  while (const dirent* entry = readdir(dir)) {
    const std::string_view name = entry->d_name;
    if (name == "." || name == "..") {
      continue;
    }
    if (!pattern.empty() && fnmatch(pattern.c_str(), entry->d_name, 0) != 0) {
      continue;
    }
    const FilePath path = root.Append(name);
    struct stat info;
    if (stat(path.value().c_str(), &info) != 0) {
      continue;
    }
    const bool is_dir = S_ISDIR(info.st_mode);
    if ((is_dir && (file_type & DIRECTORIES)) ||
        (!is_dir && (file_type & FILES))) {
      entries_.push_back(path);
    }
  }
  closedir(dir);
}

FileEnumerator::~FileEnumerator() = default;

FilePath FileEnumerator::Next() {
  return next_ < entries_.size() ? entries_[next_++] : FilePath();
}

MemoryMappedFile::~MemoryMappedFile() {
  if (data_ && length_ > 0) {
    munmap(const_cast<uint8_t*>(data_), length_);
  }
}

bool MemoryMappedFile::Initialize(const FilePath& path) {
  if (valid_) {
    return false;
  }
  const int fd = open(path.value().c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    return false;
  }
  struct stat info;
  if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size < 0) {
    close(fd);
    return false;
  }
  const size_t length = static_cast<size_t>(info.st_size);
  if (length == 0) {
    close(fd);
    valid_ = true;
    return true;
  }
  void* mapping = mmap(nullptr, length, PROT_READ, MAP_PRIVATE, fd, 0);
  close(fd);  // the mapping keeps the file open
  if (mapping == MAP_FAILED) {
    return false;
  }
  data_ = static_cast<const uint8_t*>(mapping);
  length_ = length;
  valid_ = true;
  return true;
}

}  // namespace base

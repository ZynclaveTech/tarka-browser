// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Stand-in for //base/values.h: the subset of Value / DictValue / ListValue
// the engine reads. Like Chromium, a JSON integer that fits in int is an int
// and every other number a double; FindInt/GetIfInt see only ints.
#ifndef TARK_SHIM_BASE_VALUES_H_
#define TARK_SHIM_BASE_VALUES_H_

#include <cstddef>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace base {

class Value;

class DictValue {
 public:
  using Map = std::map<std::string, std::unique_ptr<Value>, std::less<>>;

  class const_iterator {
   public:
    explicit const_iterator(Map::const_iterator it) : it_(it) {}
    std::pair<const std::string&, const Value&> operator*() const {
      return {it_->first, *it_->second};
    }
    const_iterator& operator++() {
      ++it_;
      return *this;
    }
    bool operator==(const const_iterator&) const = default;

   private:
    Map::const_iterator it_;
  };

  DictValue();
  DictValue(DictValue&&) noexcept;
  DictValue& operator=(DictValue&&) noexcept;
  ~DictValue();

  bool empty() const { return map_.empty(); }
  size_t size() const { return map_.size(); }
  const_iterator begin() const { return const_iterator(map_.begin()); }
  const_iterator end() const { return const_iterator(map_.end()); }

  const Value* Find(std::string_view key) const;
  std::optional<bool> FindBool(std::string_view key) const;
  std::optional<int> FindInt(std::string_view key) const;
  // An int or a double, as a double (Chromium's FindDouble).
  std::optional<double> FindDouble(std::string_view key) const;
  const std::string* FindString(std::string_view key) const;
  const DictValue* FindDict(std::string_view key) const;
  const class ListValue* FindList(std::string_view key) const;

  // Replaces any existing value for `key` (the last duplicate key wins, as
  // in Chromium's JSON parser).
  void Set(std::string key, Value value);

 private:
  Map map_;
};

class ListValue {
 public:
  ListValue();
  ListValue(ListValue&&) noexcept;
  ListValue& operator=(ListValue&&) noexcept;
  ~ListValue();

  bool empty() const;
  size_t size() const;
  const Value& operator[](size_t index) const;
  std::vector<Value>::const_iterator begin() const;
  std::vector<Value>::const_iterator end() const;
  void Append(Value value);

 private:
  std::vector<Value> values_;
};

class Value {
 public:
  enum class Type { NONE, BOOLEAN, INTEGER, DOUBLE, STRING, DICT, LIST };

  Value() = default;
  explicit Value(bool value) : data_(value) {}
  explicit Value(int value) : data_(value) {}
  explicit Value(double value) : data_(value) {}
  explicit Value(std::string value) : data_(std::move(value)) {}
  explicit Value(DictValue value) : data_(std::move(value)) {}
  explicit Value(ListValue value) : data_(std::move(value)) {}
  Value(Value&&) noexcept = default;
  Value& operator=(Value&&) noexcept = default;

  Type type() const { return static_cast<Type>(data_.index()); }

  std::optional<bool> GetIfBool() const;
  std::optional<int> GetIfInt() const;
  std::optional<double> GetIfDouble() const;
  const std::string* GetIfString() const { return std::get_if<std::string>(&data_); }
  const DictValue* GetIfDict() const { return std::get_if<DictValue>(&data_); }
  const ListValue* GetIfList() const { return std::get_if<ListValue>(&data_); }
  DictValue* GetIfDict() { return std::get_if<DictValue>(&data_); }

 private:
  std::variant<std::monostate, bool, int, double, std::string, DictValue,
               ListValue>
      data_;
};

}  // namespace base

#endif  // TARK_SHIM_BASE_VALUES_H_

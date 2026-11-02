// Tark iOS: the slice of base::Value tark_captions reads (model JSON files).
#pragma once
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>
namespace base {
class Value;
using ListValue = std::vector<Value>;
// A dictionary is the map; Value holds one (std::map allows an incomplete
// mapped type until it is used).
class DictValue {
 public:
  using Map = std::map<std::string, Value, std::less<>>;
  // As Chromium's: iterating yields (key, value) references, not copies.
  class const_iterator {
   public:
    explicit const_iterator(typename Map::const_iterator it) : it_(it) {}
    std::pair<const std::string&, const Value&> operator*() const;
    const_iterator& operator++();
    bool operator!=(const const_iterator& other) const;

   private:
    typename Map::const_iterator it_;
  };

  const_iterator begin() const;
  const_iterator end() const;
  size_t size() const;
  bool empty() const { return map_.empty(); }
  void Set(std::string key, Value value);
  const Value* Find(std::string_view key) const;
  const std::string* FindString(std::string_view key) const;
  const ListValue* FindList(std::string_view key) const;
  std::optional<bool> FindBool(std::string_view key) const;
  std::optional<int> FindInt(std::string_view key) const;

 private:
  Map map_;
};
class Value {
 public:
  Value() = default;
  explicit Value(bool b) : v_(b) {}
  explicit Value(int i) : v_(i) {}
  explicit Value(double d) : v_(d) {}
  explicit Value(std::string s) : v_(std::move(s)) {}
  explicit Value(ListValue l) : v_(std::move(l)) {}
  explicit Value(DictValue d) : v_(std::move(d)) {}
  bool is_none() const { return v_.index() == 0; }
  bool is_bool() const { return std::holds_alternative<bool>(v_); }
  bool is_int() const { return std::holds_alternative<int>(v_); }
  bool is_double() const { return std::holds_alternative<double>(v_); }
  bool is_string() const { return std::holds_alternative<std::string>(v_); }
  bool is_list() const { return std::holds_alternative<ListValue>(v_); }
  bool is_dict() const { return std::holds_alternative<DictValue>(v_); }
  bool GetBool() const { return std::get<bool>(v_); }
  int GetInt() const { return std::get<int>(v_); }
  double GetDouble() const { return is_int() ? GetInt() : std::get<double>(v_); }
  const std::string& GetString() const { return std::get<std::string>(v_); }
  const ListValue& GetList() const { return std::get<ListValue>(v_); }
  const DictValue& GetDict() const { return std::get<DictValue>(v_); }
  DictValue TakeDict() && { return std::move(std::get<DictValue>(v_)); }

 private:
  std::variant<std::monostate, bool, int, double, std::string, ListValue, DictValue> v_;
};
inline std::pair<const std::string&, const Value&> DictValue::const_iterator::operator*() const {
  return {it_->first, it_->second};
}
inline DictValue::const_iterator& DictValue::const_iterator::operator++() {
  ++it_;
  return *this;
}
inline bool DictValue::const_iterator::operator!=(const const_iterator& other) const { return it_ != other.it_; }
inline DictValue::const_iterator DictValue::begin() const { return const_iterator(map_.begin()); }
inline DictValue::const_iterator DictValue::end() const { return const_iterator(map_.end()); }
inline size_t DictValue::size() const { return map_.size(); }
inline void DictValue::Set(std::string key, Value value) { map_.insert_or_assign(std::move(key), std::move(value)); }
inline const Value* DictValue::Find(std::string_view key) const {
  auto it = map_.find(key);
  return it == map_.end() ? nullptr : &it->second;
}
inline const std::string* DictValue::FindString(std::string_view key) const {
  const Value* v = Find(key);
  return v && v->is_string() ? &v->GetString() : nullptr;
}
inline const ListValue* DictValue::FindList(std::string_view key) const {
  const Value* v = Find(key);
  return v && v->is_list() ? &v->GetList() : nullptr;
}
inline std::optional<bool> DictValue::FindBool(std::string_view key) const {
  const Value* v = Find(key);
  return v && v->is_bool() ? std::optional<bool>(v->GetBool()) : std::nullopt;
}
inline std::optional<int> DictValue::FindInt(std::string_view key) const {
  const Value* v = Find(key);
  return v && v->is_int() ? std::optional<int>(v->GetInt()) : std::nullopt;
}
}  // namespace base

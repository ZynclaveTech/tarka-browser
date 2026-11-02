// Tark iOS: a non-owning callable reference.
#pragma once
#include <memory>
#include <type_traits>
#include <utility>
namespace base {
template <class Sig> class FunctionRef;
template <class R, class... A>
class FunctionRef<R(A...)> {
 public:
  template <class F, class = std::enable_if_t<!std::is_same_v<std::decay_t<F>, FunctionRef>>>
  FunctionRef(F&& f)  // NOLINT: implicit, as base's.
      : obj_(const_cast<void*>(static_cast<const void*>(std::addressof(f)))),
        call_([](void* o, A... a) -> R { return (*static_cast<std::remove_reference_t<F>*>(o))(std::forward<A>(a)...); }) {}
  R operator()(A... a) const { return call_(obj_, std::forward<A>(a)...); }
 private:
  void* obj_;
  R (*call_)(void*, A...);
};
}  // namespace base

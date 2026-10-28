// Tark iOS: ONNX Runtime is linked in statically (the iOS xcframework is a
// static library, and apps may not load their own dylibs from paths), so
// "loading" it hands back the linked entry point.
#pragma once
#include <cstring>
#include <string>
#include "base/files/file_path.h"
#include "onnxruntime_c_api.h"
namespace base {
using NativeLibrary = void*;
struct NativeLibraryLoadError { std::string ToString() const { return "static"; } };
inline NativeLibrary LoadNativeLibrary(const FilePath&, NativeLibraryLoadError*) {
  return reinterpret_cast<void*>(&OrtGetApiBase);
}
inline void* GetFunctionPointerFromNativeLibrary(NativeLibrary library, const char* name) {
  return std::strcmp(name, "OrtGetApiBase") == 0 ? library : nullptr;
}
inline void UnloadNativeLibrary(NativeLibrary) {}
}  // namespace base

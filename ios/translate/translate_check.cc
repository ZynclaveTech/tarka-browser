// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// translate_check <models_dir> <direction 0|1> <language> < sentences.txt:
// prints each translation and its time (ms), then the process's peak memory.
#include <sys/resource.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>

#include "tark_translate_c.h"

int main(int argc, char** argv) {
  if (argc != 4) {
    std::fprintf(stderr, "usage: translate_check <models_dir> <0|1> <language>\n");
    return 2;
  }
  TarkTranslator* t = tark_translator_create(argv[1], static_cast<TarkTranslateDirection>(std::atoi(argv[2])));
  if (!t) {
    std::fprintf(stderr, "no translator\n");
    return 1;
  }
  std::string line;
  int failed = 0;
  while (std::getline(std::cin, line)) {
    const auto start = std::chrono::steady_clock::now();
    char* out = tark_translator_translate(t, line.c_str(), argv[3]);
    const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    std::printf("%6.0f ms  %s\n", ms, out ? out : "(failed)");
    failed += out == nullptr;
    tark_translate_free(out);
  }
  tark_translator_destroy(t);
  rusage usage;
  getrusage(RUSAGE_SELF, &usage);
  std::printf("peak memory %.0f MB\n", usage.ru_maxrss / 1048576.0);
  return failed ? 1 : 0;
}

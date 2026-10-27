// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Host check for the standalone build: the model's goldens (Compare() copied
// from components/tark_xlit/model_unittest.cc), a few phrases through the C
// API, and per-word timings.
//
// Usage: golden_check <xlit-model.bin> <golden.tsv> <words-dir>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

#include "base/files/file_path.h"
#include "base/files/memory_mapped_file.h"
#include "base/strings/utf_string_conversions.h"
#include "components/tark_xlit/model.h"
#include "tark_xlit_c.h"

namespace {

using tark_xlit::Candidate;

constexpr size_t kGoldenLines = 60 * 21;
constexpr double kTie = 1e-4;
constexpr double kScoreTolerance = 1e-3;

struct GoldenCandidate {
  std::string text;
  double score = 0;
};

std::string Num(double value) {
  std::ostringstream out;
  out.precision(6);
  out << value;
  return out.str();
}

std::string Describe(const std::vector<GoldenCandidate>& want,
                     const std::vector<Candidate>& got) {
  std::string out = "\n    want:";
  for (const GoldenCandidate& candidate : want) {
    out += " " + candidate.text + "|" + Num(candidate.score);
  }
  out += "\n    got: ";
  for (const Candidate& candidate : got) {
    out += " " + base::UTF16ToUTF8(candidate.text) + "|" + Num(candidate.score);
  }
  return out;
}

// Verbatim logic of model_unittest.cc's Compare().
std::string Compare(const std::vector<GoldenCandidate>& want,
                    const std::vector<Candidate>& got) {
  if (want.size() != got.size()) {
    return "expected " + std::to_string(want.size()) + " candidates, got " +
           std::to_string(got.size()) + Describe(want, got);
  }
  for (size_t i = 0; i < got.size(); ++i) {
    const std::string text = base::UTF16ToUTF8(got[i].text);
    std::optional<size_t> found;
    for (size_t j = 0; j < want.size(); ++j) {
      if (want[j].text == text) {
        found = j;
      }
    }
    if (!found) {
      return "candidate " + std::to_string(i) + " is not a reference " +
             "candidate" + Describe(want, got);
    }
    if (*found != i && std::abs(want[*found].score - want[i].score) >= kTie) {
      return "candidate " + std::to_string(i) + " is out of order" +
             Describe(want, got);
    }
    const double expected = want[*found].score;
    if (std::abs(got[i].score - expected) > kScoreTolerance * expected) {
      return "candidate " + std::to_string(i) + " score differs" +
             Describe(want, got);
    }
  }
  return std::string();
}

std::vector<std::string_view> Split(std::string_view text, char separator) {
  std::vector<std::string_view> out;
  size_t start = 0;
  while (true) {
    const size_t end = text.find(separator, start);
    out.push_back(text.substr(start, end - start));
    if (end == std::string_view::npos) {
      return out;
    }
    start = end + 1;
  }
}

double Percentile(std::vector<double> values, double p) {
  std::sort(values.begin(), values.end());
  const size_t index = static_cast<size_t>(
      std::ceil(p * static_cast<double>(values.size()))) - 1;
  return values[std::min(index, values.size() - 1)];
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
    std::fprintf(stderr, "usage: %s <xlit-model.bin> <golden.tsv> <words-dir>\n",
                 argv[0]);
    return 2;
  }
  const std::string model_path = argv[1];
  const std::string words_dir = argv[3];

  // (a) Goldens through Model::Transliterate.
  std::unique_ptr<tark_xlit::Model> model;
  {
    base::MemoryMappedFile file;
    if (!file.Initialize(base::FilePath(model_path))) {
      std::fprintf(stderr, "cannot map %s\n", model_path.c_str());
      return 1;
    }
    const auto start = std::chrono::steady_clock::now();
    model = tark_xlit::Model::Load(file.bytes());
    const double ms = std::chrono::duration<double, std::milli>(
                          std::chrono::steady_clock::now() - start)
                          .count();
    if (!model) {
      std::fprintf(stderr, "Model::Load failed\n");
      return 1;
    }
    std::printf("Model::Load: %.1f ms\n", ms);
  }

  std::ifstream golden_file(argv[2], std::ios::binary);
  std::stringstream buffer;
  buffer << golden_file.rdbuf();
  const std::string golden = buffer.str();
  if (golden.empty()) {
    std::fprintf(stderr, "cannot read %s\n", argv[2]);
    return 1;
  }

  size_t lines = 0;
  std::vector<std::string> mismatches;
  std::vector<std::string> hindi_words;
  for (std::string_view line : Split(golden, '\n')) {
    if (line.empty()) {
      continue;
    }
    const std::vector<std::string_view> fields = Split(line, '\t');
    if (fields.size() < 3) {
      std::fprintf(stderr, "bad line: %.*s\n", static_cast<int>(line.size()),
                   line.data());
      return 1;
    }
    ++lines;
    std::vector<GoldenCandidate> want;
    for (size_t i = 2; i < fields.size(); ++i) {
      const size_t bar = fields[i].rfind('|');
      if (bar == std::string_view::npos) {
        std::fprintf(stderr, "bad field in: %.*s\n",
                     static_cast<int>(line.size()), line.data());
        return 1;
      }
      const std::string score(fields[i].substr(bar + 1));
      char* end = nullptr;
      GoldenCandidate candidate;
      candidate.text = std::string(fields[i].substr(0, bar));
      candidate.score = std::strtod(score.c_str(), &end);
      if (end != score.c_str() + score.size()) {
        std::fprintf(stderr, "bad score in: %.*s\n",
                     static_cast<int>(line.size()), line.data());
        return 1;
      }
      want.push_back(std::move(candidate));
    }
    if (fields[0] == "hi") {
      hindi_words.emplace_back(fields[1]);
    }
    const std::string problem =
        Compare(want, model->Transliterate(fields[1], fields[0]));
    if (!problem.empty()) {
      mismatches.push_back(std::string(fields[0]) + " " +
                           std::string(fields[1]) + ": " + problem);
    }
  }
  std::printf("golden: %zu/%zu lines match (expected %zu lines)\n",
              lines - mismatches.size(), lines, kGoldenLines);
  for (size_t i = 0; i < std::min<size_t>(mismatches.size(), 10); ++i) {
    std::printf("  MISMATCH %s\n", mismatches[i].c_str());
  }
  const bool golden_ok = mismatches.empty() && lines == kGoldenLines;

  // (c) Per-word time, uncached (the model itself has no cache), for hi.
  std::vector<double> times;
  for (int round = 0; round < 3; ++round) {
    for (const std::string& word : hindi_words) {
      const auto start = std::chrono::steady_clock::now();
      const std::vector<Candidate> got = model->Transliterate(word, "hi");
      times.push_back(std::chrono::duration<double, std::milli>(
                          std::chrono::steady_clock::now() - start)
                          .count());
      if (got.empty()) {
        std::fprintf(stderr, "no candidates for %s\n", word.c_str());
      }
    }
  }
  model.reset();

  // (b) Phrases through the C API, hi and ta word lists.
  const std::string hi = words_dir + "/xlit-words-hi.bin";
  const std::string ta = words_dir + "/xlit-words-ta.bin";
  const char* const word_paths[] = {hi.c_str(), ta.c_str()};
  TarkXlit* handle = tark_xlit_new(model_path.c_str(), word_paths, 2);
  if (!handle) {
    std::fprintf(stderr, "tark_xlit_new failed\n");
    return 1;
  }
  struct Sample {
    const char* input;
    const char* tag;
  };
  const Sample samples[] = {
      {"namaste bharat", "hi"},
      {"heart attack ke lakshan", "hi"},
      {"Mera Naam Sooraj hai, 2026!", "hi"},
      {"vanakkam chennai", "ta"},
      {"tamil nadu weather", "ta"},
      {"hello world", "hi"},
  };
  bool api_ok = true;
  for (const Sample& sample : samples) {
    char* out = tark_xlit_phrase(handle, sample.input, sample.tag);
    std::printf("phrase [%s] %-30s -> %s\n", sample.tag, sample.input,
                out ? out : "(null: unchanged)");
    tark_xlit_string_free(out);
  }
  if (!tark_xlit_phrase(handle, "namaste", "hi")) {
    api_ok = false;
  }
  std::printf("looks_transliterable(\"namaste bharat\")=%d (\"नमस्ते\")=%d\n",
              tark_xlit_looks_transliterable("namaste bharat"),
              tark_xlit_looks_transliterable("नमस्ते"));
  if (tark_xlit_looks_transliterable("namaste bharat") != 1 ||
      tark_xlit_looks_transliterable("नमस्ते") != 0) {
    api_ok = false;
  }
  tark_xlit_free(handle);
  if (!tark_xlit_new("/nonexistent", nullptr, 0)) {
    std::printf("tark_xlit_new(missing file) = NULL, as expected\n");
  } else {
    api_ok = false;
  }

  std::printf("hi uncached word time over %zu calls: p50 %.2f ms, p95 %.2f ms\n",
              times.size(), Percentile(times, 0.50), Percentile(times, 0.95));

  {
    for (const char* list : {"hi-IN,en-GB", "en-IN,ta-IN,bn", "en-US", "kok,mr"}) {
      char* langs = tark_xlit_row_languages(list);
      std::printf("row_languages(%s) = %s\n", list, langs);
      tark_xlit_string_free(langs);
    }
  }
  return golden_ok && api_ok ? 0 : 1;
}

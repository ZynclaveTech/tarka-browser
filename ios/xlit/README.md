# tark_xlit outside Chromium

Builds Tark's transliteration engine (`components/tark_xlit`: model, word_list,
transliterator, languages, blas_accelerate) with plain `clang++ -std=c++20` and
Apple's Accelerate, for the iOS app. The engine sources are used unmodified.

- `shim/base/...` — minimal standard-C++20 versions of exactly the //base
  headers the engine includes (span, span_reader, heap_array, values,
  json_reader, memory_mapped_file, file_path/file_util/file_enumerator,
  path_service, ref_counted, raw_ptr, bind/callback, check, ...).
  `shim/base_shim.cc` holds the out-of-line parts (JSON parser, UTF-8/16,
  mmap, directory listing).
- `tark_xlit_c.h` / `.cc` — C API for Swift (`tark_xlit_new`,
  `tark_xlit_phrase`, `tark_xlit_looks_transliterable`, `tark_xlit_free`,
  `tark_xlit_string_free`). A handle is mutex-guarded; see the header.
- `golden_check.cc` — runs golden.tsv through `Model::Transliterate` with
  model_unittest.cc's `Compare()` logic, some phrases through the C API, and
  per-word timings.

## Run

    ./build_host.sh

Paths default to the Tark checkout (`build/ios/xlit-src`,
`build/src/third_party/indicxlit/xlit-model.bin`, `build/ios/xlit-files`,
`resources/xlit/golden.tsv`); override with `XLIT_SRC_ROOT`, `XLIT_MODEL`,
`XLIT_WORDS_DIR`, `XLIT_GOLDEN`, `XLIT_OUT`. Compiles with
`-Wall -Wextra -Werror` (`-Wno-unused-parameter`), exits with golden_check's
status.

## Results (Mac host, 2026-10-27)

    Model::Load: 52.8 ms
    golden: 1260/1260 lines match
    [hi] namaste bharat              -> नमस्ते भारत
    [hi] heart attack ke lakshan     -> heart attack के लक्षण
    [hi] Mera Naam Sooraj hai, 2026! -> मेरा नाम सूरज है, 2026!
    [ta] vanakkam chennai            -> வணக்கம் chennai
    hi uncached word: p50 26 ms, p95 43 ms (180 calls)

## Differences from Chromium

- `PathService::Get` always fails, so `LoadFromBundle()` returns nullptr;
  iOS loads by explicit path through the C API.
- `CHECK`s abort with a message in every build; `raw_ptr` / `raw_span` are
  plain pointers/spans; `STACK_ALLOCATED` is not enforced.
- `FileEnumerator` is non-recursive only (all the engine uses).
- Built with Apple's classic CBLAS and `-Wno-deprecated-declarations`, as
  BrowserKit's TarkXlitCore target is (the new LAPACK headers need iOS 16.4;
  Tark for iOS supports iOS 15).

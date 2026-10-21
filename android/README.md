# Tark for Android (A1)

Tark's Android build: ungoogled-chromium's core patches plus Tark's patches,
built for arm64 phones on a Linux machine (an AWS EC2 instance; Chromium
builds for Android only on Linux). There is no maintained upstream
ungoogled-chromium Android repository, so this layer does the build steps
itself. Everything else (patches, scripts, fixes) is done on the Mac.

- `series.py REPO OUT` — Tark's Android series: the `tarka/` entries of
  `patches/series` minus `desktop-only-patches.txt`. The build applies
  ungoogled-chromium's own series first, then this one.
  Test: `pytest utils/tests/test_android_series.py`.
- `patches/` — Android-only Tark patches with their own `series`, applied
  after the shared ones. They live outside `patches/tarka/` so the Mac and
  Windows builds never apply them.
- `desktop-only-patches.txt` — Tark patches that cannot or must not apply on
  Android, with the reason. Desktop-only patches whose files exist in the
  Android tree stay in: they apply and are simply not compiled.
- `args.gn` — Tark's Android gn args, appended to the core `flags.gn`
  (package `com.gettarka.tarka`, arm64, official build, no PGO).
- `gclient.android` — the core gclient config with Android added; `UC_OUT`
  is filled in by `build.sh` (ungoogled's `clone.py -c` does not).

# Building Tark

## Requirements

Apple Silicon Mac, macOS 12 or later, Xcode 26 with the Metal toolchain
(`xcodebuild -downloadComponent MetalToolchain`), Homebrew, and:

```sh
brew install python@3.13 ninja coreutils readline esbuild typescript quilt wget zstd
/opt/homebrew/opt/python@3.13/libexec/bin/pip install --break-system-packages PySocks httplib2 requests pillow
brew unlink binutils   # if installed; the Xcode one must win
```

`dev.sh` and `build.sh` put Python 3.13 first on `PATH` themselves; the
system Python 3.14 is too new for depot_tools.

## First build (development)

```sh
./dev.sh setup   # download the Chromium tarball, prune, patch, substitute, gn gen
./dev.sh build   # ninja chrome; incremental afterwards
./dev.sh run     # launches the app with --user-data-dir=build/profile
```

The development build (`flags.dev.gn`) is a static build with no LTO, no
PGO, no symbols and no precompiled headers: it fits an 18 GB machine and
relinks in a few minutes. It is not what ships. Two configurations were
tried and rejected: precompiled headers (the Chromium clang rejects
`-fmodule-name` on a `-x c++-header` compile) and a component build (shared
libraries that pull in the nightly Rust std without Rust code of their own
fail to link the allocator symbols). `TARKA_JOBS` sets ninja's parallelism (default 8; 11 cores
and 18 GB swap at 13).

Builds longer than a couple of minutes should run in the background with
their output in `build/logs/`; `./dev.sh build` tees there itself.

## Release build

```sh
./dev.sh reset
MACOS_AD_HOC_SIGNING=1 ./build.sh -d -m release arm64
```

`build.sh` is upstream's one-shot script: it re-extracts the tarball into
`build/src`, applies the patches with `patches.py` (not quilt), and builds
with `is_official_build=true` and ThinLTO. It assumes a fresh tree, so run
`./dev.sh reset` first; `devutils/check_clean_tree.sh` makes it refuse to
start otherwise. `-d` downloads the source tarball instead of cloning
Chromium, and tarball builds have no PGO profile, so `build.sh` turns PGO
off for them. The `.dmg` lands in `build/`. Without `MACOS_AD_HOC_SIGNING=1`
it expects the Developer ID variables documented in `sign_and_package_app.sh`.
Afterwards `./dev.sh reset && ./dev.sh setup` restores the development tree.

## Resetting

```sh
./dev.sh reset   # removes build/src (and the name-substitution backup); keeps build/download_cache
```

If a download failed, remove `build/download_cache` and run `setup` again.

## Disk and time

First development build, 2026-10-16/17, Apple M3 Pro (11 cores), 18 GB,
8 ninja jobs, Chromium 155.0.8059.39:

| Step | Time | Size |
|---|---|---|
| `dev.sh setup` (tarball 1.9 GB + toolchain 0.9 GB, prune, patch, substitute, gn bootstrap, gn gen) | 42 min | `build/download_cache` 2.7 GB |
| `dev.sh build` chrome, static dev flags, from scratch | about 5 h 15 min of compile (22:02 → 03:16) plus three restarts for the fixes below | `build/src` 26 GB, of which `out/Default` 11 GB |
| App bundle | — | `Chromium.app` 713 MB unstripped |
| Disk after | — | 79 GB free, from 121 GB before setup |

Three configuration fixes were needed before the first link succeeded,
each now in the repo: precompiled headers off (`flags.dev.gn`), static
instead of component build (`flags.dev.gn`), and
`patches/tarka/core/fix-link-without-managed-profile-creation.patch`
(see the patch header). Incremental rebuilds after a one-file change
take a few minutes, dominated by the framework link.

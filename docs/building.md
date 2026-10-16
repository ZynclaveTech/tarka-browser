# Building Tarka

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

The development build (`flags.dev.gn`) is a component build with no LTO, no
PGO and no symbols: it links in seconds and fits an 18 GB machine. It is
not what ships. `TARKA_JOBS` sets ninja's parallelism (default 8; 11 cores
and 18 GB swap at 13).

Builds longer than a couple of minutes should run in the background with
their output in `build/logs/`; `./dev.sh build` tees there itself.

## Release build

```sh
MACOS_AD_HOC_SIGNING=1 ./build.sh -d -m release arm64
```

`-d` downloads the source tarball instead of cloning Chromium. `build.sh`
deletes `build/src/out` first and builds from scratch with
`is_official_build=true` and ThinLTO. The `.dmg` lands in `build/`. Without
`MACOS_AD_HOC_SIGNING=1` it expects the Developer ID variables documented in
`sign_and_package_app.sh`.

## Resetting

```sh
./dev.sh reset   # removes build/src (and the name-substitution backup); keeps build/download_cache
```

If a download failed, remove `build/download_cache` and run `setup` again.

## Disk and time

Filled in after the first build.

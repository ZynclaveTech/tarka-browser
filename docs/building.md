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

### First release build (2026-10-17)

`./build.sh -d -m release arm64` on the 18 GB M3 Pro: official flags, ThinLTO,
no PGO (tarball build). Compile and link 5 h 10 min at 8 jobs, with other
work running alongside; **the ThinLTO link of the framework succeeded within
18 GB**, so release builds do not need a bigger machine. Results:

| Artefact | Size |
|---|---|
| `build/Tarka_155.0.8059.39-1.1_macos.dmg` | 147 MB |
| `Tarka.app` | 390 MB (framework binary 260 MB) |

Ad-hoc signing needed one change: macOS 26 refuses to load the framework
into a process signed with library validation or the hardened runtime when
the signature has no Team ID, which an ad-hoc one never has. Ad-hoc signing
therefore leaves both out (`sign()` in `sign_and_package_app.sh`); Developer
ID signing for notarized releases keeps them. Verified: the release app
renders a page and runs JavaScript headlessly. Open for M5: strict
verification (`codesign --verify --deep --strict`) flags a `FinderInfo`
attribute on `Helpers/app_mode_loader` inside the dmg, which notarization
will reject; clear it before signing.

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

## M4 notes

**Checking what Tark contacts.** Start a new profile with a net log and
leave it alone for two minutes, quit, then check every contacted host
against the §5.3 list:

```sh
open -n build/src/out/Default/Tark.app --args --user-data-dir=/tmp/tark-fresh \
  --use-mock-keychain --log-net-log=/tmp/tark-idle.json
# two minutes, no input; then quit Tark
python3 utils/net_hosts.py /tmp/tark-idle.json --allowed utils/allowed_hosts.txt
```

It counts DNS lookups, request starts and QUIC sessions only, so hosts
named inside response headers (Cloudflare's `report-to`, CSP `report-uri`)
are not counted; Chromium's Reporting and NEL are compiled out
(`enable_reporting=false`). It exits 1 if any host is not on the list. Its
blind spot: a connection to a bare IP address with no URL request (a
preconnect) makes no DNS lookup and is not counted.

**uBlock Origin "off" across a browser update** (Review Focus 4, checked by
reading, not by test). A new uBlock version re-registers the component
extension; `ExtensionRegistrar::AddComponentExtension` asks
`GetDisableReasonsOnInstalled`, which keeps the user's `DISABLE_USER_ACTION`
because Helium's hunk makes `MustRemainEnabled` false for uBlock. Re-check
this on every Chromium or uBlock bump.

Result on 2026-10-17 (dev build with all of M4 Tasks 1 to 8, new
profile, first-run on, two idle minutes): `shodhya.com` (16),
`ublockorigin.github.io` (7), `ublockorigin.pages.dev` (7),
`cdn.jsdelivr.net` (6), `malware-filter.gitlab.io` (3), `pgl.yoyo.org` (3),
`publicsuffix.org` (3). Not allowed: none. Shodhya is the new tab page;
the rest are uBlock Origin's first filter-list fetch.

**The Web Store in a private window** (Review Focus 5). The store page in a
private window has the same install API and shows "Remove from Tark" for an
installed extension. Run end to end (final review): in a private window the
store shows "You can't add or remove items when in Incognito or Guest mode"
and disables "Add to Tark", so it says why instead of failing silently.

## M3 notes

**WebUI pages and Paper.** Settings, Extensions, History, Downloads and
Bookmarks always load the theme colours (`chrome://theme/colors.css`), which
carry Tark's palette from the colour mixer; Chromium loads them only behind
its unreleased 2026 redesign flags. Inter is served from
`chrome://resources/fonts/` (copied from `resources/fonts/` by `dev.sh` and
`build.sh`; licence `resources/fonts/Inter-OFL.txt`). Recoloured, not Paper:
the side menus of Extensions and History keep Chromium's pill highlight for
the current item (their own navigation styles, outside the shared Settings
menu).

**Re-running name substitution in a dev tree** (M3 Task 7). `utils/name_substitution.py`
skips Quilt's `.pc` backups, so after `--sub` on an existing dev tree, do not
refresh older patches that touch `chrome/app/generated_resources.grd` or
`chrome/app/settings_strings.grdp`; they would absorb the substitution. A clean
`./dev.sh reset && ./dev.sh setup` has no such caveat.

**Settings strings** (M3 Tasks 12–15). Tark's settings patches add their
strings as new `IDS_SETTINGS_TARK_*` messages inside Tark's own block of
`settings_strings.grdp` and point templates at the new keys; they never
rename Chromium's messages in place. Patches apply before name
substitution, so a hunk whose context is an upstream message would not
match a clean tree if the dev tree's copy had been substituted, and a
renamed upstream message would orphan its translations in every locale.
The strings reach the page through `tark::AddTarkSettingsStrings()`
(`chrome/browser/ui/webui/settings/tark_settings_strings.cc`).

**Settings layout.** The home grid, the eight-item menu, Advanced's stacked
sections and the section header are Tark elements under
`chrome/browser/resources/settings/tark/` plus edits to `route.ts`,
`settings_main` and `settings_menu`. One shared rule outside Settings:
`cr_view_manager.css` lets views flow (instead of stacking at the top)
under the custom property `--tark-view-flow: 1`, which only Advanced sets.

**Checking pages without stealing focus.** Capture WebUI pages through
DevTools (`Page.captureScreenshot` on a `--remote-debugging-port` build)
rather than bringing the window forward; a frontmost capture can catch
keystrokes meant for another app.

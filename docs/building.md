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

## M3b notes (no Chrome)

**Brand files.** Chromium's logo files (vector icons, PNGs, SVGs) are
replaced whole by `utils/install_branding.py`, which `dev.sh setup` and
`build.sh` run after name substitution, as they copy `app.icns`. The files
are generated by `python3 utils/mark.py --out resources/branding/mark` from
the list in `resources/branding/mark/install.txt` (kind, size, palette,
destination) and committed; a test regenerates each and compares bytes. If a
Chromium update moves a listed file, the installer fails and names it.

**Words outside .grd files.** `utils/name_substitution.py` also renames
Chrome/Chromium inside string literals of the flag-description headers and
in the text of a few HTML pages (`LITERAL_FILES`). In a dev tree that was
already substituted, `--sub --only-literals` runs just that part. As with
the .grd caveat above, do not refresh an older patch touching one of those
files from a dev tree.

**The tark:// scheme.** `tark` and `tarka` are standard schemes mapped to
`chrome` by the URL fixer (typed, pasted, extension-opened) and by a URL
handler (links, bookmarks); pages keep their chrome:// URLs. Display code
swaps the shown prefix in the address bar, copy, suggestions, hover cards,
the bookmark editor, untitled tab titles and error pages.

**Auditing.** `python3 utils/brand_audit.py PORT` opens every page
chrome://chrome-urls lists in a dev build started with
`--remote-debugging-port=PORT --disable-crash-on-webui-js-error` and
reports leftover words and chrome:// addresses in tab titles and error
pages. Enable internal debugging pages on chrome://chrome-urls first to
include them (reported, not counted). Dialog-only pages are skipped: a dev
build stops on them when opened as tabs.

**Verifying without taking the user's keyboard.** Launch with `open -g` and
hand focus back, open tabs with DevTools `Target.createTarget` and
`background: true`, capture pages with `Page.captureScreenshot` and native
windows with `screencapture -l <window id>`, and read the address bar
through Accessibility. Never bring the window forward to screenshot it.

## M3c notes (one row, the Tark sheet)

- **Two Tarks on one Mac.** Once the user runs an installed Tark, AppleScript
  `tell application "Tark"` / `process "Tark"` can reach *their* browser,
  not the dev build — both have the same name and bundle id. Address the dev
  build only by its process id: launch with `open -g -n` on
  `out/Default/Tark.app`, find it with `pgrep -f "out/Default/Tark.app/.../Tark --user-data-dir"`,
  stop it with `pkill -f` on that same path (never `quit app "Tark"`), and
  read or press its controls through `AXUIElementCreateApplication(pid)`
  (a 30-line Swift helper), never System Events by name.
- **Fullscreen moves the user's screen.** `Browser.setWindowBounds`
  `windowState: fullscreen` puts the window in its own Space and macOS
  switches to it; fullscreen checks are user-assisted.
- **Views gotchas met here.** `FlexSpecification::WithOrder` DCHECKs on
  orders below 1; a view with no height is `IsEmpty()`, so test widths
  when a placeholder only carries width; a custom `FlexRule` plus
  `WithOrder` is allowed and is how the tab well shares the row.
- **Inherited defaults to check.** inox's `0006-modify-default-prefs`
  flips several prefs Tark does not want: `kShowBookmarkBar` (now false
  again, `tarka/shape/bookmarks-bar-default.patch`) and
  `kCredentialsEnableService` (now true again,
  `tarka/settings/offer-to-save-passwords.patch`); read that patch before
  assuming a Chromium default.
- **Copyright.** Name substitution writes "Zynclave Tech Private Limited"
  for "(The) Chromium Authors" in UI strings and translations;
  `branding.patch` sets the company and the Finder copyright line.

## D1: IndicXlit

`./dev.sh setup` and `build.sh` fetch Tark's on-device transliteration
model, convert it and install it (`utils/install_xlit.sh`, the function
`_install_xlit`, run after uBlock Origin's sources are unpacked).

- **Fetched** (`downloads-xlit.ini`, into `build/download_cache`, about
  138 MB, once; later runs find the files and only re-check their sha256):
  AI4Bharat IndicXlit's checkpoint `indicxlit.pt` and the dictionaries
  `dict.en.txt` and `dict.hi.txt`, pinned to one Hugging Face commit. They
  are retrieved only, never unpacked: the checkpoint is a zip that
  `downloads.py unpack` would try to extract.
- **Written** to `build/src/third_party/indicxlit/`: `xlit-model.bin`
  (23 MB; `utils/xlit_convert.py` turns the checkpoint into a flat fp16
  file, with no torch needed), `xlit-words.bin` (37 MB; `utils/xlit_wordlist.py pack`
  of `resources/xlit/`), and `README.chromium` plus `LICENSE` from
  `resources/indicxlit/`, so about:credits lists IndicXlit.
- **Also copied** to `build/src/components/tark_xlit/test/data/`: both
  `.bin` files, `golden.tsv` and `golden-inputs.txt`, for the unit tests.
- The conversion is deterministic: `xlit-model.bin` has sha256
  `3cfe73d2…cbd2fc`, and `xlit-words.bin` is 36,688,088 bytes. To redo the
  step on an existing tree without a reset, source the function and call it
  (see the variables at the top of `utils/install_xlit.sh`).
- Test: `python3 -m pytest utils/tests/test_install_xlit.py`.

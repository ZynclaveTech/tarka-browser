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

## D1 notes (the address bar)

D1 is seven patches at the end of `patches/series`: `omnibox-sources/`
(the `@` sources, and `@wiki` opening the Wikipedia of the query's
language), `omnibox-translit/` (the on-device component, the provider, the
row label, and the row fixes) and `core/webui-js-error-no-crash.patch`.

- **Tests:** `ninja -C out/Default tark_xlit_unittests tark_xlit_bench`, then
  `out/Default/tark_xlit_unittests` (65 tests, 1,260 golden phrases, about
  25 s) and `out/Default/tark_xlit_bench` (model load about 70 ms; p95 per
  phrase 34–43 ms for Hindi, Tamil and Bengali, against a 50 ms budget).
- **Where the rows come from:** `TarkTransliterationProvider` uses the
  provider type `TYPE_QUERY_TILE`, which Chromium does not use on desktop;
  its rows carry `additional_info["tark_xlit_lang"]`.
  `translit-rows-fixes.patch` keys two upstream behaviours off those: the
  controller keeps the rows' own description (the language name) instead of
  the engine name, and does not carry the previous text's rows into the
  first result for new text. Both are easy to lose in a rebase, and the
  unit tests do not cover them: check `namaste` in a running build (rows
  labelled हिन्दी on the right; no `namast` rows flashing first).
- **Rebase trap: starter-pack ids.** The ten `@` sources are starter-pack
  entries 7–16 and `kCurrentDataVersion` is 16. When an upstream bump adds
  its own starter-pack entries, renumber Tark's above upstream's and bump
  the version past both, or a profile keeps whichever entry got the id
  first.
- **WebUI JavaScript errors no longer crash a build.** Unofficial builds
  (every Tark build until M5) used to `LOG(FATAL)` on a JavaScript error in
  some WebUI pages, the omnibox popup among them. Pass
  `--tark-crash-on-webui-js-error` to get the crash back while developing.
- **Packaging a DMG to share.** `pkg-dmg`'s HFS hybrid image gave every
  file `com.apple.FinderInfo`, so an app dragged out of it failed
  `codesign --verify --deep --strict` ("resource fork, Finder information,
  or similar detritus"). Since M5 `sign_and_package_app.sh` packages with
  `utils/package_dmg.sh` instead (an APFS image from a copy without
  extended attributes), which refuses to keep an image whose app does not
  verify.

## Release signing (M5)

A release is signed with the team's **Developer ID Application**
certificate, notarized, and stapled: the app, then the DMG (which is also
code-signed, so Gatekeeper reports it as Notarized Developer ID):

    MACOS_CERTIFICATE_NAME="Developer ID Application: <name> (UMTJNNPK6C)" \
      CHROMIUM_SRC_DIR=$PWD/build/src ./sign_and_package_app.sh out.dmg

- **Once per Mac:** the certificate in the login keychain (Xcode →
  Settings → Accounts → Manage Certificates → + → Developer ID
  Application; only the team's Account Holder can create it), and the
  notarization login saved as a keychain profile:
  `xcrun notarytool store-credentials tark-notary --apple-id <Apple ID>
  --team-id UMTJNNPK6C`, with an app-specific password from
  account.apple.com. `TARKA_NOTARY_PROFILE` names another profile.
- **Check a release:** `spctl -a -vvv -t exec Tark.app` says
  `source=Notarized Developer ID`; `xcrun stapler validate out.dmg` passes.
- `MACOS_AD_HOC_SIGNING=1` (shareable, no notarization) and
  `MACOS_DEV_SIGNING=1` (this Mac only, Touch ID passkeys) still work and
  skip notarization.
- Test: `python3 -m pytest utils/tests/test_package_dmg.py`.

## Updates (Sparkle, M5)

Tark updates itself with [Sparkle 2](https://sparkle-project.org) (MIT),
the official prebuilt release pinned in `downloads-sparkle.ini` and
unpacked to `build/src/third_party/sparkle` by `dev.sh setup` and
`build.sh`.

- **In the app:** `patches/tarka/updater/sparkle.patch` makes
  `AppController` load `Contents/Frameworks/Sparkle.framework` at launch
  and start `SPUStandardUpdaterController`, and adds "Check for Updates…"
  under "About Tark". Nothing links against Sparkle: a build without the
  framework (a dev build run from `out/Default` before signing) has no
  updater and the menu item stays disabled.
- **At signing:** `sign_and_package_app.sh` runs `utils/install_sparkle.sh`,
  which copies the framework in without its XPC services (only sandboxed
  apps need them), writes `SUFeedURL` (https://gettarka.com/appcast.xml),
  `SUPublicEDKey`, a daily automatic check that installs updates when Tark
  quits (`SUAutomaticallyUpdate`), no system profiling, and sets
  `CFBundleVersion` to `BUILD.PATCH.REVISION` from `revision.txt`, so two
  releases of one Chromium version still order correctly. Sparkle's
  Autoupdate and Updater.app are signed before its framework, all before
  the app. `TARKA_SPARKLE_FEED_URL` and `TARKA_REVISION` override the feed
  and revision for tests.
- **The key:** the EdDSA private key is in the release Mac's login
  keychain, account `tark` (`third_party/sparkle/bin/generate_keys
  --account tark -p` prints the public half). Back it up once with
  `generate_keys --account tark -x <file>` and keep the file offline:
  without it no installed Tark can ever be updated again.
- **Publishing:** gettarka-site's `publish.sh` runs `generate_appcast
  --account tark` over `releases/feed/` (signed, notarized DMGs only) and
  uploads `appcast.xml` (five-minute cache) and any delta files.
- **Bump `revision.txt`** for every Tark release on the same Chromium
  version; reset it to 1 on a new Chromium version.
- Tests: `python3 -m pytest utils/tests/test_install_sparkle.py`.

## Live captions (D4)

- **ONNX Runtime** runs the caption models: Microsoft's official macOS
  arm64 release (MIT), pinned by hash in `downloads-onnxruntime.ini` and
  unpacked into `build/src/third_party/tark_onnxruntime/` by `dev.sh` and
  `build.sh`. `components/tark_captions` compiles against its `include/` and
  `dlopen()`s `libonnxruntime.1.31.0.dylib` at run time, as Chromium does
  with SODA; nothing links against it. `sign_and_package_app.sh` copies the
  dylib into `Tark.app/Contents/Frameworks` (`utils/install_onnxruntime.sh`)
  and signs it with Tark's identity, because the speech helper runs with
  library validation. Bump: new version and hash in the ini, the dylib name
  in `install_onnxruntime.sh` and `sign_and_package_app.sh`, and check
  github.com/microsoft/onnxruntime/security/advisories first.
- **Telemetry stays off.** Microsoft's builds send telemetry unless
  `ORT_DISABLE_TELEMETRY=1` is set before the library loads;
  `components/tark_captions/ort_runtime.cc` sets it and also calls
  `DisableTelemetryEvents`, and refuses to run if that call fails.
- **The models** are not in the repository. `utils/captions_export.py export
  MODELS_DIR SILERO_VAD OUT_DIR` writes the folder the engine loads (int8
  IndicConformer encoder, CTC decoder, vocabulary, language masks, Silero
  VAD, the mel window and matrix) from IndicConformer's `assets/` and
  `silero_vad.onnx`. Tark reads it from
  `~/Library/Application Support/Tark/Captions/models`, and downloads what
  is missing from gettarka.com (Phase 4, below).
- **Tests:** set `TARK_CAPTIONS_ORT` (the dylib under
  `third_party/tark_onnxruntime/lib`), `TARK_CAPTIONS_MODELS` (the models
  folder) and `TARK_CAPTIONS_TESTDATA` (`resources/captions/testdata`), then
  run `out/Default/tark_captions_unittests` (engine) and
  `out/Default/tark_speech_unittests` (the speech service's recognizer).
  `golden.json` there comes from `captions_export.py golden`; the clips are
  FLEURS (CC-BY-4.0, test data only, see `ATTRIBUTION.md`).
- **Bench:** `out/Default/tark_captions_bench` with the same variables plays
  the test clips through the engine in real time and prints cores used,
  decode times and draft lag (Phase 1: 0.23 cores, draft lag 0.51 s).
- **Trying a call without a second device:** serve
  `resources/captions/testdata` on `127.0.0.1:8765` and open
  `loopback.html?clip=hi_1.wav`, which plays a clip as the remote side of a
  same-page WebRTC call. Give the test profile
  `{"webrtc":{"ip_handling_policy":"default"}}` in `Default/Preferences`
  (Tark hides local addresses, so the loopback never connects otherwise),
  grant the page the microphone, and launch with
  `--use-fake-device-for-media-stream`. Starting the microphone puts the tab
  in a call and the pill appears; `--vmodule=call_captions_tab_helper=1`
  logs each caption's kind and size (never its text).
- **Credits:** `utils/install_captions_credits.sh` (run by `dev.sh` and
  `build.sh`) puts `README.chromium` and `LICENSE` for ONNX Runtime,
  IndicConformer and Silero VAD under `third_party/`, from
  `resources/captions/credits/`, for about:credits.
- **Translation (Phase 2):** `utils/indictrans_export.py export INDIC_EN_DIR
  EN_INDIC_DIR OUT_DIR` turns AI4Bharat's IndicTrans2 distilled 200M
  checkpoints (MIT) into `it2_indic_en/` and `it2_en_indic/` in the models
  folder: an int8 ONNX encoder and cached decoder step, the SentencePiece
  model and vocabularies. It rebuilds the model in plain PyTorch, because
  AI4Bharat's code needs a transformers release with known vulnerabilities.
  `golden` writes `resources/captions/testdata/mt_golden.json`: every stage
  of the Python reference pipeline on 16 real captions. The C++ engine
  (`components/tark_captions/translation_engine.cc`, with the text steps
  ported from IndicNLP, IndicTransToolkit and sacremoses in `indic_text.cc`)
  must match it token for token, pivots included. Indian→Indian goes
  through English, feeding the English model tokens straight into the
  second hop.
- **Where translation runs:** `media.mojom.TarkCaptionTranslator` in the
  speech utility process (`chrome/services/speech/tark_caption_translator.cc`),
  bound through `SpeechRecognitionService.BindTarkCaptionTranslator`. Text
  from call audio is changed (English letters, another script) and
  translated in the sandbox, never in the browser. The tab helper sends one
  caption at a time (`RenderQueue`: the newest draft replaces a waiting one;
  finals all go; results asked with old choices are dropped). "Show their
  words in" and "Translate to" are remembered in local state
  (`CaptionChoices`); incognito keeps its changes in memory.
- **Bench:** `out/Default/tark_captions_bench --translate` (M3 Pro: 0.08 s
  per caption to English, 0.05 s per draft, 0.18 s Indian→Indian; peak
  1.12 GB with captions and one direction, 1.47 GB with both).
  `--romanize` prints the test captions in English letters to review the
  spellings.
- **Model downloads (Phase 4):** three units: captions (IndicConformer +
  Silero VAD), to English (`it2_indic_en/`), from English (`it2_en_indic/`).
  `utils/captions_manifest.py MODELS_DIR
  components/tark_captions/model_manifest.cc` writes the table of every
  file's size and SHA-256 compiled into Tark; `--check` compares a folder
  with it. `CaptionModelStore` downloads a unit's files from
  `https://gettarka.com/models/captions/v1/` (no cookies, system network
  context), checks each hash in `.download/`, then moves them in and writes
  `.ready-<unit>`. The pill waits for a missing unit with a progress bar;
  Settings › Accessibility › Live captions downloads, cancels and removes
  them. `--tark-captions-models-url=http://127.0.0.1:PORT/models/captions/v1/`
  points a test copy at a local server. Every published name has an
  extension: gettarka.com serves a path without one as `<path>/index.html`
  (so the IndicTrans2 licences ship as `LICENSE.txt`).
- **Publishing the models:** `utils/publish_caption_models.sh MODELS_DIR`
  (`--dry-run` first) checks the folder against the manifest, uploads each
  file once to the site bucket with an immutable cache header and its hash
  as metadata, and reads every file back through CloudFront. v1 never
  changes: new models go to `v2/` with a new manifest. gettarka-site's
  `publish.sh` keeps `models/` out of its `--delete` sync.

- **Auto-detect (Phase 3):** the speech process starts in "auto": Silero VAD
  keeps the client's speech, SpeechBrain's VoxLingua107 ECAPA (Apache-2.0,
  `utils/lid_export.py export` → `lid.onnx` + `lid_labels.txt`, fp32: int8
  lost 2.7% top-1) decides at 3 s of speech, 5 s when unsure
  (`components/tark_captions/detection_policy.cc`, tuned with
  `lid_export.py policy` on FLEURS: hi .96, ta .94, bn .96, en/es/fr/zh 1.0,
  Swahili called unsupported .96). The recognizer reports it as a
  LanguageIdentificationEvent and captions from the first word (what it
  heard is replayed); Apple languages go to the browser through
  `SpeechRecognitionService.BindTarkAudioTap` (Part B captions them).
  `language_id` is a download unit holding the detector and the VAD, so
  detection never needs the 679 MB captions unit. The pill's chip reads
  "Auto-detect", then "Tamil · detected"; a language Tark can't caption
  gets a line and "Choose a language".
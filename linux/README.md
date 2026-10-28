# Tark for Linux (L1)

Tark's Linux x64 build is upstream
[ungoogled-chromium-portablelinux](https://github.com/ungoogled-software/ungoogled-chromium-portablelinux)
plus Tark's patches and build steps, as `windows/` is for Windows. It builds
on the Android build machine (`tark-android-builder`, Ubuntu 24.04) in its
own folder; everything else (patches, scripts, fixes) is done on the Mac.
Design and plan: tarka-notes `specs/2026-10-28-tark-linux-design.md`,
`plans/2026-10-28-tark-linux.md`.

- `upstream/` — upstream's build scripts, Docker images, Linux platform
  patches and packaging at the tag in `upstream/UPSTREAM_COMMIT`
  (BSD-3-Clause, `upstream/LICENSE`). One local change, in
  `scripts/build.sh`: after patches and domain substitution it runs
  `tark_post_patch.py` once (`.tark.stamp`), then its ONNX Runtime step on
  every build (`--onnxruntime-only`, skipped when the headers are there). When bumping upstream, copy the
  new files over and re-add it.
- `prepare_workdir.py REPO WORKDIR` — assembles the folder `scripts/build.sh`
  runs in: upstream's files, this repo's `ungoogled-chromium` core, Tark's
  patches after the portablelinux ones (minus `mac-only-patches.txt`), Tark's
  gn args (`args.gn`) after upstream's `flags.linux.gn`, Tark's filtered
  domain substitution list. Test:
  `python3 -m unittest utils.tests.test_linux_workdir`.
- `tark_post_patch.py` — the steps every non-Mac desktop build shares
  (`utils/tark_post_patch_common.py`: name substitution, the mark, trust
  data, Inter, the ad blocker's crates and lists, IndicXlit). The captions'
  credits come with live captions (L2). Test: `python3 -m unittest utils.tests.test_post_patch_common`.
- `mac-only-patches.txt` — patches the Linux build leaves out.

## What Linux has (L1)

Open on Linux: the ad blocker (`adblock-desktop.patch`, which also builds
the Zynclave sign-in service), typing in your language
(`windows/xlit-provider.patch`), Sign in with Zynclave (the web offer and the
Settings card no longer sit inside the captions-only blocks).

Still Mac and Windows only, on purpose:

- **Live captions** (`windows/captions.patch`, the speech sandbox and ONNX
  Runtime patches): Linux needs ONNX Runtime and its sandbox rule first (L2).
- **Widevine opt-in** (`core/widevine-opt-in.patch`): context from
  Chromium's own Mac/Windows block, where the component installer lives.

Zynclave uses the Mac's OAuth client IDs on Linux (`ConfigFor()`; Windows
has its own). Ask Zynclave whether Linux should get its own client before
the first public Linux release.

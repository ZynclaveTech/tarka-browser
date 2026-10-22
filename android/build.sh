#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   android/build.sh [--stop-before-gn] WORKDIR
#
# Builds Tark for Android (A1) on a Linux x86-64 machine, the steps of the
# Mac's build.sh for an Android tree: clone Chromium with Android's
# dependencies (ungoogled's clone.py and android/gclient.android; no pruning),
# apply ungoogled-chromium's core patches then Tark's Android series, domain
# and name substitution, the mark, Inter, uBlock Origin's sources, IndicXlit,
# then gn and ninja.
# The APK lands in WORKDIR/src/out/Default/apks/ChromePublic.apk.
# WORKDIR/src-base keeps the base (Chromium and ungoogled's core patches)
# between builds, so a change to Tark's patches or steps alone rebuilds only
# what it changed (see the prepare section and android/layers.py).
#
# --stop-before-gn stops after the patches and Tark's steps with exit 3 (the
# patch-only job). TARK_ANDROID_DRYRUN=1 prints each external command as
# "tark: run ..." instead of running it (utils/tests/test_android_build_sh.py).
set -euo pipefail

stop_before_gn=0
if [[ "${1:-}" == --stop-before-gn ]]; then
  stop_before_gn=1
  shift
fi
if [[ $# -ne 1 ]]; then
  echo "usage: $0 [--stop-before-gn] WORKDIR" >&2
  exit 2
fi

_root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_main_repo="$_root_dir/ungoogled-chromium"
work="$(mkdir -p "$1" && cd "$1" && pwd)"
_src_dir="$work/src"
_download_cache="$work/download_cache"
dryrun="${TARK_ANDROID_DRYRUN:-0}"

log() { echo "tark: $*"; }
run() {
  echo "tark: run $*"
  if [[ "$dryrun" != 1 ]]; then
    "$@"
  fi
}

mkdir -p "$_src_dir" "$_download_cache"
# gclient writes state files into its working directory: work from WORKDIR.
cd "$work"

# --- prepare --- (android/prep_hash.py hashes this section and the inputs)
# A tree prepared from the same inputs (android/prep_hash.py) is reused:
# straight to gn and ninja. Otherwise the preparation comes in two layers.
# The base (steps 1 to 3a: Chromium with Android's dependencies, the
# toolchains, ungoogled-chromium's core patches) is kept as a copy in
# WORKDIR/src-base, stamped with prep_hash.py --base. Tark's layer (steps 3b
# to 5: Tark's series, domain and name substitution, Tark's steps) goes on
# top. When the base is unchanged, android/layers.py puts back the base
# wherever the last layer changed it, the layer is applied again, and each
# file that comes out as the last build had it keeps that build's time: out/
# is kept and ninja rebuilds only what changed. A different base wipes the
# tree, its copy and out/, and prepares everything again.
stamp="$work/prepared.stamp"
base_stamp="$work/base.stamp"
_base_dir="$work/src-base"
prep="$(python3 "$_root_dir/android/prep_hash.py" "$_root_dir")"
base="$(python3 "$_root_dir/android/prep_hash.py" --base "$_root_dir")"
if [[ -f "$stamp" && "$(cat "$stamp")" == "$prep" ]]; then
  log "prepared tree matches its inputs; skipping to gn"
else
  # A layer cut short must never pass for a prepared tree.
  rm -f "$stamp"
  if [[ -f "$base_stamp" && "$(cat "$base_stamp")" == "$base" && -d "$_base_dir" ]]; then
    log "base matches its inputs; putting back what Tark's last layer changed"
    run python3 "$_root_dir/android/layers.py" reset "$_base_dir" "$_src_dir" "$work/layers.json"
  else
    if [[ -n "$(ls -A "$_src_dir" 2>/dev/null)" || -e "$_base_dir" ]]; then
      run rm -rf "$_src_dir" "$_base_dir"
      mkdir -p "$_src_dir"
    fi
    rm -f "$base_stamp" "$work/layers.json"
    # 1. Chromium with Android's dependencies, from ungoogled's clone.py with
    #    android/gclient.android (a solution named "src").
    cp "$_root_dir/android/gclient.android" "$work/gclient"
    # clone.py needs two fixes, made in a copy of ungoogled's utils/ (clone.py
    # reads depot_tools.patch and gsutil.patch beside it, and
    # ../chromium_version.txt); the submodule is untouched:
    # - its -c path crashes on current Python (Path.replace(old, new) on the
    #   path copy() returns);
    # - it keeps .gclient in src/uc_staging with the absolute output path as the
    #   solution name, which current depot_tools rejects; .gclient goes beside
    #   src instead (WORKDIR), the standard layout.
    rm -rf "$work/uc" && mkdir -p "$work/uc"
    cp -R "$_main_repo/utils" "$work/uc/utils"
    cp "$_main_repo/chromium_version.txt" "$work/uc/"
    sed -i.orig \
      -e "s|copy(args.custom_config, ucstaging / '.gclient').replace('UC_OUT', str(args.output))|copy(args.custom_config, args.output.parent / '.gclient')|" \
      -e "s|environ\['GCLIENT_FILE'\] = str(ucstaging / '.gclient')|environ['GCLIENT_FILE'] = str(args.output.parent / '.gclient')|" \
      "$work/uc/utils/clone.py"
    rm -f "$work/uc/utils/clone.py.orig"
    # - ungoogled's depot_tools.patch makes gclient_gn_args_file absolute, which
    #   the pinned depot_tools rejects; with .gclient beside src the relative
    #   path is right, so that one hunk is dropped from the copy.
    python3 "$_root_dir/android/drop_gn_args_hunk.py" "$work/uc/utils/depot_tools.patch"
    if grep -q ".gclient').replace('UC_OUT'" "$work/uc/utils/clone.py" ||
       ! grep -q "environ\['GCLIENT_FILE'\] = str(args.output.parent / '.gclient')" "$work/uc/utils/clone.py"; then
      echo "tark: clone.py changed upstream; android/build.sh's fix no longer applies" >&2
      exit 1
    fi
    run python3 "$work/uc/utils/clone.py" -o "$_src_dir" -c "$work/gclient" -s amd64

    # 1b. The Android SDK, NDK, build-tools and R8. Chromium ships them as CIPD
    #     packages, which ungoogled's depot_tools patch skips (it avoids
    #     prebuilt binaries); Android cannot be built without them. A second sync
    #     with an unpatched depot_tools at the same commit fetches them. It runs
    #     on the build machine only; no -D, so nothing clone.py fetched is removed.
    dt_commit=dca727ba1f8fa8f1e3b12a815d065818bb61d395
    if [[ "$dryrun" != 1 ]]; then
      dt_commit=$(git -C "$_src_dir/uc_staging/depot_tools" rev-parse HEAD)
    fi
    if [[ ! -d "$work/depot_tools-stock/.git" ]]; then
      run git init -q "$work/depot_tools-stock"
      run git -C "$work/depot_tools-stock" remote add origin https://chromium.googlesource.com/chromium/tools/depot_tools
    fi
    run git -C "$work/depot_tools-stock" fetch -q --depth=1 origin "$dt_commit"
    run git -C "$work/depot_tools-stock" reset -q --hard FETCH_HEAD
    run env DEPOT_TOOLS_UPDATE=0 GCLIENT_FILE=.gclient PATH="$work/depot_tools-stock:$PATH" \
      "$work/depot_tools-stock/gclient" sync --nohooks --no-history --shallow -j 32
    if [[ "$dryrun" != 1 && ! -d "$_src_dir/third_party/android_sdk/public/platforms" ]]; then
      echo "tark: no Android SDK after the sync (third_party/android_sdk/public/platforms)" >&2
      exit 1
    fi

    # 2. No pruning on Android. ungoogled's prune_binaries.py serves the desktop
    #    lite tarball: its contingent paths delete chrome/android/,
    #    android_webview/, the JDK and other CIPD folders, and its list deletes
    #    third_party/r8/custom_d8.jar and custom_r8.jar — all of which an
    #    Android build needs. The Android toolchain is Google's prebuilt one, as
    #    in every Android build; nothing pruning would remove is compiled in.

    # 2b. Chromium's own clang and Rust, fetched by their update scripts before
    #     domain substitution (which rewrites googleapis.com inside them).
    run python3 "$_src_dir/tools/clang/scripts/update.py"
    run python3 "$_src_dir/tools/rust/update_rust.py"
    # The Debian sysroot the Linux host tools build against (gclient fetches it
    # only for checkout_linux, which an Android checkout does not set). Also
    # before domain substitution, which rewrites its download URL.
    run python3 "$_src_dir/build/linux/sysroot_scripts/install-sysroot.py" --arch=amd64

    # 3a. ungoogled-chromium's core patches, the last of the base. The base is
    #     kept (out/ is not there yet; cp -a keeps every file's time, which
    #     android/layers.py compares).
    run python3 "$_main_repo/utils/patches.py" apply "$_src_dir" "$_main_repo/patches"
    run cp -a "$_src_dir" "$_base_dir"
    echo "$base" > "$base_stamp"
    # --- end base ---
  fi

  # 3b. Tark's Android series.
  mkdir -p "$work/tark-patches"
  ln -sfn "$_root_dir/patches/tarka" "$work/tark-patches/tarka"
  ln -sfn "$_root_dir/android/patches" "$work/tark-patches/android"
  python3 "$_root_dir/android/series.py" "$_root_dir" "$work/tark-patches/series"
  run python3 "$_main_repo/utils/patches.py" apply "$_src_dir" "$work/tark-patches"

  # 4. Domain substitution with Tark's filtered list (the Chrome Web Store's
  #    files stay unsubstituted, as on the Mac), then the product name.
  run python3 "$_root_dir/utils/filter_substitution_list.py" "$_main_repo/domain_substitution.list" \
    "$_root_dir/utils/domain_substitution_skip.txt" "$work/domain_substitution.list"
  run python3 "$_main_repo/utils/domain_substitution.py" apply -r "$_main_repo/domain_regex.list" \
    -f "$work/domain_substitution.list" "$_src_dir"
  # Tark's layer is applied again on every preparation, so an earlier run's
  # name-substitution backup is stale (name_substitution.py refuses to
  # overwrite it).
  rm -f "$work/namesubs.tar"
  run python3 "$_root_dir/utils/name_substitution.py" --sub -t "$_src_dir" --backup-path "$work/namesubs.tar"

  # 5. Tark's steps: the mark, Inter for WebUI pages, uBlock Origin's sources
  #    (Tark's shared patches put its files into the resource paks on every
  #    platform; Android never loads them, having no extension system, and
  #    A2's engine-level blocker removes them), IndicXlit (D1).
  run python3 "$_root_dir/utils/install_branding.py" "$_root_dir/resources/branding/mark" "$_src_dir" \
    install.txt install-android.txt
  run mkdir -p "$_src_dir/ui/webui/resources/fonts"
  run cp "$_root_dir"/resources/fonts/inter-latin.woff2 "$_root_dir"/resources/fonts/inter-latin-ext.woff2 \
    "$_src_dir/ui/webui/resources/fonts/"
  run python3 "$_main_repo/utils/downloads.py" retrieve -i "$_root_dir/downloads-tark.ini" -c "$_download_cache"
  run python3 "$_main_repo/utils/downloads.py" unpack -i "$_root_dir/downloads-tark.ini" -c "$_download_cache" \
    --tar-path bsdtar "$_src_dir"
  run python3 "$_root_dir/utils/ublock_key.py" "$_src_dir/third_party/ublock/manifest.json" \
    "$_root_dir/resources/ublock/key.txt"
  # A2: adblock-rust and its new crates into Chromium's vendored crates, each
  # .crate checked against its pinned sha256 (android/adblock/crates.py).
  run python3 "$_root_dir/android/adblock/crates.py" "$_src_dir" --cache "$_download_cache/crates"
  echo "tark: run _install_xlit"
  if [[ "$dryrun" != 1 ]]; then
    export _root_dir _src_dir _main_repo _download_cache
    # shellcheck source=../utils/install_xlit.sh
    source "$_root_dir/utils/install_xlit.sh"
    _install_xlit
  fi
  # A3: the model and word lists are not in the APK; phones download them
  # (spec §5). One word-list file per language, and every file's size and
  # sha256, compiled in, for the download to check against.
  run python3 "$_root_dir/android/xlit/files.py" build "$_root_dir/resources/xlit/words" \
    "$_root_dir/resources/xlit/english-common.txt.xz" "$_src_dir/third_party/indicxlit/xlit-model.bin" \
    "$_src_dir/third_party/indicxlit/android"
  run mkdir -p "$_src_dir/chrome/browser/tark_xlit"
  run python3 "$_root_dir/android/xlit/files.py" header "$_src_dir/third_party/indicxlit/android/files.json" \
    "$_src_dir/chrome/browser/tark_xlit/xlit_files.inc"
  # Two of them for tark_xlit_unittests (android_files_unittest.cc).
  run mkdir -p "$_src_dir/components/tark_xlit/test/data/android"
  run cp "$_src_dir/third_party/indicxlit/android/xlit-words-hi.bin" \
    "$_src_dir/third_party/indicxlit/android/xlit-words-ta.bin" "$_src_dir/components/tark_xlit/test/data/android/"
  run python3 "$_root_dir/android/layers.py" settle "$_base_dir" "$_src_dir" "$work/layers.json"
  log "every patch applied and Tark's steps done"
  echo "$prep" > "$stamp"
fi
# --- end prepare ---

# A2: the newest signed list bundle goes into the APK as an asset, checked
# against Tark's list-signing key first (android/adblock/bundle.py verify).
# TARK_LISTS_DIR (latest.json beside its zip) stands in for gettarka.com.
lists_base="https://gettarka.com/lists/android/v1"
rm -rf "$work/lists" && mkdir -p "$work/lists"
if [[ -n "${TARK_LISTS_DIR:-}" ]]; then
  run cp "$TARK_LISTS_DIR"/latest.json "$work/lists/latest.json"
else
  run curl -fsSL -o "$work/lists/latest.json" "$lists_base/latest.json"
fi
if [[ "$dryrun" != 1 ]]; then
  lists_file=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["file"])' "$work/lists/latest.json")
  [[ $lists_file =~ ^lists-[0-9]{8}\.zip$ ]] || { echo "bad list bundle name '$lists_file'" >&2; exit 1; }
else
  lists_file=lists-00000000.zip
fi
if [[ -n "${TARK_LISTS_DIR:-}" ]]; then
  run cp "$TARK_LISTS_DIR/$lists_file" "$work/lists/$lists_file"
else
  run curl -fsSL -o "$work/lists/$lists_file" "$lists_base/$lists_file"
fi
run python3 "$_root_dir/android/adblock/bundle.py" verify "$work/lists/$lists_file" "$work/lists/latest.json" \
  --pubkey "$_root_dir/android/adblock/lists_pubkey.txt"
run cp "$work/lists/$lists_file" "$_src_dir/chrome/browser/tark_adblock/lists.zip"

if (( stop_before_gn )); then
  log "stopping before gn gen (--stop-before-gn)"
  exit 3
fi

# 6. gn and ninja, with the clang and Rust fetched while preparing; gn is
#    bootstrapped from source as on the Mac.
# Live captions: the model files the APK pins (android/captions/files.json,
# built on the Mac by models.py; the files themselves are on gettarka.com).
run python3 "$_root_dir/android/captions/models.py" header "$_root_dir/android/captions/files.json" \
  "$_src_dir/chrome/browser/tark_captions_android/model_files.inc"
# Live captions: ONNX Runtime's headers and its arm64 .so, pinned
# (android/captions/ort.sh).
run bash "$_root_dir/android/captions/ort.sh" "$_src_dir/third_party/tark_onnxruntime"
mkdir -p "$_src_dir/out/Default"
# Chromium's own clang (fetched while preparing) builds gn and everything else.
export PATH="$_src_dir/third_party/llvm-build/Release+Asserts/bin:$PATH"
export CC=clang CXX=clang++ AR=llvm-ar
cat "$_main_repo/flags.gn" "$_root_dir/android/args.gn" > "$_src_dir/out/Default/args.gn"
# A5: Tark's own version name and code (android/release/version.py), which
# Play and the direct APK's update check compare.
read -r _version_name _version_code < <(python3 "$_root_dir/android/release/version.py" "$_root_dir")
printf 'android_override_version_name = "%s"\nandroid_override_version_code = "%s"\n' \
  "$_version_name" "$_version_code" >> "$_src_dir/out/Default/args.gn"
run python3 "$_src_dir/tools/gn/bootstrap/bootstrap.py" -o "$_src_dir/out/Default/gn" --skip-generate-buildfiles
# Scripts run with the machine's python3, as in Chromium's source tarball (a
# git checkout's .gn names a bundled Python the Android tree does not have).
run sed -i "s|^script_executable = .*|script_executable = \"python3\"|" "$_src_dir/.gn"
run "$_src_dir/out/Default/gn" gen "$_src_dir/out/Default" --root="$_src_dir" --fail-on-unused-args
# Live captions' test binaries, before the APK (a build whose APK does not
# compile still reports them): each runs even when an earlier one failed;
# the build fails after the APK if any did.
test_failures=0
run_test() {
  echo "tark: run $*"
  if [[ "$dryrun" != 1 ]] && ! "$@"; then
    echo "tark: FAILED $*"
    test_failures=$((test_failures + 1))
  fi
}
run ninja -C "$_src_dir/out/Default" components/tark_captions:host_unittests
run_test env TARK_CAPTIONS_TESTDATA="$_root_dir/resources/captions/testdata" \
  "$_src_dir/out/Default/clang_x64/tark_captions_engine_unittests"
run ninja -C "$_src_dir/out/Default" chrome/browser/tark_captions_android:host_unittests
run_test "$_src_dir/out/Default/clang_x64/tark_captions_android_unittests"
run ninja -C "$_src_dir/out/Default" chrome/services/tark_captions:host_unittests
run_test "$_src_dir/out/Default/clang_x64/tark_captions_session_unittests"
# -k 0: one run reports every failing step, not only the first.
run ninja -k 0 -C "$_src_dir/out/Default" chrome_public_apk
# A5: the app bundle Play takes, from the same build (debug-signed here; the
# release key signs it on the Mac, android/release/sign.py).
run ninja -k 0 -C "$_src_dir/out/Default" chrome_public_bundle
# A2: the ad blocker's unit tests (list bundle, signature, update schedule),
# built for this machine and run here.
run ninja -C "$_src_dir/out/Default" chrome/browser/tark_adblock:host_unittests
run "$_src_dir/out/Default/clang_x64/tark_adblock_unittests"
run ninja -C "$_src_dir/out/Default" components/tark_xlit:host_unittests
run env CR_SOURCE_ROOT="$_src_dir" "$_src_dir/out/Default/clang_x64/tark_xlit_unittests"
run ninja -C "$_src_dir/out/Default" chrome/browser/tark_xlit:host_unittests
run "$_src_dir/out/Default/clang_x64/tark_xlit_files_unittests"
run ninja -C "$_src_dir/out/Default" chrome/browser/tark_update:host_unittests
run "$_src_dir/out/Default/clang_x64/tark_update_unittests"
# Live captions: the engine's own tests (front end, speech model, segmenter,
# VAD, ONNX Runtime loader), built for this machine.
(( test_failures == 0 )) || { log "$test_failures test binaries failed"; exit 1; }
log "built $_src_dir/out/Default/apks/ChromePublic.apk"

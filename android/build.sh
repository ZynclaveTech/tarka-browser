#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   android/build.sh [--stop-before-gn] WORKDIR
#
# Builds Tark for Android (A1) on a Linux x86-64 machine, the steps of the
# Mac's build.sh for an Android tree: clone Chromium with Android's
# dependencies (ungoogled's clone.py and android/gclient.android), prune,
# apply ungoogled-chromium's core patches then Tark's Android series, domain
# and name substitution, the mark, Inter, IndicXlit, then gn and ninja.
# The APK lands in WORKDIR/src/out/Default/apks/ChromePublic.apk.
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

# 2. Prune binaries, as every ungoogled-chromium build does.
run python3 "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list"

# 3. ungoogled-chromium's core patches, then Tark's Android series.
mkdir -p "$work/tark-patches"
ln -sfn "$_root_dir/patches/tarka" "$work/tark-patches/tarka"
python3 "$_root_dir/android/series.py" "$_root_dir" "$work/tark-patches/series"
run python3 "$_main_repo/utils/patches.py" apply "$_src_dir" "$_main_repo/patches" "$work/tark-patches"

# 4. Domain substitution with Tark's filtered list (the Chrome Web Store's
#    files stay unsubstituted, as on the Mac), then the product name.
run python3 "$_root_dir/utils/filter_substitution_list.py" "$_main_repo/domain_substitution.list" \
  "$_root_dir/utils/domain_substitution_skip.txt" "$work/domain_substitution.list"
run python3 "$_main_repo/utils/domain_substitution.py" apply -r "$_main_repo/domain_regex.list" \
  -f "$work/domain_substitution.list" "$_src_dir"
run python3 "$_root_dir/utils/name_substitution.py" --sub -t "$_src_dir" --backup-path "$work/namesubs.tar"

# 5. Tark's steps: the mark, Inter for WebUI pages, IndicXlit (D1). No
#    uBlock Origin: Chromium on Android runs no extensions (A2 blocks ads in
#    the engine instead).
run python3 "$_root_dir/utils/install_branding.py" "$_root_dir/resources/branding/mark" "$_src_dir"
run mkdir -p "$_src_dir/ui/webui/resources/fonts"
run cp "$_root_dir"/resources/fonts/inter-latin.woff2 "$_root_dir"/resources/fonts/inter-latin-ext.woff2 \
  "$_src_dir/ui/webui/resources/fonts/"
echo "tark: run _install_xlit"
if [[ "$dryrun" != 1 ]]; then
  export _root_dir _src_dir _main_repo _download_cache
  # shellcheck source=../utils/install_xlit.sh
  source "$_root_dir/utils/install_xlit.sh"
  _install_xlit
fi
log "every patch applied and Tark's steps done"

if (( stop_before_gn )); then
  log "stopping before gn gen (--stop-before-gn)"
  exit 3
fi

# 6. gn and ninja: Chromium's own clang and Rust (fetched by their update
#    scripts on the build machine), gn bootstrapped from source as on the Mac.
mkdir -p "$_src_dir/out/Default"
cat "$_main_repo/flags.gn" "$_root_dir/android/args.gn" > "$_src_dir/out/Default/args.gn"
run python3 "$_src_dir/tools/clang/scripts/update.py"
run python3 "$_src_dir/tools/rust/update_rust.py"
run python3 "$_src_dir/tools/gn/bootstrap/bootstrap.py" -o "$_src_dir/out/Default/gn" --skip-generate-buildfiles
run "$_src_dir/out/Default/gn" gen "$_src_dir/out/Default" --root="$_src_dir" --fail-on-unused-args
run ninja -C "$_src_dir/out/Default" chrome_public_apk
log "built $_src_dir/out/Default/apks/ChromePublic.apk"

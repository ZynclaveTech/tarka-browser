#!/usr/bin/env bash
# Tarka development loop: an incremental edit-build-run cycle on top of the
# ungoogled-chromium-macos tooling. The upstream build.sh re-downloads and
# rebuilds from scratch on every run; this script keeps build/src around.
#
#   ./dev.sh setup   fetch, prune, patch, substitute, gn gen (once)
#   ./dev.sh setup --continue   resume after fixing a patch that failed to
#                    apply: skips fetch, prune and quilt push
#   ./dev.sh build   ninja chrome, incremental, logged under build/logs/
#   ./dev.sh run     launch the built app with its own profile directory
#   ./dev.sh reset   delete build/src, keep build/download_cache
#
# See docs/building.md and docs/patching.md.

set -euo pipefail

# TARKA_ROOT overrides the repo root; the tests point it at a fake tree.
_root_dir="${TARKA_ROOT:-$(dirname "$(greadlink -f "${BASH_SOURCE[0]}")")}"
_src_dir="$_root_dir/build/src"
_out_dir="$_src_dir/out/Default"
_main_repo="$_root_dir/ungoogled-chromium"
_download_cache="$_root_dir/build/download_cache"
_logs_dir="$_root_dir/build/logs"
_arch=arm64

# depot_tools needs Python 3.13 or earlier; the system has 3.14.
export PATH="/opt/homebrew/opt/python@3.13/libexec/bin:$PATH"

_quilt() {
  # Same settings as devutils/set_quilt_vars.sh, without relying on an alias.
  QUILT_PATCHES="$_root_dir/patches" QUILT_SERIES=series.merged \
  QUILT_PATCH_OPTS="--unified --reject-format=unified" \
  QUILT_REFRESH_ARGS="-p ab --no-timestamps --no-index" \
  QUILT_DIFF_ARGS="-p ab --no-timestamps --no-index" \
    quilt --quiltrc - "$@"
}

_write_gn_args() {
  mkdir -p "$_out_dir"
  {
    cat "$_main_repo/flags.gn" "$_root_dir/flags.macos.gn" "$_root_dir/flags.dev.gn"
    echo 'target_cpu = "arm64"'
  } > "$_out_dir/args.gn"
}

_fix_esbuild() {
  # Mirrors build.sh: Chromium's devtools build wants a node module whose
  # version matches the Homebrew esbuild binary.
  local version module
  version="$(/opt/homebrew/bin/esbuild --version)"
  module="$_root_dir/build/esbuild-node/node_modules/esbuild"
  if [[ ! -f "$module/package.json" ]] || \
     [[ "$(node -p 'require(process.argv[1]).version' "$module/package.json")" != "$version" ]]; then
    npm install --prefix "$_root_dir/build/esbuild-node" --no-save --package-lock=false \
      --no-bin-links --ignore-scripts --omit=optional --no-audit --no-fund "esbuild@$version"
  fi
  rm -rf "$_src_dir/third_party/devtools-frontend/src/node_modules/esbuild"
  ln -s "$module" "$_src_dir/third_party/devtools-frontend/src/node_modules/esbuild"
}

cmd_setup() {
  local resume=false
  [[ "${1:-}" == "--continue" ]] && resume=true
  if [[ -d "$_out_dir" ]]; then
    echo "$_out_dir already exists; run ./dev.sh reset for a clean setup" >&2
    return 0
  fi
  if ! $resume && [[ -e "$_root_dir/patches/series.merged" ]]; then
    cat >&2 <<MSG
patches/series.merged exists: a previous setup stopped part-way (usually a
patch that failed to apply). Either
  - fix it: cd build/src; quilt push -f; edit; quilt refresh; cd ../..;
    then ./dev.sh setup --continue
  - or start over: ./dev.sh reset && ./dev.sh setup
MSG
    return 2
  fi
  mkdir -p "$_download_cache" "$_logs_dir"

  if ! $resume; then
    "$_root_dir/retrieve_and_unpack_resource.py" -d -g "$_arch"
    python3 "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list"

    # Apply ungoogled-chromium's patches, then ours, through quilt so that
    # build/src/.pc exists and new patches can be made with quilt new/refresh.
    "$_root_dir/devutils/update_patches.sh" merge
    (cd "$_src_dir" && _quilt push -a)
  else
    (cd "$_src_dir" && _quilt push -a)   # applies whatever is still unapplied
  fi

  # Tark leaves the Chrome Web Store's files unsubstituted (utils/domain_substitution_skip.txt).
  python3 "$_root_dir/utils/filter_substitution_list.py" "$_main_repo/domain_substitution.list" \
    "$_root_dir/utils/domain_substitution_skip.txt" "$_root_dir/build/domain_substitution.list"
  python3 "$_main_repo/utils/domain_substitution.py" apply \
    -r "$_main_repo/domain_regex.list" -f "$_root_dir/build/domain_substitution.list" "$_src_dir"

  # Tarka: product name in UI strings, and the app icon (binary, so not a patch).
  python3 "$_root_dir/utils/name_substitution.py" --sub -t "$_src_dir" --backup-path "$_root_dir/build/namesubs.tar"
  cp "$_root_dir/resources/branding/app.icns" "$_src_dir/chrome/app/theme/chromium/mac/app.icns"
  # Inter for WebUI pages (M3 Task 8), served as chrome://resources/fonts/.
  mkdir -p "$_src_dir/ui/webui/resources/fonts"
  cp "$_root_dir"/resources/fonts/inter-latin*.woff2 "$_src_dir/ui/webui/resources/fonts/"

  _write_gn_args
  mkdir -p "$_src_dir/third_party/llvm-build/Release+Asserts" "$_src_dir/third_party/rust-toolchain/bin"
  "$_root_dir/retrieve_and_unpack_resource.py" -p "$_arch"

  # Tark: uBlock Origin's sources, and the key that fixes its extension id.
  python3 "$_main_repo/utils/downloads.py" retrieve -i "$_root_dir/downloads-tark.ini" -c "$_download_cache"
  python3 "$_main_repo/utils/downloads.py" unpack -i "$_root_dir/downloads-tark.ini" -c "$_download_cache" "$_src_dir"
  python3 "$_root_dir/utils/ublock_key.py" "$_src_dir/third_party/ublock/manifest.json" "$_root_dir/resources/ublock/key.txt"

  _fix_esbuild
  cd "$_src_dir"
  ./tools/gn/bootstrap/bootstrap.py -o out/Default/gn --skip-generate-buildfiles
  ./tools/rust/build_bindgen.py --skip-test
  ./out/Default/gn gen out/Default --fail-on-unused-args
}

cmd_build() {
  mkdir -p "$_logs_dir"
  local log
  log="$_logs_dir/build-$(date +%Y%m%d-%H%M).log"
  echo "log: $log"
  cd "$_src_dir"
  ninja -C out/Default -j "${TARKA_JOBS:-8}" chrome "$@" 2>&1 | tee "$log"
}

cmd_run() {
  local app
  app="$(find "$_out_dir" -maxdepth 1 -name '*.app' -not -name '*Helper*' | head -1)"
  if [[ -z "$app" ]]; then
    echo "no app bundle in $_out_dir; run ./dev.sh build first" >&2
    return 1
  fi
  # --use-mock-keychain: Chromium unlocks its "Safe Storage" keychain key
  # before the cookie store opens, and every rebuild changes the ad-hoc
  # signature, so macOS would ask for keychain access on every launch and
  # block all network loads until answered. Release builds with a Developer
  # ID ask once and keep the real keychain.
  open -n "$app" --args --user-data-dir="$_root_dir/build/profile" --use-mock-keychain "$@"
}

cmd_reset() {
  "$_root_dir/devutils/update_patches.sh" unmerge 2>/dev/null || true
  rm -rf "$_src_dir" "$_root_dir/build/namesubs.tar"
  echo "removed build/src; kept build/download_cache"
}

case "${1:-}" in
  setup|build|run|reset) cmd="cmd_$1"; shift; "$cmd" "$@" ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

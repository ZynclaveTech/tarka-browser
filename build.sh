#!/usr/bin/env bash

set -eux

# Build script for local macOS environment

# Some path variables
_root_dir="$(dirname "$(greadlink -f "$0")")"
_download_cache="$_root_dir/build/download_cache"
_src_dir="$_root_dir/build/src"
_main_repo="$_root_dir/ungoogled-chromium"
source "$_root_dir/utils/install_xlit.sh"
source "$_root_dir/utils/install_captions_credits.sh"

# Clone to get the Chromium Source
clone=true
_mode=release
while getopts 'dm:' OPTION; do
  case "$OPTION" in
    d)
      clone=false
      ;;
    m)
      _mode="$OPTARG"
      ;;
  esac
done

shift "$(($OPTIND -1))"

_arch=${1:-arm64}

# Add local clang and build tools to PATH
# export PATH="$PATH:$_src_dir/third_party/llvm-build/Release+Asserts/bin"

# A development tree (dev.sh setup) must be reset first; see the check.
"$_root_dir/devutils/check_clean_tree.sh"

rm -rf "$_src_dir/out" || true
mkdir -p "$_download_cache"

if $clone; then
  "$_root_dir/retrieve_and_unpack_resource.py" -g $_arch
else
  "$_root_dir/retrieve_and_unpack_resource.py" -d -g $_arch
fi

mkdir -p "$_src_dir/out/Default"

# Apply patches and substitutions
python3 "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list"
# Toolchains and TypeScript before the patches: fix-typescript-lib-dom.patch
# changes a file from the TypeScript download.
mkdir -p "$_src_dir/third_party/llvm-build/Release+Asserts"
mkdir -p "$_src_dir/third_party/rust-toolchain/bin"

"$_root_dir/retrieve_and_unpack_resource.py" -p $_arch

python3 "$_main_repo/utils/patches.py" apply "$_src_dir" "$_main_repo/patches" "$_root_dir/patches"

# Tark leaves the Chrome Web Store's files unsubstituted (utils/domain_substitution_skip.txt).
python3 "$_root_dir/utils/filter_substitution_list.py" "$_main_repo/domain_substitution.list" "$_root_dir/utils/domain_substitution_skip.txt" "$_root_dir/build/domain_substitution.list"
python3 "$_main_repo/utils/domain_substitution.py" apply -r "$_main_repo/domain_regex.list" -f "$_root_dir/build/domain_substitution.list" "$_src_dir"
# Tarka: product name in UI strings, and the app icon (binary, so not a patch).
python3 "$_root_dir/utils/name_substitution.py" --sub -t "$_src_dir" --backup-path "$_root_dir/build/namesubs.tar"
cp "$_root_dir/resources/branding/app.icns" "$_src_dir/chrome/app/theme/chromium/mac/app.icns"
# Certificate trust data: CT log list, Chrome Root Store, CRLSet (resources/trust).
python3 "$_root_dir/utils/trust_data.py" install "$_src_dir" --domain-regex "$_main_repo/domain_regex.list"
# The three-dot mark over every Chromium logo file (M3b, spec 6.3).
python3 "$_root_dir/utils/install_branding.py" "$_root_dir/resources/branding/mark" "$_src_dir"
# Inter for WebUI pages (M3 Task 8), served as chrome://resources/fonts/.
mkdir -p "$_src_dir/ui/webui/resources/fonts"
cp "$_root_dir"/resources/fonts/inter-latin*.woff2 "$_src_dir/ui/webui/resources/fonts/"
# Set build flags
cat "$_main_repo/flags.gn" "$_root_dir/flags.macos.gn" > "$_src_dir/out/Default/args.gn"

# Set target_cpu to the corresponding architecture
if [[ $_arch == "arm64" ]]; then
  echo 'target_cpu = "arm64"' >> "$_src_dir/out/Default/args.gn"
else
  echo 'target_cpu = "x64"' >> "$_src_dir/out/Default/args.gn"
fi

# Development mode: static build, no LTO/PGO, no symbols. See flags.dev.gn.
if [[ $_mode == "dev" ]]; then
  cat "$_root_dir/flags.dev.gn" >> "$_src_dir/out/Default/args.gn"
fi

# The PGO profile is only fetched by the clone path (clone.py -p); a tarball
# build (-d) has none, and flags.macos.gn's chrome_pgo_phase=2 would stop gn.
if ! $clone; then
  echo 'chrome_pgo_phase=0' >> "$_src_dir/out/Default/args.gn"
fi

# Tark: Sparkle 2, the updater (M5); installed into the app when it is signed.
python3 "$_main_repo/utils/downloads.py" retrieve -i "$_root_dir/downloads-sparkle.ini" -c "$_download_cache"
python3 "$_main_repo/utils/downloads.py" unpack -i "$_root_dir/downloads-sparkle.ini" -c "$_download_cache" "$_src_dir"
# Tark: ONNX Runtime for live captions (D4); installed into the app when it is signed.
python3 "$_main_repo/utils/downloads.py" retrieve -i "$_root_dir/downloads-onnxruntime.ini" -c "$_download_cache"
python3 "$_main_repo/utils/downloads.py" unpack -i "$_root_dir/downloads-onnxruntime.ini" -c "$_download_cache" "$_src_dir"
_install_captions_credits

# Tark: IndicXlit weights and word lists for the address bar (D1).
_install_xlit

# Tark: the ad blocker. adblock-rust's crates (pinned sha256) and its
# built-in list bundle, checked against Tark's list-signing key
# (utils/adblock_lists.py; TARK_LISTS_DIR stands in for gettarka.com).
python3 "$_root_dir/android/adblock/crates.py" "$_src_dir" --cache "$_download_cache/crates"
python3 "$_root_dir/utils/adblock_lists.py" "$_src_dir/chrome/browser/tark_adblock/lists.zip" \
  ${TARK_LISTS_DIR:+--lists-dir "$TARK_LISTS_DIR"}

cd "$_src_dir"

# Fix ESBuild
_esbuild_version="$(/opt/homebrew/bin/esbuild --version)"
_esbuild_module="$_root_dir/build/esbuild-node/node_modules/esbuild"
if [[ ! -f "$_esbuild_module/package.json" ]] || \
    [[ "$(node -p 'require(process.argv[1]).version' "$_esbuild_module/package.json")" != "$_esbuild_version" ]]; then
  npm install --prefix "$_root_dir/build/esbuild-node" --no-save --package-lock=false --no-bin-links --ignore-scripts --omit=optional --no-audit --no-fund "esbuild@$_esbuild_version"
fi
rm -rf third_party/devtools-frontend/src/node_modules/esbuild
ln -s "$_esbuild_module" third_party/devtools-frontend/src/node_modules/esbuild

./tools/gn/bootstrap/bootstrap.py -o out/Default/gn --skip-generate-buildfiles
./tools/rust/build_bindgen.py --skip-test

./out/Default/gn gen out/Default --fail-on-unused-args

ninja -C out/Default chrome chromedriver

if [[ $_mode == "release" ]]; then
  CHROMIUM_SRC_DIR="$_src_dir" "$_root_dir/sign_and_package_app.sh"
fi

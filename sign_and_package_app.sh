#!/usr/bin/env bash

set -euo pipefail

_root_dir="$(dirname "$(greadlink -f "$0")")"
_src_dir="${CHROMIUM_SRC_DIR:-$_root_dir/build/src}"
# Product name as set in chrome/app/theme/chromium/BRANDING by patches/tarka/core/branding.patch.
_product_name="${TARKA_PRODUCT_NAME:-Tark}"
_bundle_id="${TARKA_BUNDLE_ID:-com.gettarka.Tarka}"
_app="$_src_dir/out/Default/$_product_name.app"
_framework="$_app/Contents/Frameworks/$_product_name Framework.framework"
_helpers="$_framework/Helpers"
_libraries="$_framework/Libraries"
_pkg_dmg="$_src_dir/chrome/installer/mac/pkg-dmg"

_ad_hoc="${MACOS_AD_HOC_SIGNING:-0}"
_target_dmg="${1:-}"
if [[ -z "$_target_dmg" ]]; then
  _chromium_version="$(cat "$_root_dir/ungoogled-chromium/chromium_version.txt")"
  _ungoogled_revision="$(cat "$_root_dir/ungoogled-chromium/revision.txt")"
  _package_revision="$(cat "$_root_dir/revision.txt")"
  _target_dmg="$_root_dir/build/${_product_name}_${_chromium_version}-${_ungoogled_revision}.${_package_revision}_macos.dmg"
fi

sign() {
  if (( _ad_hoc )); then
    # Library validation compares Team IDs, and an ad-hoc signature has
    # none, so on macOS 26 the app cannot load its own framework with it on;
    # the hardened runtime turns library validation on by itself. Both mean
    # nothing without a Developer ID, and an ad-hoc build cannot be notarized
    # anyway, so ad-hoc signing leaves them out. Release signing keeps them.
    local args=() a
    for a in "$@"; do
      a="${a//library,/}"; a="${a//,library/}"
      a="${a//runtime,/}"; a="${a//,runtime/}"
      args+=("$a")
    done
    codesign --sign - --force "${args[@]}"
  else
    codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp "$@"
  fi
}

error() {
  printf '::error::%s\n' "$*" >&2
}

warning() {
  printf '::warning::%s\n' "$*" >&2
}

# Fix issue where macOS requests permission for incoming network connections
# See https://github.com/ungoogled-software/ungoogled-chromium-macos/issues/17
xattr -cs "$_app"

# Sign the binary
sign --identifier chrome_crashpad_handler --options=restrict,library,runtime,kill "$_helpers/chrome_crashpad_handler"
sign --identifier $_bundle_id.helper --options restrict,library,runtime,kill "$_helpers/$_product_name Helper.app"
sign --identifier $_bundle_id.helper.renderer --options restrict,kill,runtime --entitlements "$_root_dir/entitlements/helper-renderer-entitlements.plist" "$_helpers/$_product_name Helper (Renderer).app"
sign --identifier $_bundle_id.helper --options restrict,kill,runtime --entitlements "$_root_dir/entitlements/helper-gpu-entitlements.plist" "$_helpers/$_product_name Helper (GPU).app"
sign --identifier $_bundle_id.framework.AlertNotificationService --options restrict,library,runtime,kill "$_helpers/$_product_name Helper (Alerts).app"
if [[ -d "$_helpers/$_product_name Helper (Aperitif).app" ]]; then
  sign --identifier $_bundle_id.helper --options restrict,library,runtime,kill "$_helpers/$_product_name Helper (Aperitif).app"
  sign --identifier $_bundle_id.helper.renderer --options restrict,kill,runtime --entitlements "$_root_dir/entitlements/helper-renderer-entitlements.plist" "$_helpers/$_product_name Helper (Aperitif Renderer).app"
  sign --identifier $_bundle_id.helper --options restrict,kill,runtime --entitlements "$_root_dir/entitlements/helper-gpu-entitlements.plist" "$_helpers/$_product_name Helper (Aperitif GPU).app"
  sign --identifier $_bundle_id.framework.AlertNotificationService --options restrict,library,runtime,kill "$_helpers/$_product_name Helper (Aperitif Alerts).app"
fi
sign --identifier app_mode_loader --options restrict,library,runtime,kill "$_helpers/app_mode_loader"
sign --identifier web_app_shortcut_copier --options restrict,library,runtime,kill "$_helpers/web_app_shortcut_copier"

# The dylibs bundled by Chromium vary by release. Sign the files that are
# actually present instead of maintaining a version-dependent hard-coded list.
for _dylib in "$_libraries"/*.dylib; do
  [[ -e "$_dylib" ]] || continue
  _dylib_name="$(basename "$_dylib" .dylib)"
  sign --identifier "$_dylib_name" "$_dylib"
done

sign --identifier "$_bundle_id.framework" "$_framework"
if (( _ad_hoc )); then
  sign --identifier "$_bundle_id" --options restrict,library,runtime,kill --entitlements "$_root_dir/entitlements/app-entitlements.plist" "$_app"
else
  sign --identifier "$_bundle_id" --options restrict,library,runtime,kill --entitlements "$_root_dir/entitlements/app-entitlements.plist" --requirements "=designated => identifier \"$_bundle_id\" and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] /* exists */ and certificate leaf[field.1.2.840.113635.100.6.1.13] /* exists */" "$_app"
fi

# Verify the binary signature
verify_dylib() {
  local dylib="$1"
  local signature_info

  codesign --verify --strict --verbose=4 "$dylib"

  if (( _ad_hoc )); then
    return
  fi

  signature_info="$(codesign -dvvv "$dylib" 2>&1)"
  printf '%s\n' "$signature_info"

  if ! grep -q '^Authority=Developer ID Application:' <<< "$signature_info"; then
    error "${dylib} is not signed with a Developer ID Application certificate"
    return 1
  fi

  if ! grep -q '^Timestamp=' <<< "$signature_info"; then
    error "${dylib} does not have a secure signing timestamp"
    return 1
  fi
}

# Check all framework dylibs to catch signing omissions in future releases.
for _framework_dylib in "$_libraries"/*.dylib; do
  verify_dylib "$_framework_dylib"
done

codesign --verify --deep --strict --verbose=4 "$_app"

notarize_app() {
  local archive="$TMPDIR/notarize.zip"
  local result="$TMPDIR/notary-result.json"
  local log="$TMPDIR/notary-log.json"
  local status submission_id
  local submit_exit=0
  local credentials=(
    --apple-id "$PROD_MACOS_NOTARIZATION_APPLE_ID"
    --team-id "$PROD_MACOS_NOTARIZATION_TEAM_ID"
    --password "$PROD_MACOS_NOTARIZATION_PWD"
  )

  ditto -c -k --keepParent "$_app" "$archive"

  xcrun notarytool submit --wait --output-format json "${credentials[@]}" "$archive" \
    > "$result" || submit_exit=$?

  cat "$result"

  status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status", ""))' "$result" 2>/dev/null)" || status=""
  submission_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("id", ""))' "$result" 2>/dev/null)" || submission_id=""

  if [[ -n "$submission_id" ]]; then
    if xcrun notarytool log "${credentials[@]}" "$submission_id" > "$log"; then
      cat "$log"
    else
      warning "Could not retrieve Apple's notarization log for submission $submission_id"
      [[ ! -s "$log" ]] || cat "$log" || true
    fi
  fi

  if [[ "$status" != "Accepted" ]]; then
    if [[ -n "$status" ]]; then
      error "Apple notarization failed with status: $status"
    elif (( submit_exit != 0 )); then
      error "notarytool submit failed with exit status $submit_exit"
    else
      error "Apple notarization returned no status"
    fi
    return 1
  fi

  if (( submit_exit != 0 )); then
    error "notarytool submit exited with status $submit_exit despite reporting Accepted"
    return "$submit_exit"
  fi

  if [[ -z "$submission_id" ]]; then
    error "Apple notarization returned Accepted without a submission ID"
    return 1
  fi

  xcrun stapler staple "$_app"
  xcrun stapler validate "$_app"
}

if (( _ad_hoc )); then
  printf 'Ad-hoc signing enabled; skipping notarization and stapling.\n'
else
  notarize_app
fi

# Package the app
"$_pkg_dmg" \
  --sourcefile --source "$_app" \
  --target "$_target_dmg" \
  --volname "$_product_name" --symlink /Applications:/Applications \
  --format UDBZ --verbosity 2

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

_ad_hoc="${MACOS_AD_HOC_SIGNING:-0}"
# S1: development signing for the author's own Mac — an Apple Development
# certificate (MACOS_CERTIFICATE_NAME) and a development provisioning
# profile (TARKA_PROVISIONING_PROFILE) that names this Mac. Touch ID passkeys
# need it; the result runs only on Macs in the profile. No notarization.
_dev="${MACOS_DEV_SIGNING:-0}"
_target_dmg="${1:-}"
if [[ -z "$_target_dmg" ]]; then
  _chromium_version="$(cat "$_root_dir/ungoogled-chromium/chromium_version.txt")"
  _ungoogled_revision="$(cat "$_root_dir/ungoogled-chromium/revision.txt")"
  _package_revision="$(cat "$_root_dir/revision.txt")"
  _target_dmg="$_root_dir/build/${_product_name}_${_chromium_version}-${_ungoogled_revision}.${_package_revision}_macos.dmg"
fi

# A release for other people must be an official build: non-official builds
# keep Chromium's DCHECKs on, so an internal check that is harmless in an
# official build kills the tab ("Aw, Snap!", error code 6). Revisions 1 and 2
# shipped that way. Ad-hoc and development signing stay allowed for testing.
if (( ! _ad_hoc && ! _dev )); then
  _official="$(grep -E '^[[:space:]]*is_official_build[[:space:]]*=' "$_src_dir/out/Default/args.gn" | tail -1 | tr -d ' ')"
  if [[ "$_official" != "is_official_build=true" ]]; then
    printf '::error::refusing to sign a non-official build for release (%s in out/Default/args.gn)\n' "${_official:-no is_official_build}" >&2
    exit 1
  fi
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
  elif (( _dev )); then
    codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp=none "$@"
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

# Tark (M5): Sparkle 2 for updates from gettarka.com, with the update keys and
# a CFBundleVersion that carries Tark's revision. Signed below, before the app.
_sparkle_src="${TARKA_SPARKLE_FRAMEWORK:-$_src_dir/third_party/sparkle/Sparkle.framework}"
_sparkle="$_app/Contents/Frameworks/Sparkle.framework"
if [[ -d "$_sparkle_src" ]]; then
  "$_root_dir/utils/install_sparkle.sh" "$_app" "$_sparkle_src" "$_src_dir" "${TARKA_REVISION:-$(cat "$_root_dir/revision.txt")}"
else
  warning "No Sparkle.framework at $_sparkle_src: this build has no updater"
  rm -rf "$_sparkle"
fi

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
# Sparkle inside-out, as its documentation orders it: the helpers, then the
# framework. Its own bundle identifiers are kept.
if [[ -d "$_sparkle" ]]; then
  sign --options runtime "$_sparkle/Versions/B/Autoupdate"
  sign --options runtime "$_sparkle/Versions/B/Updater.app"
  sign --options runtime "$_sparkle"
fi
if (( _dev )); then
  _profile="${TARKA_PROVISIONING_PROFILE:?set TARKA_PROVISIONING_PROFILE to the development profile}"
  _dev_entitlements="$(mktemp -t tark-entitlements).plist"
  python3 -I "$_root_dir/utils/dev_entitlements.py" "$_root_dir/entitlements/app-entitlements.plist" \
    "$_profile" "$_bundle_id" "$_dev_entitlements"
  cp "$_profile" "$_app/Contents/embedded.provisionprofile"
  sign --identifier "$_bundle_id" --options restrict,library,runtime,kill --entitlements "$_dev_entitlements" "$_app"
elif (( _ad_hoc )); then
  sign --identifier "$_bundle_id" --options restrict,library,runtime,kill --entitlements "$_root_dir/entitlements/app-entitlements.plist" "$_app"
else
  sign --identifier "$_bundle_id" --options restrict,library,runtime,kill --entitlements "$_root_dir/entitlements/app-entitlements.plist" --requirements "=designated => identifier \"$_bundle_id\" and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] /* exists */ and certificate leaf[field.1.2.840.113635.100.6.1.13] /* exists */" "$_app"
fi

# Verify the binary signature
verify_dylib() {
  local dylib="$1"
  local signature_info

  codesign --verify --strict --verbose=4 "$dylib"

  if (( _ad_hoc || _dev )); then
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

# Notarizes and staples the app or the DMG given (M5). The credentials are a
# notarytool keychain profile the user saved once
# (`xcrun notarytool store-credentials tark-notary`); no password passes
# through the environment.
notarize() {
  local target="$1"
  local upload="$target"
  local result="$TMPDIR/notary-result.json"
  local log="$TMPDIR/notary-log.json"
  local status submission_id
  local submit_exit=0
  local credentials=(--keychain-profile "${TARKA_NOTARY_PROFILE:-tark-notary}")

  if [[ -d "$target" ]]; then
    upload="$TMPDIR/notarize.zip"
    rm -f "$upload"
    ditto -c -k --keepParent "$target" "$upload"
  fi

  xcrun notarytool submit --wait --output-format json "${credentials[@]}" "$upload" \
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

  xcrun stapler staple "$target"
  xcrun stapler validate "$target"
}

if (( _ad_hoc )); then
  printf 'Ad-hoc signing enabled; skipping notarization and stapling.\n'
elif (( _dev )); then
  printf 'Development signing; skipping notarization and stapling.\n'
  if [[ "${TARKA_SKIP_DMG:-0}" == 1 ]]; then
    exit 0
  fi
else
  notarize "$_app"
fi

# Package the app (an APFS image, never pkg-dmg's HFS hybrid; see the script).
"$_root_dir/utils/package_dmg.sh" "$_app" "$_target_dmg"

# A release DMG is notarized and stapled too, so it opens offline without a
# Gatekeeper prompt about the image itself.
if (( ! _ad_hoc && ! _dev )); then
  codesign --sign "$MACOS_CERTIFICATE_NAME" --timestamp "$_target_dmg"
  codesign --verify --strict "$_target_dmg"
  notarize "$_target_dmg"
fi

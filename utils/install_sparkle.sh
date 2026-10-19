#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   utils/install_sparkle.sh APP SPARKLE.framework CHROMIUM_SRC REVISION
#
# Puts Sparkle 2 into APP for updates from gettarka.com (M5), before signing:
# - copies the framework into Contents/Frameworks (Tark loads it at run time,
#   see patches/tarka/updater/sparkle.patch) without its XPC services, which
#   only sandboxed apps need;
# - writes the update settings into Info.plist;
# - sets CFBundleVersion to BUILD.PATCH.REVISION (8059.39.1). Sparkle orders
#   versions by CFBundleVersion, and Chromium's BUILD.PATCH alone would make
#   two Tark releases of one Chromium version look equal.
# TARKA_SPARKLE_FEED_URL replaces the feed for tests; TARKA_SPARKLE_PUBLIC_KEY
# replaces the key (the private half is in the release Mac's login keychain,
# account "tark", made with Sparkle's generate_keys).
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 APP SPARKLE.framework CHROMIUM_SRC REVISION" >&2
  exit 2
fi
app="${1%/}"
sparkle_src="${2%/}"
src="$3"
revision="$4"
feed="${TARKA_SPARKLE_FEED_URL:-https://gettarka.com/appcast.xml}"
public_key="${TARKA_SPARKLE_PUBLIC_KEY:-jifHjeHnUyao+9lgJ+TZ/mDQuNhOmXw/gNfI7uJKmQk=}"

if [[ ! -d "$sparkle_src" ]]; then
  echo "error: no Sparkle.framework at $sparkle_src" >&2
  exit 1
fi
if [[ ! "$revision" =~ ^[0-9]+$ ]]; then
  echo "error: revision must be a number, not '$revision'" >&2
  exit 1
fi

sparkle="$app/Contents/Frameworks/Sparkle.framework"
rm -rf "$sparkle"
ditto "$sparkle_src" "$sparkle"
rm -rf "$sparkle/XPCServices" "$sparkle/Versions/B/XPCServices"

build="$(sed -n 's/^BUILD=//p' "$src/chrome/VERSION")"
patch="$(sed -n 's/^PATCH=//p' "$src/chrome/VERSION")"
plist="$app/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$build.$patch.$revision" "$plist"
plutil -replace SUFeedURL -string "$feed" "$plist"
plutil -replace SUPublicEDKey -string "$public_key" "$plist"
plutil -replace SUEnableAutomaticChecks -bool YES "$plist"
plutil -replace SUScheduledCheckInterval -integer 86400 "$plist"
plutil -replace SUEnableSystemProfiling -bool NO "$plist"
plutil -replace SUAllowsAutomaticUpdates -bool YES "$plist"
echo "Sparkle installed; CFBundleVersion $build.$patch.$revision; feed $feed"

#!/bin/sh
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# netcheck.sh DEVICE SECONDS
#
# Installs the simulator build fresh on DEVICE, launches it and lists every
# outside address the app's own process connects to in SECONDS. Pages load
# in WebKit's separate process, so an idle fresh install should list none.
D=$1; N=$2; B=com.gettarka.Tarka.dev
A=$(dirname "$0")/../build/ios/dd/Build/Products/Debug-iphonesimulator/Client.app
xcrun simctl terminate "$D" $B 2>/dev/null
xcrun simctl uninstall "$D" $B
xcrun simctl install "$D" "$A"
P=$(xcrun simctl launch "$D" $B | awk '{print $2}')
O=$(mktemp); i=0
while [ $i -lt "$N" ]; do
  lsof -nP -a -p "$P" -iTCP 2>/dev/null | awk 'NR>1{print $9}' >> "$O"
  sleep 1; i=$((i+1))
done
sed -E 's/.*->//; s/:[0-9]+$//' "$O" | grep -vE '^(127\.0\.0\.1|\[::1\])$' | grep -v '\*' | sort -u
rm -f "$O"

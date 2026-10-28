#!/bin/sh
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# netcapture.sh DEVICE SECONDS OUT
#
# For SECONDS, records every outside TCP connection made by Tark on the
# simulator DEVICE: the app, its extensions (widget, share, ...) and the
# WebKit processes the simulator runs for it (networking and web content).
# netcheck.sh sees the app's own process only. Appends "pid process addr"
# lines to OUT; netcapture-report.sh turns them into hosts.
D=$1; N=$2; OUT=$3
i=0
while [ "$i" -lt "$N" ]; do
  for p in $(pgrep -f "Devices/$D/" ; pgrep -f "WebKit|WebContentExtension|NetworkingExtension|GPUExtension"); do
    case $(ps eww -p "$p" 2>/dev/null) in
      *"Devices/$D/"*|*"SIMULATOR_UDID=$D"*) ;;
      *) continue ;;
    esac
    name=$(ps -o comm= -p "$p" | sed 's#.*/##')
    lsof -nP -a -p "$p" -iTCP 2>/dev/null | awk -v n="$name" -v p="$p" 'NR>1 && $9 ~ /->/ {sub(/.*->/,"",$9); sub(/:[0-9]+$/,"",$9); print p, n, $9}'
  done | sort -u >> "$OUT"
  sleep 1; i=$((i+1))
done

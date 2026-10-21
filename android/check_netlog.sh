#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   android/check_netlog.sh NETLOG.json
#
# A1: lists the hosts an Android net log shows Tark contacting and exits 1 if
# any is not in android/allowed_hosts.txt (the Mac's checker,
# utils/net_hosts.py).
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "usage: $0 NETLOG.json" >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$root/utils/net_hosts.py" "$1" --allowed "$root/android/allowed_hosts.txt"

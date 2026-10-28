#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   linux/check_deb.sh OUT REPORT
#
# L3: OUT's tark_*_amd64.deb as people get it: installed with apt in a clean
# Ubuntu 24.04 container (its Depends resolve), the tark command starts Tark
# and it renders a page headless, and apt removes it again. Each check prints
# `ok NAME` or `FAIL NAME: why` into REPORT/deb-checks.txt; any FAIL fails the
# script. The container has no user namespaces for Chromium's sandbox, so the
# page check alone runs with --no-sandbox; the sandbox is checked on a desktop.
set -uo pipefail
out=$1; report=$2
mkdir -p "$report"
txt=$report/deb-checks.txt
: > "$txt"
deb=$(ls "$out"/tark_*_amd64.deb 2>/dev/null | head -1)
[[ -n $deb ]] || { echo "FAIL deb: no tark_*_amd64.deb in $out" | tee -a "$txt"; exit 1; }

sudo docker run --rm -v "$out:/out:ro" ubuntu:24.04 bash -c '
  set -u
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null
  if apt-get install -y -q /out/'"$(basename "$deb")"' > /tmp/install.log 2>&1; then
    echo "ok installs"
  else
    echo "FAIL installs: $(tail -3 /tmp/install.log | tr "\n" " ")"; exit 0
  fi
  [ -L /usr/bin/tark ] && [ -f /usr/share/applications/tark.desktop ] && [ -f /etc/apparmor.d/tark ] \
    && echo "ok files" || echo "FAIL files: launcher, desktop entry or AppArmor profile missing"
  if timeout 120 tark --headless=new --no-sandbox --no-first-run --user-data-dir=/tmp/p \
      --dump-dom "data:text/html,<title>tark-deb-ok</title>" 2>/tmp/run.log | grep -q tark-deb-ok; then
    echo "ok starts"
  else
    echo "FAIL starts: $(tail -3 /tmp/run.log | tr "\n" " ")"
  fi
  apt-get remove -y -q tark >/dev/null 2>&1 && [ ! -e /usr/bin/tark ] && echo "ok removes" || echo "FAIL removes"
' 2>&1 | tee -a "$txt"
! grep -q '^FAIL' "$txt" && grep -q '^ok removes' "$txt"

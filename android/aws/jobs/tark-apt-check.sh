#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   tark-apt-check.sh BUCKET PREFIX SUBMODULE_COMMIT [REPO_PATH]
#
# L3: Tark's apt repository as people meet it, in a clean Ubuntu 24.04
# container: install the oldest .deb in REPO_PATH (default apt-test) from its
# file, check it added Tark's source and key, point the source at REPO_PATH,
# and check that apt update accepts the signature and apt upgrade installs
# the newest. Results (ok/FAIL lines) and the log go to the job's S3 prefix;
# the machine powers off at the end unless another job is running.
set -uo pipefail
B=$1; P=$2; path=${4:-apt-test}
cd /tark
exec 9>/tark/job.lock
flock -n 9 || { echo "another Tark job is running on this machine"; exit 1; }
out=/tark/apt-check.txt
finish() {
  aws s3 cp --quiet "$out" "s3://$B/$P/apt-check.txt"
  if ! pgrep -f 'ninja|android/build.sh|scripts/build.sh' | grep -vq "^$$\$"; then sudo poweroff; fi
}
trap finish EXIT
sudo docker run --rm -e REPO="https://gettarka.com/$path" ubuntu:24.04 bash -c '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null && apt-get install -y -q curl ca-certificates >/dev/null
  first=$(curl -sSf "$REPO/dists/stable/main/binary-amd64/Packages" | sed -n "s/^Filename: //p" | sort -V | head -1)
  newest=$(curl -sSf "$REPO/dists/stable/main/binary-amd64/Packages" | sed -n "s/^Version: //p" | sort -V | tail -1)
  curl -sSf -o /tmp/tark.deb "$REPO/$first" || { echo "FAIL download $first"; exit 0; }
  apt-get install -y -q /tmp/tark.deb > /tmp/install.log 2>&1 && echo "ok installs $(dpkg-query -W -f="\${Version}" tark)" \
    || { echo "FAIL installs: $(tail -2 /tmp/install.log | tr "\n" " ")"; exit 0; }
  grep -q "https://gettarka.com/apt stable main" /etc/apt/sources.list.d/tark.list && \
    [ -s /usr/share/keyrings/tark-archive-keyring.gpg ] && echo "ok source and key added" || echo "FAIL source and key"
  sed -i "s#https://gettarka.com/apt #$REPO #" /etc/apt/sources.list.d/tark.list
  if apt-get update > /tmp/update.log 2>&1 && ! grep -qi "NO_PUBKEY\|not signed\|BADSIG\|Err:" /tmp/update.log; then
    echo "ok apt update verifies the signature"
  else
    echo "FAIL apt update: $(grep -i "err\|warn\|sig" /tmp/update.log | head -3 | tr "\n" " ")"
  fi
  apt-get upgrade -y -q > /tmp/upgrade.log 2>&1
  got=$(dpkg-query -W -f="\${Version}" tark)
  [ "$got" = "$newest" ] && echo "ok apt upgrade installs $got" || echo "FAIL apt upgrade: has $got, wants $newest"
' > "$out" 2>&1
cat "$out"
! grep -q '^FAIL' "$out" && grep -q '^ok apt upgrade' "$out"

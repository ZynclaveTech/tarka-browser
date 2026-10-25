#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# One-time setup of Tark's Android build machine (A1), run as root by
# cloud-init (create.sh's user data): Chromium's Linux and Android build
# dependencies (its own install-build-deps for the pinned version), the AWS
# CLI, 32 GB of swap, and an idle watchdog that powers the machine off
# (which stops the instance) after 30 minutes with no build running.
set -euxo pipefail
exec > >(tee -a /var/log/tark-bootstrap.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
VERSION=156.0.8078.47

# A setup step that fails powers the machine off rather than leave it billing.
trap 'poweroff' ERR

# Idle watchdog first, so the machine stops itself even if setup fails:
# every 10 minutes; three idle checks in a row (30 min) power the machine
# off, which stops the instance.
cat > /usr/local/bin/tark-idle-check <<'WATCH'
#!/bin/bash
flag=/var/lib/tark-idle-count
if pgrep -f 'ninja|android/build.sh|clone.py|gclient|cloud-init|apt' >/dev/null; then echo 0 > $flag; exit 0; fi
n=$(( $(cat $flag 2>/dev/null || echo 0) + 1 )); echo $n > $flag
if [ $n -ge 3 ]; then echo 0 > $flag; poweroff; fi
WATCH
chmod +x /usr/local/bin/tark-idle-check
cat > /etc/systemd/system/tark-idle-stop.service <<'UNIT'
[Unit]
Description=Tark builder: power off after 30 idle minutes
[Service]
Type=oneshot
ExecStart=/usr/local/bin/tark-idle-check
UNIT
cat > /etc/systemd/system/tark-idle-stop.timer <<'UNIT'
[Unit]
Description=Tark builder idle check every 10 minutes
[Timer]
OnBootSec=10min
OnUnitActiveSec=10min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now tark-idle-stop.timer

apt-get update
apt-get install -y git python3 python3-pip curl xz-utils unzip zstd lsb-release sudo ninja-build libarchive-tools
snap install aws-cli --classic

# Chromium's own dependency script for this version, with --android.
mkdir -p /opt/tark && cd /opt/tark
for f in install-build-deps.sh install-build-deps.py; do
  curl -fsSL --retry 8 --retry-delay 15 --retry-all-errors "https://chromium.googlesource.com/chromium/src/+/refs/tags/$VERSION/build/$f?format=TEXT" | base64 -d > $f
done
chmod +x install-build-deps.sh install-build-deps.py
./install-build-deps.sh --android --no-prompt --no-chromeos-fonts --no-nacl

# Swap: the framework link wants more than RAM on smaller types.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 32G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
mkdir -p /tark && chown ubuntu:ubuntu /tark
echo 'bootstrap done'

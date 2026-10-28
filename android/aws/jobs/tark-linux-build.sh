#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   tark-linux-build.sh BUCKET PREFIX SUBMODULE_COMMIT [--fresh] [--dry-run]
#
# L1: build Tark for Linux x64 on the Android build machine, from the source
# andbuild.sh put in S3, in upstream's Docker image (linux/upstream/docker).
# Linux keeps to $ROOT/linux (the repo, the work folder and its Chromium
# tree, kept between runs; --fresh wipes the tree) and takes the machine's one
# job lock, so it never touches Android's checkout or runs beside its build.
# The tarball, its sha256, the checks and the log go to the job's S3 prefix;
# the machine powers off at the end unless another build is running.
# --dry-run (the Mac's test): the lock and disk checks, then the plan only.
set -uo pipefail
B=$1; P=$2; SUB=$3; shift 3
fresh=0; dry=0
for a in "$@"; do
  case $a in --fresh) fresh=1;; --dry-run) dry=1;; esac
done
ROOT=${TARK_ROOT:-/tark}
L=$ROOT/linux
repo=$L/repo
work=$L/tl
mkdir -p "$L"
cd "$L"

# One job at a time: Android's jobs take the same lock.
exec 9>"$ROOT/job.lock"
flock -n 9 || { echo "another Tark job is running on this machine"; exit 1; }

# A Chromium tree and its build need about 100 GB; Android's checkout stays.
free=${TARK_FREE_GB:-$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc 0-9)}
if (( free < 150 )); then
  echo "refused: ${free} GB free on $ROOT; a Linux build needs 150 GB"
  exit 1
fi

if (( dry )); then
  echo "repo $repo"
  echo "work $work"
  echo "free ${free} GB"
  exit 0
fi

log=$L/tark-linux-build.log
echo "tark-linux-build $P $(date -Is)" > "$log"
upload() { [[ -f $1 ]] && aws s3 cp --quiet "$1" "s3://$B/$P/$2"; }
finish() {
  upload "$log" tark-linux-build.log
  if ! pgrep -f 'ninja|android/build.sh|scripts/build.sh' | grep -vq "^$$\$"; then sudo poweroff; fi
}
trap finish EXIT

must() { "$@" >> "$log" 2>&1 || { echo "failed: $*" >> "$log"; exit 1; }; }
must rm -rf "$repo"
must mkdir -p "$repo"
must aws s3 cp --quiet "s3://$B/$P/src.tar.gz" "$L/src.tar.gz"
must tar -xzf "$L/src.tar.gz" -C "$repo"
[[ $SUB =~ ^[0-9a-f]{40}$ ]] || { echo "bad submodule commit '$SUB'" >> "$log"; exit 1; }
must git clone --quiet --no-checkout https://github.com/ungoogled-software/ungoogled-chromium.git "$repo/ungoogled-chromium"
must git -C "$repo/ungoogled-chromium" fetch --quiet origin "$SUB"
must git -C "$repo/ungoogled-chromium" checkout --quiet --detach "$SUB"
echo "submodule $SUB" >> "$log"

(( fresh )) && rm -rf "$work/build/src"
must python3 "$repo/linux/prepare_workdir.py" "$repo" "$work"

# Upstream builds in its own Debian image (system Node, tsc, esbuild, Go).
# Its Dockerfile needs BuildKit (COPY --chmod): Ubuntu's docker-buildx.
if ! command -v docker >/dev/null || ! sudo docker buildx version >/dev/null 2>&1; then
  must sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker.io docker-buildx
fi
must sudo docker buildx build --load -q -t tark-linux-builder -f "$work/docker/build.Dockerfile" "$work/docker"

# The ad blocker's list bundle staged in s3://BUCKET/lists/, as for Android.
rm -rf "$L/lists" && mkdir -p "$L/lists"
lists=()
if aws s3 cp --quiet --recursive "s3://$B/lists/" "$L/lists/" && [[ -f $L/lists/latest.json ]]; then
  lists=(-e TARK_LISTS_DIR="$L/lists")
fi

# The repo and the lists are mounted at their own paths: tark_repo.txt names
# the repo's path, which the container must see the same.
timeout 8h sudo docker run --rm -u "$(id -u):$(id -g)" \
  -v "$work:/repo" -v "$repo:$repo:ro" -v "$L/lists:$L/lists:ro" "${lists[@]}" \
  tark-linux-builder bash /repo/scripts/build.sh >> "$log" 2>&1
code=$?
echo "build exit $code" >> "$log"

# An earlier run's tarball or checks must never pass as this job's.
rm -rf "$L/out" "$L/checks"
if (( code == 0 )); then
  bash "$repo/linux/package_tarball.sh" "$repo" "$work/build/src/out/Default" "$L/out" >> "$log" 2>&1 || code=1
fi
if (( code == 0 )); then
  # The window picture needs Xvfb and ImageMagick; without them it is skipped.
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q xvfb imagemagick >> "$log" 2>&1 || true
  bash "$repo/linux/check_build.sh" "$L/out" "$L/checks" >> "$log" 2>&1 || code=1
  for f in "$L"/checks/*; do upload "$f" "checks/$(basename "$f")"; done
fi
if (( code == 0 )); then
  for f in "$L"/out/*.tar.xz "$L"/out/*.sha256; do upload "$f" "$(basename "$f")"; done
fi
echo "exit $code" >> "$log"
exit $code

#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   tark-linux-build.sh BUCKET PREFIX SUBMODULE_COMMIT [--fresh] [--package-only] [--dry-run]
#
# L1: build Tark for Linux x64 on the Android build machine, from the source
# andbuild.sh put in S3, in upstream's Docker image (linux/upstream/docker).
# Linux keeps to $ROOT/linux (the repo, the work folder and its Chromium
# tree, kept between runs; --fresh wipes the tree) and takes the machine's one
# job lock, so it never touches Android's checkout or runs beside its build.
# The tarball, its sha256, the checks and the log go to the job's S3 prefix;
# the machine powers off at the end unless another build is running.
# --package-only: package and check the build already on the machine (upstream's
# build.sh deletes out/ first, so a re-run would compile everything again).
# --dry-run (the Mac's test): the lock and disk checks, then the plan only.
set -uo pipefail
B=$1; P=$2; SUB=$3; shift 3
fresh=0; dry=0; package_only=0
for a in "$@"; do
  case $a in --fresh) fresh=1;; --dry-run) dry=1;; --package-only) package_only=1;; esac
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
  (( package_only )) && echo "package only"
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

if (( package_only )); then
  code=0
  echo "package only: the build already on the machine" >> "$log"
else
  # The name substitution backup goes with the tree: --sub refuses to run
  # when it exists.
  (( fresh )) && rm -rf "$work/build/src" "$work/build/namesubs.tar"
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
  # A failed compile goes on past its first errors, so one run lists them
  # all (the job still fails).
  if (( code != 0 )) && [[ -f $work/build/src/out/Default/build.ninja ]]; then
    echo "keep going: every compile error" >> "$log"
    timeout 2h sudo docker run --rm -u "$(id -u):$(id -g)" \
      -v "$work:/repo" -v "$repo:$repo:ro" tark-linux-builder \
      ninja -k 0 -C /repo/build/src/out/Default chrome chromedriver \
        tark_captions_unittests tark_speech_unittests tark_page_translate_unittests >> "$log" 2>&1
  fi
fi
echo "build exit $code" >> "$log"

# Tark's unit tests (captions with ONNX Runtime, speech, transliteration),
# built and run in the build image on the same tree.
if (( code == 0 )); then
  rm -rf "$L/tests" && mkdir -p "$L/tests"
  timeout 2h sudo docker run --rm -u "$(id -u):$(id -g)" \
    -v "$work:/repo" -v "$repo:$repo:ro" -v "$L/tests:$L/tests" \
    tark-linux-builder bash "$repo/linux/run_tests.sh" /repo/build/src "$L/tests" >> "$log" 2>&1 || code=1
  for f in "$L"/tests/*; do upload "$f" "tests/$(basename "$f")"; done
  echo "tests exit $code" >> "$log"
fi
# An earlier run's tarball or checks must never pass as this job's.
rm -rf "$L/out" "$L/checks"
if (( code == 0 )); then
  bash "$repo/linux/package_tarball.sh" "$repo" "$work/build/src/out/Default" "$L/out" >> "$log" 2>&1 || code=1
fi
if (( code == 0 )); then
  # The window picture needs Xvfb and ImageMagick (without them it is skipped);
  # the Zynclave checks need websocket-client.
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q xvfb imagemagick python3-websocket >> "$log" 2>&1 || true
  bash "$repo/linux/check_build.sh" "$L/out" "$L/checks" >> "$log" 2>&1 || code=1
  for f in "$L"/checks/*; do upload "$f" "checks/$(basename "$f")"; done
fi
# L4: Sign in with Zynclave on the tarball's Tark, against production
# Zynclave (a release build), under Xvfb: the Settings card, the sign-in page,
# stray redirects ignored, the policy known (utils/zynclave_e2e.py).
if (( code == 0 )); then
  unpacked=$(mktemp -d)
  tar -xJf "$L"/out/Tark-*-x64-linux.tar.xz -C "$unpacked"
  timeout 15m xvfb-run -a -s "-screen 0 1280x800x24" \
    python3 "$repo/utils/zynclave_e2e.py" "$(ls -d "$unpacked"/Tark-*/)" --production \
    > "$L/checks/zynclave.txt" 2>&1 || code=1
  cat "$L/checks/zynclave.txt" >> "$log"
  upload "$L/checks/zynclave.txt" checks/zynclave.txt
  rm -rf "$unpacked"
fi
# Desktop page translation on the tarball's Tark: a Hindi page, and text its
# JS adds later, turned into English on the computer by the real models
# (utils/translate_e2e.py).
if (( code == 0 )); then
  unpacked=$(mktemp -d)
  models=$(mktemp -d)
  tar -xJf "$L"/out/Tark-*-x64-linux.tar.xz -C "$unpacked"
  if bash "$repo/linux/fetch_translate_models.sh" "$work/build/src" "$models" >> "$log" 2>&1; then
    timeout 15m xvfb-run -a -s "-screen 0 1280x800x24" \
      python3 "$repo/utils/translate_e2e.py" "$(ls -d "$unpacked"/Tark-*/)" "$models" \
      --screenshot "$L/checks/translate-bar.png" \
      > "$L/checks/translate.txt" 2>&1 || code=1
  else
    echo "FAIL translate: could not fetch the translation models" > "$L/checks/translate.txt"; code=1
  fi
  cat "$L/checks/translate.txt" >> "$log"
  upload "$L/checks/translate.txt" checks/translate.txt
  [[ -f $L/checks/translate-bar.png ]] && upload "$L/checks/translate-bar.png" checks/translate-bar.png
  rm -rf "$unpacked" "$models"
fi
# L3: the .deb, from the tarball as people get it, then installed and started
# in a clean Ubuntu.
if (( code == 0 )); then
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q dpkg-dev >> "$log" 2>&1 || true
  unpacked=$(mktemp -d)
  tar -xJf "$L"/out/Tark-*-x64-linux.tar.xz -C "$unpacked" &&
    bash "$repo/linux/package_deb.sh" "$repo" "$unpacked"/Tark-*/ "$work/build/src" "$L/out" >> "$log" 2>&1 || code=1
  rm -rf "$unpacked"
fi
if (( code == 0 )); then
  bash "$repo/linux/check_deb.sh" "$L/out" "$L/checks" >> "$log" 2>&1 || code=1
  upload "$L/checks/deb-checks.txt" checks/deb-checks.txt
fi
if (( code == 0 )); then
  for f in "$L"/out/*.tar.xz "$L"/out/*.sha256 "$L"/out/*.deb; do upload "$f" "$(basename "$f")"; done
fi
echo "exit $code" >> "$log"
exit $code

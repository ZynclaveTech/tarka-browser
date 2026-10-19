#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   tark-build.sh BUCKET PREFIX SUBMODULE_COMMIT [--stop-before-gn] [--fresh]
#
# A1: build Tark for Android from the source andbuild.sh put in S3. /tark/work
# keeps the Chromium checkout between runs (--fresh wipes it). The APK and the
# log go to the job's S3 prefix; the machine powers off at the end, success
# or not, unless another build is still running.
set -uo pipefail
B=$1; P=$2; SUB=$3; shift 3
stop=""; fresh=0
for a in "$@"; do
  case $a in --stop-before-gn) stop=--stop-before-gn;; --fresh) fresh=1;; esac
done
log=/tark/tark-build.log
echo "tark-build $P $(date -Is)" > $log
upload() { [[ -f $1 ]] && aws s3 cp --quiet "$1" "s3://$B/$P/$2"; }
finish() {
  upload $log tark-build.log
  if ! pgrep -f 'ninja|android/build.sh' | grep -vq "^$$\$"; then sudo poweroff; fi
}
trap finish EXIT

# Setting up the source is all-or-nothing: any failure ends the job before a
# build can run on a missing or wrong tree.
must() { "$@" >> $log 2>&1 || { echo "failed: $*" >> $log; exit 1; }; }
repo=/tark/repo
must rm -rf $repo
must mkdir -p $repo
must aws s3 cp --quiet "s3://$B/$P/src.tar.gz" /tark/src.tar.gz
must tar -xzf /tark/src.tar.gz -C $repo
# ungoogled-chromium at exactly the submodule's commit, verified.
[[ $SUB =~ ^[0-9a-f]{40}$ ]] || { echo "bad submodule commit '$SUB'" >> $log; exit 1; }
must git clone --quiet --no-checkout https://github.com/ungoogled-software/ungoogled-chromium.git $repo/ungoogled-chromium
must git -C $repo/ungoogled-chromium fetch --quiet origin "$SUB"
must git -C $repo/ungoogled-chromium checkout --quiet --detach "$SUB"
[[ $(git -C $repo/ungoogled-chromium rev-parse HEAD) == "$SUB" ]] || { echo "submodule is not $SUB" >> $log; exit 1; }
echo "submodule $SUB" >> $log

(( fresh )) && rm -rf /tark/work/src
bash $repo/android/build.sh $stop /tark/work >> $log 2>&1
code=$?
echo "exit $code" >> $log
upload /tark/work/src/out/Default/apks/ChromePublic.apk ChromePublic.apk
exit $code

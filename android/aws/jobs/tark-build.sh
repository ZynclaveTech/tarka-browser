#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   tark-build.sh BUCKET PREFIX SUBMODULE_COMMIT [--stop-before-gn] [--fresh]
#
# A1: build Tark for Android from the source andbuild.sh put in S3. /tark/work
# keeps the Chromium checkout and its base copy between runs (--fresh wipes
# both). The APK and the log go to the job's S3 prefix; the machine powers off
# at the end, success or not, unless another build is still running.
set -uo pipefail
B=$1; P=$2; SUB=$3; shift 3
stop=""; fresh=0
for a in "$@"; do
  case $a in --stop-before-gn) stop=--stop-before-gn;; --fresh) fresh=1;; esac
done
# Never the SSM agent's folder: tools write state into their working directory.
cd /tark
# One job at a time: jobs share /tark/repo, /tark/work and the log.
exec 9>/tark/job.lock
flock -n 9 || { echo "another Tark job is running on this machine"; exit 1; }
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

(( fresh )) && rm -rf /tark/work/src /tark/work/src-base /tark/work/prepared.stamp /tark/work/base.stamp /tark/work/layers.json
# An earlier build's APK must never be uploaded as this job's.
rm -f /tark/work/src/out/Default/apks/ChromePublic.apk
# A2: a list bundle staged in s3://BUCKET/lists/ (latest.json and its zip)
# stands in for gettarka.com's; build.sh checks its signature either way.
rm -rf /tark/lists && mkdir -p /tark/lists
if aws s3 cp --quiet --recursive "s3://$B/lists/" /tark/lists/ && [[ -f /tark/lists/latest.json ]]; then
  export TARK_LISTS_DIR=/tark/lists
fi
# A hung step (a stalled sync, a stuck link) ends here instead of billing on.
timeout 8h bash $repo/android/build.sh $stop /tark/work >> $log 2>&1
code=$?
echo "exit $code" >> $log
(( code == 0 )) && upload /tark/work/src/out/Default/apks/ChromePublic.apk ChromePublic.apk
# A3: the IndicXlit files this APK pins (android/xlit/files.py), for the
# emulator checks and for publishing on gettarka.com.
if (( code == 0 )); then
  tar -czf /tark/xlit-files.tgz -C /tark/work/src/third_party/indicxlit android
  upload /tark/xlit-files.tgz xlit-files.tgz
fi
exit $code

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

repo=/tark/repo
rm -rf $repo && mkdir -p $repo
aws s3 cp --quiet "s3://$B/$P/src.tar.gz" /tark/src.tar.gz >> $log 2>&1
tar -xzf /tark/src.tar.gz -C $repo >> $log 2>&1
cache=/tark/ungoogled-chromium.git
[[ -d $cache ]] || git clone --quiet --bare https://github.com/ungoogled-software/ungoogled-chromium.git $cache >> $log 2>&1
git -C $cache fetch --quiet origin >> $log 2>&1
git clone --quiet --reference $cache https://github.com/ungoogled-software/ungoogled-chromium.git $repo/ungoogled-chromium >> $log 2>&1
git -C $repo/ungoogled-chromium checkout --quiet $SUB >> $log 2>&1
echo "submodule $SUB" >> $log

(( fresh )) && rm -rf /tark/work/src
bash $repo/android/build.sh $stop /tark/work >> $log 2>&1
code=$?
echo "exit $code" >> $log
upload /tark/work/src/out/Default/apks/ChromePublic.apk ChromePublic.apk
exit $code

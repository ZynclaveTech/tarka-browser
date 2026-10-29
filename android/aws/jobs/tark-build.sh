#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   tark-build.sh BUCKET PREFIX SUBMODULE_COMMIT [--stop-before-gn] [--fresh] [--zynclave-staging]
#
# --zynclave-staging: a test APK on Zynclave staging (tark_zynclave_staging =
# true in out/Default/args.gn, through build.sh's TARK_ZYNCLAVE_STAGING); never one to publish.
#
# A1: build Tark for Android from the source andbuild.sh put in S3. /tark/work
# keeps the Chromium checkout and its base copy between runs (--fresh wipes
# both). The APK and the log go to the job's S3 prefix; the machine powers off
# at the end, success or not, unless another build is still running.
set -uo pipefail
B=$1; P=$2; SUB=$3; shift 3
stop=""; fresh=0; staging=""
for a in "$@"; do
  case $a in --stop-before-gn) stop=--stop-before-gn;; --fresh) fresh=1;; --zynclave-staging) staging=1;; esac
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
rm -f /tark/work/src/out/Default/apks/ChromePublic.apk /tark/work/src/out/Default/apks/ChromePublic.aab
# A2: a list bundle staged in s3://BUCKET/lists/ (latest.json and its zip)
# stands in for gettarka.com's; build.sh checks its signature either way.
rm -rf /tark/lists && mkdir -p /tark/lists
if aws s3 cp --quiet --recursive "s3://$B/lists/" /tark/lists/ && [[ -f /tark/lists/latest.json ]]; then
  export TARK_LISTS_DIR=/tark/lists
fi
# A hung step (a stalled sync, a stuck link) ends here instead of billing on.
TARK_ZYNCLAVE_STAGING=${staging:-0} timeout 8h bash $repo/android/build.sh $stop /tark/work >> $log 2>&1
code=$?
echo "exit $code" >> $log
# The captions downloads' sharing rules (voice and captions share the
# language detector) and voice's detector ring run in build.sh's host
# tests: each must have run.
if (( code == 0 )); then
  for t in RemoveKeepsUnitCaptionsUses RemoveDeletesWhenNoOwner SharedNoSecondDownload \
      RequestAfterPendingRemoveKeepsUnit ReleaseKeepsUnitWantedAgain InUseRemoveWhileKeptThenRelease \
      RetryBacksOffThenGivesUp InterruptedDownloadResumes ResumeKeepsDownloadNow; do
    grep -qE "^\[[0-9]+/[0-9]+\] CaptionDownloadsTest\.$t \([0-9]+ ms\)$" $log || { echo "no CaptionDownloadsTest.$t test ran" >> $log; code=1; }
    grep -qE "CaptionDownloadsTest\.$t.*(SKIPPED|FAILED)|(SKIPPED|FAILED).*CaptionDownloadsTest\.$t" $log && { echo "CaptionDownloadsTest.$t did not pass" >> $log; code=1; }
  done
  # Background play's visibility hold (media-background-play.patch), kept
  # while in Picture in Picture (media-pip-on-leave.patch).
  for t in PlayingWithSoundThenHideStaysVisible NothingPlayingThenHideIsHidden MutedThenHideIsHidden \
      HoldReleasedWhenMediaPauses HoldReleasedWhenEnded SilentStretchWhilePlayingKeepsTheHold SettingsOffIsUpstream \
      OnlyPictureInPictureWithoutWindowIsUpstream OnlyPictureInPictureWithWindowIsHeld BackgroundPlayOnlyIsHeld \
      PausedInPictureInPictureStaysHeld PictureInPictureClosedWhilePausedReleases PictureInPictureCloseButtonReleases \
      Allowed LaterHiddenUpdatesKeepTheHold ShowAfterHoldSendsNoEvent NoHoldAgainAfterRelease NeverShownTabIsNotHeld \
      HoldAgainAfterShowingAgain; do
    grep -qE "^\[[0-9]+/[0-9]+\] TarkVisibilityHoldTest\.$t \([0-9]+ ms\)$" $log || { echo "no TarkVisibilityHoldTest.$t test ran" >> $log; code=1; }
    grep -qE "TarkVisibilityHoldTest\.$t.*(SKIPPED|FAILED)|(SKIPPED|FAILED).*TarkVisibilityHoldTest\.$t" $log && { echo "TarkVisibilityHoldTest.$t did not pass" >> $log; code=1; }
  done
  # Voice search's detector: its 15 s ring of audio (voice-language-detect.patch).
  for t in RingBufferKeeps15s RingBufferHoldsLessWhenShorter RingBufferDropsAtSessionEnd NoModelsDecidesNothing \
      SharedModelsWaitForAttachedSessions UnattachedDetectorLeavesSharedUseAlone; do
    grep -qE "^\[[0-9]+/[0-9]+\] VoiceLanguageDetectorTest\.$t \([0-9]+ ms\)$" $log || { echo "no VoiceLanguageDetectorTest.$t test ran" >> $log; code=1; }
    grep -qE "VoiceLanguageDetectorTest\.$t.*(SKIPPED|FAILED)|(SKIPPED|FAILED).*VoiceLanguageDetectorTest\.$t" $log && { echo "VoiceLanguageDetectorTest.$t did not pass" >> $log; code=1; }
  done
fi
(( code == 0 )) && upload /tark/work/src/out/Default/apks/ChromePublic.apk ChromePublic.apk
(( code == 0 )) && upload /tark/work/src/out/Default/apks/ChromePublic.aab ChromePublic.aab
# A3: the IndicXlit files this APK pins (android/xlit/files.py), for the
# emulator checks and for publishing on gettarka.com.
if (( code == 0 )); then
  tar -czf /tark/xlit-files.tgz -C /tark/work/src/third_party/indicxlit android
  upload /tark/xlit-files.tgz xlit-files.tgz
fi
# The junit tests of the speech and voice patches (voice input) and of the
# Private button (private-tab-button.patch), of Sign in with Zynclave
# (zynclave-*.patch), of Background play (media-background-play.patch) and of
# Picture in Picture on leave (media-pip-on-leave.patch), built and
# run here on the same tree (the runners with a venv's Python: there is no
# vpython3); a failure, or a filter that runs no test, fails the job.
if (( code == 0 )); then
  o=/tark/work/src/out/Default
  # The runners' unittest_util.py subclasses unittest._TextTestResult, gone
  # from the machine's Python 3.12 (vpython brings 3.11): alias it back.
  mkdir -p /tark/pyshim
  echo 'import unittest; unittest._TextTestResult = unittest.TextTestResult' > /tark/pyshim/sitecustomize.py
  export PYTHONPATH=/tark/pyshim
  # vpython also brings the runners' packages (protobuf: the tree's copy
  # lacks the generated well-known types; devil needs packaging): a venv of
  # their own, kept between runs, from pinned and hashed versions. Ubuntu's
  # python3-venv brings pip into it; without it the venv has none.
  venv_ok=1
  if [[ ! -x /tark/junit-venv/bin/pip ]]; then
    { sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv &&
      rm -rf /tark/junit-venv && python3 -m venv /tark/junit-venv; } >> $log 2>&1 || venv_ok=0
  fi
  (( venv_ok )) && /tark/junit-venv/bin/pip -q install --require-hashes \
    -r $repo/android/aws/jobs/junit-requirements.txt >> $log 2>&1 || venv_ok=0
  if (( ! venv_ok )); then
    echo "junit: could not set up /tark/junit-venv" >> $log
    code=1
  else
    {
      ninja -C $o content_junit_tests chrome_junit_tests &&
      /tark/junit-venv/bin/python $o/bin/run_content_junit_tests --gtest_filter='*SpeechRecognitionImplTest*' &&
      /tark/junit-venv/bin/python $o/bin/run_chrome_junit_tests --gtest_filter='*SpeechLanguageSnackbarTest*:*VoiceDetectionTest*:*VoiceLanguagesTest*:*VoiceLanguageSignalsTest*:*VoiceLanguagesSettingsTest*:*AndroidVoicePlatformTest*:*VoiceSiteLanguagesTest*:*VoiceLanguageOfferTest*' &&
      /tark/junit-venv/bin/python $o/bin/run_chrome_junit_tests --gtest_filter='*IncognitoTabSwitcherPaneUnitTest*' &&
      /tark/junit-venv/bin/python $o/bin/run_chrome_junit_tests --gtest_filter='*ZynclaveAuthFlowTest*:*AuthStateStoreTest*:*ZynclaveAccountTest*:*ZynclaveAccountRowTest*:*ZynclaveNoTokenLogsTest*:*ZynclaveRedirectTest*:*ZynclaveWebOfferTest*' &&
      /tark/junit-venv/bin/python $o/bin/run_chrome_junit_tests --gtest_filter='*TarkMediaPrefsTest*:*TarkLeaveDecisionTest*:*TarkExclusiveAccessPipTest*'
    } > /tark/junit.log 2>&1
    code=$?
    # A filter that matches nothing "passes" with no test run.
    for t in SpeechRecognitionImplTest SpeechLanguageSnackbarTest VoiceDetectionTest VoiceLanguagesTest VoiceLanguageSignalsTest VoiceLanguagesSettingsTest AndroidVoicePlatformTest VoiceSiteLanguagesTest VoiceLanguageOfferTest IncognitoTabSwitcherPaneUnitTest \
        ZynclaveAuthFlowTest AuthStateStoreTest ZynclaveAccountTest ZynclaveAccountRowTest ZynclaveNoTokenLogsTest ZynclaveRedirectTest ZynclaveWebOfferTest \
        TarkMediaPrefsTest TarkLeaveDecisionTest TarkExclusiveAccessPipTest; do
      grep -q "OK \] .*$t\." /tark/junit.log || { echo "junit: no $t test ran" >> $log; code=1; }
    done
    upload /tark/junit.log junit.log
  fi
  echo "junit exit $code" >> $log
fi
exit $code

# Emulator checks

Tools for checking a Tark for Android build on the Mac's emulator (AVD
`tark_a1`, Android 16, arm64). Both default to `emulator-5554` and never act
on a connected phone by accident.

- `walk_settings.py` opens every Settings screen (top level and Privacy and
  security) and exits 1 if any crashes. `--serial S --allow-device` walks a
  phone instead.
- `session.sh TAG` runs A1's network session on a fresh profile and prints
  both checks: `android/check_netlog.sh` (Chromium's net log) and
  `android/pcap_hosts.py` (every DNS lookup on the emulator). Sites the
  session visits (example.com, Wikipedia and Wikimedia, w3schools) show as
  "not allowed"; anything else is a finding.

Before a session: Wi-Fi off and mobile data on (`adb shell svc wifi disable;
adb shell svc data enable`) — with Wi-Fi the emulator's console capture sees
none of the traffic; Play Services and Android's own probes off
(`pm disable-user`, `settings put global captive_portal_mode 0`, private DNS
off, automatic time off); an idle capture of the same emulator saved as
`build/android/sessions/baseline.pcap`.

## Page translation's browser tests

`tark-build.sh` builds `android_browsertests` and uploads
`AndroidBrowserTests.apk` beside the APK. On `emulator-5554` (never the phone):

    adb -s emulator-5554 install -r AndroidBrowserTests.apk
    adb -s emulator-5554 shell am instrument -w \
      -e org.chromium.native_test.NativeTest.CommandLineFlags \
      "--gtest_filter=TarkPageTranslate*" \
      org.chromium.android_browsertests_apk/org.chromium.build.gtest_apk.NativeTestInstrumentationTestRunner

Filter `--gtest_filter=TarkPageTranslate*` (two fixtures). All must run and
pass: TranslatesLocalHindiPageInPlace, ShowOriginalRestoresWithoutReload,
LoadMoreTextTranslated, NoScriptRequestOnNetwork (in both fixtures, the second
with --translate-script-url), HiddenTabDefersThenResumes,
UnparseableBatchStillFinishes, NotInjectedBeforeTap. The instrumentation's
package and runner names are from the build's AndroidManifest.xml; check them
there if `am instrument` can't find the runner.

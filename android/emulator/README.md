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

`TarkPageTranslateBrowserTest` (page-translate-wiring.patch) stays in the
patches but is not built: `android_browsertests` needs `chrome/test/base`,
which does not compile without safe_browsing, and ungoogled removes it. Its
behaviours are checked by hand on `emulator-5554` (never the phone) with the
build's APK and local pages served over `adb reverse`:

- a Hindi page: the offer shows, and Translate translates the page in place;
- Show original restores the text without a reload;
- text added after "finished" (a "load more" button) is translated too;
- a Private tab: translation works and nothing is stored (no download card);
- Settings › Languages › Page translation off: no offer and no menu Translate;
- the net log over load, translate and undo: `android/check_netlog.sh` finds no
  translate script, Google or translate host.

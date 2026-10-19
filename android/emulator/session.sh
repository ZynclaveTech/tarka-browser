#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   android/emulator/session.sh TAG [OUTDIR]
#
# A1's network session on the emulator: install build/android/apk/
# ChromePublic.apk on a fresh profile with the net log on, capture the
# emulator's traffic (use mobile data: with Wi-Fi the console capture sees
# nothing), search twice, open three sites and a video, open Settings, stay
# idle two minutes, then run android/check_netlog.sh and pcap_hosts.py
# (against an idle baseline OUTDIR/baseline.pcap when present).
# TARK_SERIAL picks the emulator (default emulator-5554); a phone is refused:
# the capture comes from the emulator console.
set -uo pipefail
serial="${TARK_SERIAL:-emulator-5554}"
if [[ $serial != emulator-* ]]; then
  echo "$serial is not an emulator: the capture needs the emulator console" >&2
  exit 2
fi
tag="${1:?usage: $0 TAG [OUTDIR]}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="${2:-$root/build/android/sessions}"
mkdir -p "$out"
adbe() { adb -s "$serial" "$@"; }
pkg=com.gettarka.tarka
go() {  # type into the address bar
  adbe shell input tap 444 136; sleep 2; adbe shell input keyevent 67
  adbe shell input text "$1"; adbe shell input keyevent 66; sleep 10
}

adbe install -r "$root/build/android/apk/ChromePublic.apk" | tail -1
adbe shell pm clear $pkg
adbe shell "echo '_ --log-net-log=/data/user/0/$pkg/cache/netlog.json' > /data/local/tmp/chrome-command-line"
adbe logcat -c
adbe emu network capture start "$tag.pcap" >/dev/null
adbe shell monkey -p $pkg -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; sleep 12
adbe exec-out screencap -p > "$out/$tag-1.png"
adbe shell input tap 504 1708; sleep 3                 # notifications prompt: No thanks
go "tark%sbrowser%stest"
adbe shell input tap 761 137; sleep 8                  # a new tab: Shodhya Today
adbe exec-out screencap -p > "$out/$tag-2.png"
go "https://example.com"; go "https://en.wikipedia.org/wiki/India"
go "https://www.w3schools.com/html/mov_bbb.mp4"; adbe shell input tap 538 1238; sleep 10
go "shodhya%ssearch%sengine"
adbe shell am start -n "$pkg/org.chromium.chrome.browser.settings.SettingsActivity" >/dev/null; sleep 5
adbe exec-out screencap -p > "$out/$tag-3.png"
sleep 120
adbe emu network capture stop >/dev/null; sleep 2
avd="$(adbe emu avd name | head -1 | tr -d '\r')"
cp "$HOME/.android/avd/$avd.avd/console_out/$tag.pcap" "$out/$tag.pcap"
adbe shell input keyevent 3; sleep 5; adbe shell am force-stop $pkg; sleep 2
adbe shell cat "/data/user/0/$pkg/cache/netlog.json" > "$out/$tag-netlog.json"
adbe shell rm -f /data/local/tmp/chrome-command-line
adbe logcat -d > "$out/$tag-logcat.txt"
echo "== crashes"; grep -E "Fatal signal|FATAL EXCEPTION" "$out/$tag-logcat.txt" | head -3
# A stopped browser leaves the net log's events array open: close it.
python3 - "$out/$tag-netlog.json" <<'EOF'
import json, sys
t = open(sys.argv[1]).read().rstrip()
try:
    json.loads(t)
except json.JSONDecodeError:
    t = t.rstrip(',').rstrip()
    t = t if t.endswith(']}') else t.rstrip(',') + ']}'
    json.loads(t)
    open(sys.argv[1], 'w').write(t)
EOF
echo "== net log"; bash "$root/android/check_netlog.sh" "$out/$tag-netlog.json"
base=(); [[ -f $out/baseline.pcap ]] && base=(--baseline "$out/baseline.pcap")
echo "== whole device"; python3 "$root/android/pcap_hosts.py" "$out/$tag.pcap" "${base[@]}"

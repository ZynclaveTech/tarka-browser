#!/bin/sh
# Step 2 (phone, live mic). Run by the controller, with the user speaking on cue.
# Usage: run-phone.sh [serial] [modes...]   default: bf678949 pipe normal switch
# Installs out/spike.apk (build with ./build.sh), grants RECORD_AUDIO, runs each mode,
# saves phone-<mode>.log here, then uninstalls com.gettarka.speechspike. Nothing else is changed.
set -u
cd "$(dirname "$0")"
S=${1:-bf678949}; [ $# -gt 0 ] && shift
MODES=${*:-pipe normal switch}
PKG=com.gettarka.speechspike
A="adb -s $S"

$A install -r -g out/spike.apk || exit 1
if ! $A shell pm grant $PKG android.permission.RECORD_AUDIO; then
  echo ">>> pm grant refused. The first mode will show a permission dialog: tap Allow on the phone."
fi

for M in $MODES; do
  case $M in
    pipe)   SAY="hello world this is a test"; NOTE="speak once, within 6 seconds" ;;
    normal) SAY="hello world this is a test"; NOTE="speak once, then stay quiet" ;;
    switch) SAY="hello world this is a test of switching languages"; NOTE="start at once and keep talking slowly for ~5 seconds (the switch happens at 3 s)" ;;
    *) echo "unknown mode $M"; continue ;;
  esac
  echo
  echo "================ MODE: $M ================"
  echo "  Say: \"$SAY\""
  echo "  ($NOTE) -- start speaking when the log shows SPEAK NOW"
  for n in 3 2 1; do echo "  $n..."; sleep 1; done
  $A shell am force-stop $PKG
  $A logcat -c
  $A shell am start -n $PKG/.Main --es mode "$M" >/dev/null
  # Tail until the app logs DONE (or 40 s safety timeout).
  $A logcat -v time -s SpeechSpike:I | tee "phone-$M.log" | {
    while IFS= read -r line; do
      echo "$line"
      case "$line" in *" DONE"*) break ;; esac
    done
  } &
  TP=$!
  i=0; while kill -0 $TP 2>/dev/null && [ $i -lt 40 ]; do sleep 1; i=$((i+1)); done
  kill $TP 2>/dev/null
  pkill -f "adb -s $S logcat -v time -s SpeechSpike" 2>/dev/null
  echo "saved $(pwd)/phone-$M.log"
done

$A shell am force-stop $PKG
$A uninstall $PKG
echo "done; logs: $(ls phone-*.log)"

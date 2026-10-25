#!/bin/sh
# Usage: run.sh <serial> <mode> [lang] [wait_s]  -- runs one spike mode and dumps SPIKE logcat.
S=$1; M=$2; L=${3:-en-US}; W=${4:-15}
adb -s "$S" shell am force-stop com.gettarka.speechspike
adb -s "$S" logcat -c
adb -s "$S" shell am start -W -n com.gettarka.speechspike/.MainActivity --es mode "$M" --es lang "$L" --es end "${END:-close}" --es lang2 "${LANG2:-$L}" >/dev/null
sleep "$W"
adb -s "$S" logcat -d -v time -s SPIKE

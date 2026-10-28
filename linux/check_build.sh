#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   linux/check_build.sh OUT REPORT
#
# L1: the checks after a Linux build, on the build machine, with Tark as
# people get it: unpacked from OUT's tarball. The tarball matches its
# sha256; it holds Tark and the transliteration model; Tark renders
# gettarka.com headless (its own profile); and, under Xvfb, a picture of its
# window. Each check prints `ok NAME` or `FAIL NAME: why` into REPORT/checks.txt;
# any FAIL fails the script.
set -uo pipefail
out=$1; report=$2
rm -rf "$report" && mkdir -p "$report"
txt=$report/checks.txt
fails=0
ok() { echo "ok $1" | tee -a "$txt"; }
fail() { echo "FAIL $1: $2" | tee -a "$txt"; fails=$((fails + 1)); }

tarball=$(ls "$out"/Tark-*-x64-linux.tar.xz 2>/dev/null | head -1)
[[ -n $tarball ]] || { fail tarball "no Tark-*-x64-linux.tar.xz in $out"; exit 1; }
(cd "$out" && sha256sum -c "$(basename "$tarball").sha256" >/dev/null) && ok sha256 || fail sha256 "does not match"

run=$(mktemp -d)
trap 'rm -rf "$run"' EXIT
tar -xJf "$tarball" -C "$run"
app=$(ls -d "$run"/Tark-*/)
for f in tark chrome indicxlit/xlit-model.bin indicxlit/xlit-words.bin; do
  [[ -e $app/$f ]] || fail contents "no $f"
done
grep -q "^FAIL contents" "$txt" || ok contents

profile=$run/profile
timeout 120 "$app/tark" --headless=new --user-data-dir="$profile" --no-first-run \
  --dump-dom https://gettarka.com/ > "$report/headless-dom.html" 2> "$report/headless.log"
if grep -q "Tark" "$report/headless-dom.html"; then ok "headless page"; else fail "headless page" "gettarka.com did not render (headless.log)"; fi
timeout 120 "$app/tark" --headless=new --user-data-dir="$profile" --no-first-run \
  --window-size=1280,800 --screenshot="$report/gettarka-headless.png" https://gettarka.com/ \
  >> "$report/headless.log" 2>&1

# Best effort: Tark's own window, under Xvfb.
if command -v xvfb-run >/dev/null && command -v import >/dev/null; then
  xvfb-run -a -s "-screen 0 1280x800x24" bash -c "
    \"$app/tark\" --user-data-dir=\"$profile-window\" --no-first-run --window-size=1280,800 https://gettarka.com/ &
    sleep 15; import -window root \"$report/window.png\"; kill %1" >> "$report/headless.log" 2>&1 \
    && echo "INFO window picture saved" | tee -a "$txt"
else
  echo "INFO no window picture (needs xvfb and imagemagick)" | tee -a "$txt"
fi
exit $(( fails > 0 ))

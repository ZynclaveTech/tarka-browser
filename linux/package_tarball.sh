#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   linux/package_tarball.sh REPO OUT_DIR DEST
#
# L1: Tark-<chromium>-<revision>-x64-linux.tar.xz from the build's
# out/Default (upstream's scripts/package.sh file list, without chromedriver
# and the AppImage, plus IndicXlit's files), one top folder of the same name
# with a `tark` launcher, and its .sha256 for `sha256sum -c`.
set -euo pipefail
repo=$1; out=$2; dest=$3
chromium=$(cat "$repo/ungoogled-chromium/chromium_version.txt")
revision=$(cat "$repo/revision.txt")
stem="Tark-$chromium-$revision-x64-linux"

files="chrome chrome_100_percent.pak chrome_200_percent.pak chrome_crashpad_handler
chrome-wrapper icudtl.dat libEGL.so libGLESv2.so libqt5_shim.so libqt6_shim.so
libvk_swiftshader.so libvulkan.so.1 locales indicxlit product_logo_48.png
resources.pak v8_context_snapshot.bin vk_swiftshader_icd.json"
# The default-browser helpers: packed when the build made them.
optional="xdg-mime xdg-settings"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/$stem" "$dest"
for f in $files; do
  cp -R "$out/$f" "$stage/$stem/"
done
for f in $optional; do
  [[ -e $out/$f ]] && cp -R "$out/$f" "$stage/$stem/"
done
cat > "$stage/$stem/tark" <<'LAUNCH'
#!/bin/sh
# Starts Tark from wherever this folder was unpacked.
here=$(dirname "$(readlink -f "$0")")
exec "$here/chrome" "$@"
LAUNCH
chmod 755 "$stage/$stem/tark"

rm -f "$dest/$stem.tar.xz" "$dest/$stem.tar.xz.sha256"
COPYFILE_DISABLE=1 tar -C "$stage" -cf - "$stem" | xz -T0 -9 > "$dest/$stem.tar.xz"
python3 - "$dest" "$stem.tar.xz" <<'PY'
import hashlib, pathlib, sys
dest, name = pathlib.Path(sys.argv[1]), sys.argv[2]
h = hashlib.sha256((dest / name).read_bytes()).hexdigest()
(dest / f'{name}.sha256').write_text(f'{h}  {name}\n')
PY
echo "packaged $dest/$stem.tar.xz"

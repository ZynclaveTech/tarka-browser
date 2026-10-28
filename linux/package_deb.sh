#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   linux/package_deb.sh REPO APP_DIR SRC DEST
#
# L3: tark_<chromium>-<revision>_amd64.deb from the tarball's folder APP_DIR:
# Tark in /opt/tark with a launcher that names its desktop entry, a `tark`
# command, the app menu entry and Tark's icons (SRC's branded product logos),
# the AppArmor profile Ubuntu 23.10+ needs for Chromium's sandbox, and
# linux/deb's maintainer scripts. Depends comes from dpkg-shlibdeps on the
# build machine (TARK_DEB_DEPENDS stands in for it in tests).
set -euo pipefail
repo=$1; app=${2%/}; src=$3; dest=$4
chromium=$(cat "$repo/ungoogled-chromium/chromium_version.txt")
revision=$(cat "$repo/revision.txt")
version="$chromium-$revision"
deb=$(dirname "$0")/deb

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
root=$stage/root
mkdir -p "$root/opt/tark" "$root/usr/bin" "$root/usr/share/applications" "$root/etc/apparmor.d" "$root/DEBIAN"
cp -R "$app/." "$root/opt/tark/"
cat > "$root/opt/tark/tark" <<'LAUNCH'
#!/bin/sh
# Starts Tark; CHROME_DESKTOP names the app menu entry Tark checks when it is
# asked to be the default browser.
export CHROME_DESKTOP=tark.desktop
exec /opt/tark/chrome "$@"
LAUNCH
chmod 755 "$root/opt/tark/tark"
ln -s /opt/tark/tark "$root/usr/bin/tark"
install -m 644 "$deb/tark.desktop" "$root/usr/share/applications/tark.desktop"
install -m 644 "$deb/apparmor" "$root/etc/apparmor.d/tark"
for size in 16 24 48 64 128 256; do
  mkdir -p "$root/usr/share/icons/hicolor/${size}x${size}/apps"
  install -m 644 "$src/chrome/app/theme/chromium/product_logo_$size.png" \
    "$root/usr/share/icons/hicolor/${size}x${size}/apps/tark.png"
done
install -m 755 "$deb/postinst" "$root/DEBIAN/postinst"
install -m 755 "$deb/postrm" "$root/DEBIAN/postrm"
echo /etc/apparmor.d/tark > "$root/DEBIAN/conffiles"

if [[ -n ${TARK_DEB_DEPENDS:-} ]]; then
  depends=$TARK_DEB_DEPENDS
else
  mkdir -p "$stage/debian" && touch "$stage/debian/control"
  depends=$(cd "$stage" && dpkg-shlibdeps -O -e"$root/opt/tark/chrome" -e"$root/opt/tark/libonnxruntime.so.1" 2>/dev/null \
    | sed -n 's/^shlibs:Depends=//p')
fi
size=$(du -sk "$root" | cut -f1)
cat > "$root/DEBIAN/control" <<CONTROL
Package: tark
Version: $version
Architecture: amd64
Maintainer: Zynclave Tech Private Limited <support@zynclave.com>
Installed-Size: $size
Depends: $depends, xdg-utils, ca-certificates
Section: web
Priority: optional
Homepage: https://gettarka.com/
Description: Tark, a browser that speaks your language and keeps to itself
 Type in Hindi, Tamil or Bengali with English letters, live captions for any
 video or call, ads blocked, no account needed, nothing sent home.
CONTROL

mkdir -p "$dest"
out="$dest/tark_${version}_amd64.deb"
dpkg-deb --root-owner-group -Zxz --build "$root" "$out" >/dev/null
echo "packaged $out"

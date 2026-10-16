#!/usr/bin/env bash
# Renders resources/branding/app-icon.svg into resources/branding/app.icns,
# the macOS application icon Chromium's bundle uses. Needs rsvg-convert
# (brew install librsvg); sips and iconutil ship with macOS.
set -euo pipefail

_root_dir="$(dirname "$(dirname "$(greadlink -f "${BASH_SOURCE[0]}")")")"
_svg="$_root_dir/resources/branding/app-icon.svg"
_out="$_root_dir/resources/branding/app.icns"
_tmp="$(mktemp -d)"
_set="$_tmp/Tarka.iconset"
mkdir -p "$_set"

rsvg-convert -w 1024 -h 1024 "$_svg" -o "$_tmp/1024.png"
for n in 16 32 128 256 512; do
  sips -z "$n" "$n" "$_tmp/1024.png" --out "$_set/icon_${n}x${n}.png" >/dev/null
  double=$((n * 2))
  sips -z "$double" "$double" "$_tmp/1024.png" --out "$_set/icon_${n}x${n}@2x.png" >/dev/null
done
iconutil -c icns "$_set" -o "$_out"
echo "wrote $_out"

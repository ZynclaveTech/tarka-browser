# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Sourced by dev.sh (setup) and build.sh; defines _install_xlit (D1, on-device
# transliteration). The caller sets _root_dir, _src_dir, _main_repo and
# _download_cache. _xlit_ini overrides the downloads file (the tests point it
# at file:// stand-ins).
#
# It fetches IndicXlit's checkpoint and two dictionaries (about 138 MB, kept in
# the download cache), converts them to the TXLM blob, packs the word lists,
# and puts the licence files and the golden test data where the build wants
# them. Retrieve only: downloads.py unpack would try to extract the .pt, which
# is a zip.

_install_xlit() {
  local ini="${_xlit_ini:-$_root_dir/downloads-xlit.ini}"
  local cache="$_download_cache"
  local third_party="$_src_dir/third_party/indicxlit"
  local test_data="$_src_dir/components/tark_xlit/test/data"

  python3 "$_main_repo/utils/downloads.py" retrieve -i "$ini" -c "$cache"

  mkdir -p "$third_party" "$test_data"
  python3 "$_root_dir/utils/xlit_convert.py" \
    --checkpoint "$cache/indicxlit-e7049fe.pt" \
    --src-dict "$cache/indicxlit-e7049fe-dict.en.txt" \
    --tgt-dict "$cache/indicxlit-e7049fe-dict.hi.txt" \
    "$third_party/xlit-model.bin"
  python3 "$_root_dir/utils/xlit_wordlist.py" pack \
    "$_root_dir/resources/xlit/words" "$_root_dir/resources/xlit/english-common.txt.xz" \
    "$third_party/xlit-words.bin"

  # about:credits lists IndicXlit from these.
  cp "$_root_dir/resources/indicxlit/README.chromium" "$_root_dir/resources/indicxlit/LICENSE" "$third_party/"
  cp "$third_party/xlit-model.bin" "$third_party/xlit-words.bin" \
    "$_root_dir/resources/xlit/golden.tsv" "$_root_dir/resources/xlit/golden-inputs.txt" "$test_data/"
}

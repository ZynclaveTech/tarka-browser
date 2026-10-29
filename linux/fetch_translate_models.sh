#!/bin/bash
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
#   linux/fetch_translate_models.sh SRC DIR
#
# Fetches the page translation models (the to_english and from_english
# units: it2_indic_en/, it2_en_indic/) into DIR as Tark fetches them, each
# file sha256-checked against the manifest compiled into Tark
# (SRC/components/tark_captions/model_manifest.cc). Exits 1 on any miss.
set -uo pipefail
src=$1; dir=$2
mkdir -p "$dir"
while read -r path sha; do
  mkdir -p "$dir/$(dirname "$path")"
  curl -sSfL -o "$dir/$path" "https://gettarka.com/models/captions/v1/$path" || exit 1
  echo "$sha  $dir/$path" | sha256sum -c --quiet || exit 1
done < <(python3 - "$src/components/tark_captions/model_manifest.cc" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
for unit in ('kToEnglishFiles', 'kFromEnglishFiles'):
    block = text[text.index(unit):]
    block = block[:block.index('};')]
    for path, sha in re.findall(r'\{"([^"]+)",\s*\d+,\s*"([0-9a-f]{64})"\}', block):
        print(path, sha)
PY
)
[[ -d $dir/it2_indic_en && -d $dir/it2_en_indic ]]

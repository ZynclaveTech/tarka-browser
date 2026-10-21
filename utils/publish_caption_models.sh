#!/bin/bash
# Publishes Tark's live caption and translation models to
# https://gettarka.com/models/captions/v1/ (D4 Phase 4).
#
#   utils/publish_caption_models.sh [--dry-run] MODELS_DIR
#
# 1. Checks MODELS_DIR against the manifest compiled into Tark
#    (components/tark_captions/model_manifest.cc); stops on any difference.
# 2. Uploads each file once, immutable, with its SHA-256 as metadata. v1 never
#    changes: a file already there with another hash stops the run (new models
#    go to v2 with a new manifest).
# 3. Reads every file back through CloudFront and compares its SHA-256.
# --dry-run prints the uploads and checks instead of running them.
set -euo pipefail

BUCKET=tark-site-967555169405   # gettarka-site/publish.sh
PREFIX=models/captions/v1
BASE=https://gettarka.com/$PREFIX
here=$(cd "$(dirname "$0")" && pwd)
manifest=${TARK_CAPTIONS_MANIFEST_CC:-$here/../build/src/components/tark_captions/model_manifest.cc}

dry=0
if [[ ${1:-} == --dry-run ]]; then dry=1; shift; fi
models=${1:?usage: publish_caption_models.sh [--dry-run] MODELS_DIR}

python3 "$here/captions_manifest.py" --check "$models" "$manifest"

content_type() {
  case $1 in
    *.json) echo application/json ;;
    *.txt) echo text/plain ;;
    *) echo application/octet-stream ;;
  esac
}

rows=$(grep -oE '\{"[^"]+", [0-9]+, "[0-9a-f]{64}"\}' "$manifest" | sed -E 's/^\{"([^"]+)", [0-9]+, "([0-9a-f]+)"\}$/\1 \2/')
[[ -n $rows ]] || { echo "no files in $manifest" >&2; exit 1; }

while read -r path sha; do
  cmd=(aws s3 cp "$models/$path" "s3://$BUCKET/$PREFIX/$path"
       --content-type "$(content_type "$path")"
       --cache-control "public, max-age=31536000, immutable"
       --metadata "sha256=$sha")
  if (( dry )); then echo "${cmd[*]}"; continue; fi
  there=$(aws s3api head-object --bucket $BUCKET --key "$PREFIX/$path" \
            --query Metadata.sha256 --output text 2>/dev/null || true)
  if [[ $there == "$sha" ]]; then echo "already there: $path"; continue; fi
  if [[ -n $there ]]; then
    echo "$PREFIX/$path is already published with another hash ($there); v1 never changes" >&2
    exit 1
  fi
  "${cmd[@]}"
done <<< "$rows"

bad=0
while read -r path sha; do
  if (( dry )); then echo "verify $BASE/$path $sha"; continue; fi
  got=$(curl -sfL --retry 3 "$BASE/$path" | shasum -a 256 | cut -d' ' -f1)
  if [[ $got == "$sha" ]]; then echo "ok $path"; else echo "MISMATCH $path: $got" >&2; bad=1; fi
done <<< "$rows"
exit $bad

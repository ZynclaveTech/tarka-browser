#!/bin/bash
# Publishes Tark for Android's live caption models to
# https://gettarka.com/models/android/v1/<sha256>.bin (Phase 1), the URLs every
# APK pins (android/captions/files.json, compiled in as model_files.inc).
#
#   android/captions/publish.sh [--dry-run] MODELS_DIR
#
# MODELS_DIR is android/captions/models.py build's output. Like
# utils/publish_caption_models.sh (the Mac's):
# 1. Checks every file in MODELS_DIR against files.json (size and sha256);
#    stops on any difference.
# 2. Uploads each file once, immutable, named by its sha256, with the sha256
#    as metadata. A key already there with another hash stops the run.
# 3. Reads every file back through CloudFront and compares its sha256.
# gettarka-site/publish.sh leaves models/ alone (--delete excludes it).
set -euo pipefail

BUCKET=tark-site-967555169405   # gettarka-site/publish.sh
PREFIX=models/android/v1
BASE=https://gettarka.com/$PREFIX
here=$(cd "$(dirname "$0")" && pwd)

dry=0
if [[ ${1:-} == --dry-run ]]; then dry=1; shift; fi
models=${1:?usage: publish.sh [--dry-run] MODELS_DIR}

# "<file> <sha256> <size>" for each pinned file, after checking MODELS_DIR.
rows=$(python3 - "$here/files.json" "$models" <<'PY'
import hashlib, json, pathlib, sys
table = json.loads(pathlib.Path(sys.argv[1]).read_text())
models = pathlib.Path(sys.argv[2])
bad = 0
for name, f in sorted(table.items()):
    path = models / name
    data = path.read_bytes() if path.exists() else b''
    if len(data) != f['size'] or hashlib.sha256(data).hexdigest() != f['sha256']:
        print(f'{name}: not the pinned file', file=sys.stderr)
        bad = 1
    print(name, f['sha256'], f['size'])
sys.exit(bad)
PY
)
[[ -n $rows ]] || { echo "no files" >&2; exit 1; }

while read -r name sha size; do
  cmd=(aws s3 cp "$models/$name" "s3://$BUCKET/$PREFIX/$sha.bin"
       --content-type application/octet-stream
       --cache-control "public, max-age=31536000, immutable"
       --metadata "sha256=$sha")
  if (( dry )); then echo "${cmd[*]}"; continue; fi
  there=$(aws s3api head-object --bucket $BUCKET --key "$PREFIX/$sha.bin" \
            --query Metadata.sha256 --output text 2>/dev/null || true)
  if [[ $there == "$sha" ]]; then echo "already there: $name"; continue; fi
  if [[ -n $there ]]; then
    echo "$PREFIX/$sha.bin is already published with another hash ($there)" >&2
    exit 1
  fi
  "${cmd[@]}" --only-show-errors
  echo "uploaded $name"
done <<< "$rows"

bad=0
while read -r name sha size; do
  if (( dry )); then echo "verify $BASE/$sha.bin ($name)"; continue; fi
  got=$(curl -sf --retry 5 --retry-all-errors "$BASE/$sha.bin" | shasum -a 256 | cut -d' ' -f1)
  if [[ $got == "$sha" ]]; then echo "ok $name"; else echo "MISMATCH $name: $got" >&2; bad=1; fi
done <<< "$rows"
exit $bad

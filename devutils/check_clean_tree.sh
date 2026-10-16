#!/usr/bin/env bash
# Refuses to let build.sh run on top of a development tree. build.sh
# re-extracts the tarball and re-applies patches with patches.py, which
# assumes a fresh build/src and an unmerged patches/series. Run
# ./dev.sh reset first.
set -euo pipefail
_root_dir="$(dirname "$(dirname "$(greadlink -f "${BASH_SOURCE[0]}")")")"
_problems=()
[[ -e "$_root_dir/patches/series.merged" ]] && _problems+=("patches/series.merged exists (run ./devutils/update_patches.sh unmerge, or ./dev.sh reset)")
[[ -e "$_root_dir/build/namesubs.tar" ]] && _problems+=("build/namesubs.tar exists (a dev tree's name substitution; run ./dev.sh reset)")
[[ -d "$_root_dir/build/src/.pc" ]] && _problems+=("build/src/.pc exists (a quilt-managed dev tree; run ./dev.sh reset)")
if (( ${#_problems[@]} )); then
  printf 'build.sh needs a clean tree:\n' >&2
  printf '  - %s\n' "${_problems[@]}" >&2
  exit 1
fi

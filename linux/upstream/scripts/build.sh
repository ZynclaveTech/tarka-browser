#!/bin/bash
set -euo pipefail

clone=false
use_gentoo_source_tar=false
if [[ "${1:-}" == "-c" ]]; then
    clone=true
elif [[ "${1:-}" == "-g" ]]; then
    use_gentoo_source_tar=true
fi

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)/shared.sh"

setup_paths

# clean out/ directory before build
rm -rf "${_src_dir}/out" || true

fetch_sources "$clone" "$use_gentoo_source_tar"
apply_patches
apply_domsub
# Tark (local change to upstream, see linux/README.md): Tark's own steps after
# patching and domain substitution.
if [ ! -f "${_src_dir}/.tark.stamp" ]; then
    python3 "${_root}/tark_post_patch.py" "${_src_dir}"
    touch "${_src_dir}/.tark.stamp"
fi
# ONNX Runtime's headers on every build: a tree kept from before Tark's steps
# installed them skips those steps.
python3 "${_root}/tark_post_patch.py" --onnxruntime-only "${_src_dir}"
write_gn_args
fix_tool_downloading
setup_toolchain
gn_gen
maybe_build

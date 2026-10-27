#!/usr/bin/env bash
# Builds and runs the desktop Zynclave sign-in unit tests in the Mac dev tree
# (build/src, from ./dev.sh setup). Extra arguments go to the test binary,
# e.g. --gtest_filter=TarkZynclaveIdToken.*
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/build/src/out/Default"
export PATH="/opt/homebrew/opt/python@3.13/libexec/bin:$PATH"
ninja -C "$out" -j "${TARKA_JOBS:-8}" tark_zynclave_unittests
"$out/tark_zynclave_unittests" "$@"

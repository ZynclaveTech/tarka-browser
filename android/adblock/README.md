# Ad blocking (A2)

Tark for Android blocks ads with Brave's adblock-rust inside the browser
(spec §4). This folder holds what is not browser code:

- `bundle.py` builds the list bundle: every list from spec §4 as text
  (`!#if` evaluated as uBO does on Chromium for Android, `!#include`
  inlined), uBlock Origin's redirect resources and scriptlets as
  adblock-rust Resources, and a manifest. `sign`/`verify` handle
  `latest.json` (Ed25519 over the zip's bytes, `ed25519.py`, RFC 8032's
  reference code). `keygen` makes a signing key (never printed, mode 600).
- `scriptlets.mjs` turns uBO's scriptlet module into Resources (as Brave's
  crx packager does); `requiresTrust` scriptlets get permission 1.
- `listtool/` (Rust, the browser's adblock-rust 0.13.3): `resources`
  assembles uBO's redirect resources; `check` compiles a bundle and checks
  `canaries.txt` — a bundle that fails is never published.

    cargo build --release --manifest-path android/adblock/listtool/Cargo.toml
    python3 android/adblock/bundle.py build --out build/adblock
    android/adblock/listtool/target/release/listtool check build/adblock/lists-*.zip android/adblock/canaries.txt

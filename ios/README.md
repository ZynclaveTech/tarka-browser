# Tark for iPhone and iPad

Tark for iOS is Firefox for iOS (MPL-2.0) with Tark's patches. In India every
iOS browser must use WebKit, so this is not a Chromium build.

- `upstream.json`: the pinned firefox-ios tag and commit.
- `series`, `patches/`: Tark's changes, applied in order.
- `build.py fetch | patch | sim`: clone the tag into `build/ios/firefox-ios`,
  apply the series, bootstrap and build the Fennec scheme for the simulator
  (`build/ios/dd`).

Builds with Xcode 26.4.1 although firefox-v159.0 names 26.5.

## Nothing sent home

`netcheck.sh DEVICE SECONDS` lists the outside addresses the app's own
process connects to after a fresh install; idle, it must list none. Debug
builds log every URLSession host as `TarkNet allow|block host`. Rust
components (viaduct) do not use URLSession: they are switched off where they
start (`services-off.patch`), and Remote Settings points at a closed local
port.

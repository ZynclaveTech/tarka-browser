# Tark for iPhone and iPad

Tark for iOS is Firefox for iOS (MPL-2.0) with Tark's patches. In India every
iOS browser must use WebKit, so this is not a Chromium build.

- `upstream.json`: the pinned firefox-ios tag and commit.
- `series`, `patches/`: Tark's changes, applied in order.
- `build.py fetch | patch | lists | engine | sim`: clone the tag into `build/ios/firefox-ios`,
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

## Ads blocked

`build.py lists` downloads the signed list bundle Tark for Android uses
(gettarka.com/lists/android/v1/), verifies it with `lists_pubkey.txt`, and
converts its network rules to WebKit content-blocker rules with
`listtool webkit` (adblock-rust's conversion, as Brave does for iOS). The
rules ship in the app as `fxcb-tark-N.json` and apply in Standard mode.
Hide rules and scriptlets are not in WebKit's rules; adblock-rust runs in
the app for them, as Brave does on iOS: `adblock/` is the same adblock-rust
Tark for Android ships, behind a C interface, which `build.py engine` builds
into `BrowserKit/TarkAdblockFFI.xcframework`. `build.py lists` also writes
the engine (`listtool engine`: `tark-engine.dat`, `tark-resources.json`).
A script in Firefox's isolated client world asks for each page's hide rules
and scriptlets and reports the class and id names it sees; the engine
answers with generic hide rules minus the page's exceptions
(`adblock-cosmetic.patch`). uBlock exempts localhost and bare IP addresses
from generic hiding, so check that on a real site. `adtest/index.html` checks blocking: serve it with
`python3 -m http.server 8765 --bind 127.0.0.1` and type the address into
Tark — `simctl openurl` opens http links in Safari, not Tark.

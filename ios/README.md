# Tark for iPhone and iPad

Tark for iOS is Firefox for iOS (MPL-2.0) with Tark's patches. In India every
iOS browser must use WebKit, so this is not a Chromium build.

- `upstream.json`: the pinned firefox-ios tag and commit.
- `series`, `patches/`: Tark's changes, applied in order.
- `build.py fetch | patch | sim`: clone the tag into `build/ios/firefox-ios`,
  apply the series, bootstrap and build the Fennec scheme for the simulator
  (`build/ios/dd`).

Builds with Xcode 26.4.1 although firefox-v159.0 names 26.5.

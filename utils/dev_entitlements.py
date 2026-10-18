#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The app entitlements for development signing (S1).

    python3 utils/dev_entitlements.py BASE.plist PROFILE.provisionprofile BUNDLE_ID OUT.plist

Adds to the app's own entitlements what Touch ID passkeys need: the
application identifier and team from the provisioning profile, and the
keychain group <team>.<bundle id>.webauthn that Chromium's Touch ID
authenticator uses (chrome_web_authentication_delegate.cc). Refuses a
profile made for another app or one whose keychain groups do not allow it.
"""

import fnmatch
import plistlib
import subprocess
import sys


def read_profile(path):
    """The provisioning profile's plist, decoded from its CMS envelope."""
    decoded = subprocess.run(['security', 'cms', '-D', '-i', path],
                             check=True, capture_output=True).stdout
    return plistlib.loads(decoded)


def merge(base_plist, profile, bundle_id):
    team = profile['TeamIdentifier'][0]
    granted = profile['Entitlements']
    app_id = granted['com.apple.application-identifier']
    if app_id != f'{team}.{bundle_id}':
        raise ValueError(f'the profile is for {app_id}, not {team}.{bundle_id}')
    group = f'{team}.{bundle_id}.webauthn'
    if not any(fnmatch.fnmatchcase(group, allowed)
               for allowed in granted.get('keychain-access-groups', [])):
        raise ValueError(f'the profile does not allow the keychain group {group}')
    entitlements = plistlib.loads(base_plist)
    entitlements['com.apple.application-identifier'] = app_id
    entitlements['com.apple.developer.team-identifier'] = team
    entitlements['keychain-access-groups'] = [group]
    return plistlib.dumps(entitlements)


def main():
    if len(sys.argv) != 5:
        sys.exit('usage: dev_entitlements.py BASE.plist PROFILE BUNDLE_ID OUT.plist')
    base, profile, bundle_id, out = sys.argv[1:]
    with open(base, 'rb') as f:
        merged = merge(f.read(), read_profile(profile), bundle_id)
    with open(out, 'wb') as f:
        f.write(merged)


if __name__ == '__main__':
    main()

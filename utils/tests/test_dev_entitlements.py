"""S1: development signing adds the entitlements Touch ID passkeys need to
the app's own entitlements, from the provisioning profile's team."""
import pathlib
import plistlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dev_entitlements  # noqa: E402

BASE = plistlib.dumps({'com.apple.security.device.camera': True})
PROFILE = {
    'TeamIdentifier': ['UMTJNNPK6C'],
    'Entitlements': {
        'com.apple.application-identifier': 'UMTJNNPK6C.com.gettarka.Tarka',
        'keychain-access-groups': ['UMTJNNPK6C.*'],
        'com.apple.developer.team-identifier': 'UMTJNNPK6C',
    },
}


def test_adds_team_application_id_and_webauthn_group():
    got = plistlib.loads(dev_entitlements.merge(BASE, PROFILE, 'com.gettarka.Tarka'))
    assert got['com.apple.security.device.camera'] is True
    assert got['com.apple.application-identifier'] == 'UMTJNNPK6C.com.gettarka.Tarka'
    assert got['com.apple.developer.team-identifier'] == 'UMTJNNPK6C'
    assert got['keychain-access-groups'] == ['UMTJNNPK6C.com.gettarka.Tarka.webauthn']


def test_profile_for_another_app_is_refused():
    other = dict(PROFILE, Entitlements=dict(PROFILE['Entitlements'], **{
        'com.apple.application-identifier': 'UMTJNNPK6C.com.example.Other'}))
    try:
        dev_entitlements.merge(BASE, other, 'com.gettarka.Tarka')
    except ValueError as error:
        assert 'com.example.Other' in str(error)
    else:
        raise AssertionError('a profile for another app was accepted')


def test_group_outside_the_profile_is_refused():
    narrow = dict(PROFILE, Entitlements=dict(PROFILE['Entitlements'], **{
        'keychain-access-groups': ['UMTJNNPK6C.com.gettarka.Tarka.other']}))
    try:
        dev_entitlements.merge(BASE, narrow, 'com.gettarka.Tarka')
    except ValueError as error:
        assert 'webauthn' in str(error)
    else:
        raise AssertionError('a keychain group the profile does not allow was accepted')

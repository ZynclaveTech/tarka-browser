"""Tests for utils/package_dmg.sh, the DMG step of sign_and_package_app.sh (M5).

A tiny ad-hoc-signed app stands in for Tark.app. It carries the detritus
that pkg-dmg's HFS hybrid used to add (com.apple.FinderInfo), so the test
proves the packager never ships it.
"""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'package_dmg.sh')
FINDER_INFO = '00000000000000000000FFFFFFFF0000' + '00' * 16


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def make_app(root):
    app = os.path.join(root, 'Dummy.app')
    macos = os.path.join(app, 'Contents', 'MacOS')
    helpers = os.path.join(app, 'Contents', 'Helpers')
    os.makedirs(macos)
    os.makedirs(helpers)
    shutil.copy('/bin/echo', os.path.join(macos, 'Dummy'))
    shutil.copy('/bin/echo', os.path.join(helpers, 'helper'))
    with open(os.path.join(app, 'Contents', 'Info.plist'), 'wb') as f:
        plistlib.dump({'CFBundleExecutable': 'Dummy',
                       'CFBundleIdentifier': 'com.gettarka.test.dummy',
                       'CFBundlePackageType': 'APPL'}, f)
    for path in (os.path.join(helpers, 'helper'), app):
        signed = run('codesign', '--sign', '-', '--force', path)
        assert signed.returncode == 0, signed.stderr
    return app


def attach(dmg):
    out = run('hdiutil', 'attach', '-nobrowse', '-readonly', dmg)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1].split('\t')[-1]


@unittest.skipUnless(sys.platform == 'darwin', 'needs hdiutil and codesign')
class TestPackageDmg(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.app = make_app(self.tmp)
        self.dmg = os.path.join(self.tmp, 'out', 'Dummy.dmg')
        os.makedirs(os.path.dirname(self.dmg))

    def test_dmg_app_has_no_finder_info_and_verifies(self):
        # The source app carries detritus, as an app copied off pkg-dmg's
        # image did; the DMG must not.
        helper = os.path.join(self.app, 'Contents', 'Helpers', 'helper')
        run('xattr', '-wx', 'com.apple.FinderInfo', FINDER_INFO, helper)
        result = run('bash', SCRIPT, self.app, self.dmg)
        self.assertEqual(result.returncode, 0, result.stderr)
        mount = attach(self.dmg)
        self.addCleanup(run, 'hdiutil', 'detach', '-quiet', mount)
        app = os.path.join(mount, 'Dummy.app')
        found = run('find', app, '-xattrname', 'com.apple.FinderInfo')
        self.assertEqual(found.stdout.strip(), '')
        verify = run('codesign', '--verify', '--deep', '--strict', app)
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertEqual(os.readlink(os.path.join(mount, 'Applications')), '/Applications')

    def test_broken_signature_fails_and_leaves_no_dmg(self):
        with open(os.path.join(self.app, 'Contents', 'Info.plist'), 'ab') as f:
            f.write(b'\n')
        result = run('bash', SCRIPT, self.app, self.dmg)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(self.dmg))

    def test_volume_is_named_after_the_app(self):
        result = run('bash', SCRIPT, self.app, self.dmg)
        self.assertEqual(result.returncode, 0, result.stderr)
        mount = attach(self.dmg)
        self.addCleanup(run, 'hdiutil', 'detach', '-quiet', mount)
        self.assertTrue(os.path.basename(mount).startswith('Dummy'))


if __name__ == '__main__':
    unittest.main()

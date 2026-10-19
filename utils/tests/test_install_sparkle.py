"""Tests for utils/install_sparkle.sh, the updater step of sign_and_package_app.sh (M5).

A stand-in app and a stand-in Sparkle.framework (the real layout: Versions/B
with Autoupdate, Updater.app and XPCServices, and top-level symlinks).
"""
import os
import plistlib
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'install_sparkle.sh')
KEY = 'jifHjeHnUyao+9lgJ+TZ/mDQuNhOmXw/gNfI7uJKmQk='


def make_sparkle(root):
    fw = os.path.join(root, 'Sparkle.framework')
    b = os.path.join(fw, 'Versions', 'B')
    for d in ('Updater.app/Contents/MacOS', 'XPCServices/Installer.xpc', 'Resources'):
        os.makedirs(os.path.join(b, d))
    for f in ('Sparkle', 'Autoupdate'):
        open(os.path.join(b, f), 'w').close()
    os.symlink('B', os.path.join(fw, 'Versions', 'Current'))
    for name in ('Sparkle', 'Autoupdate', 'Updater.app', 'XPCServices', 'Resources'):
        os.symlink(os.path.join('Versions', 'Current', name), os.path.join(fw, name))
    return fw


def make_app(root):
    app = os.path.join(root, 'Tark.app')
    os.makedirs(os.path.join(app, 'Contents', 'Frameworks'))
    with open(os.path.join(app, 'Contents', 'Info.plist'), 'wb') as f:
        plistlib.dump({'CFBundleVersion': '8059.39',
                       'CFBundleShortVersionString': '155.0.8059.39'}, f)
    return app


def make_src(root):
    src = os.path.join(root, 'src', 'chrome')
    os.makedirs(src)
    with open(os.path.join(src, 'VERSION'), 'w') as f:
        f.write('MAJOR=155\nMINOR=0\nBUILD=8059\nPATCH=39\n')
    return os.path.join(root, 'src')


class TestInstallSparkle(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.sparkle = make_sparkle(self.root)
        self.app = make_app(self.root)
        self.src = make_src(self.root)

    def run_script(self, revision='1', feed=None):
        env = dict(os.environ)
        if feed:
            env['TARKA_SPARKLE_FEED_URL'] = feed
        return subprocess.run(['bash', SCRIPT, self.app, self.sparkle, self.src, revision],
                              capture_output=True, text=True, env=env)

    def plist(self):
        with open(os.path.join(self.app, 'Contents', 'Info.plist'), 'rb') as f:
            return plistlib.load(f)

    def test_framework_copied_without_xpc_services(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        fw = os.path.join(self.app, 'Contents', 'Frameworks', 'Sparkle.framework')
        self.assertTrue(os.path.isfile(os.path.join(fw, 'Versions', 'B', 'Autoupdate')))
        self.assertTrue(os.path.isdir(os.path.join(fw, 'Versions', 'B', 'Updater.app')))
        self.assertFalse(os.path.lexists(os.path.join(fw, 'XPCServices')))
        self.assertFalse(os.path.lexists(os.path.join(fw, 'Versions', 'B', 'XPCServices')))
        self.assertTrue(os.path.islink(os.path.join(fw, 'Versions', 'Current')))

    def test_update_keys(self):
        self.assertEqual(self.run_script().returncode, 0)
        p = self.plist()
        self.assertEqual(p['SUFeedURL'], 'https://gettarka.com/appcast.xml')
        self.assertEqual(p['SUPublicEDKey'], KEY)
        self.assertIs(p['SUEnableAutomaticChecks'], True)
        self.assertEqual(p['SUScheduledCheckInterval'], 86400)
        self.assertIs(p['SUEnableSystemProfiling'], False)
        self.assertIs(p['SUAllowsAutomaticUpdates'], True)
        # Updates install by themselves when Tark quits, as Chrome's do; the
        # user can still turn this off in Sparkle's update prompt.
        self.assertIs(p['SUAutomaticallyUpdate'], True)
        self.assertEqual(p['CFBundleShortVersionString'], '155.0.8059.39')

    def test_bundle_version_carries_the_revision_and_is_idempotent(self):
        self.assertEqual(self.run_script('3').returncode, 0)
        self.assertEqual(self.plist()['CFBundleVersion'], '8059.39.3')
        self.assertEqual(self.run_script('3').returncode, 0)
        self.assertEqual(self.plist()['CFBundleVersion'], '8059.39.3')

    def test_feed_url_override_for_tests(self):
        self.assertEqual(self.run_script(feed='http://localhost:8766/appcast.xml').returncode, 0)
        self.assertEqual(self.plist()['SUFeedURL'], 'http://localhost:8766/appcast.xml')

    def test_missing_framework_fails(self):
        self.sparkle = os.path.join(self.root, 'nowhere', 'Sparkle.framework')
        self.assertNotEqual(self.run_script().returncode, 0)


if __name__ == '__main__':
    unittest.main()

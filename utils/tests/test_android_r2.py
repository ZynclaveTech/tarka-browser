"""Tark for Android r2: the A5 review's stale update offer, the screen-sharing
foreground service Tark cannot use, and Tark's mark on the media
notification."""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATCHES = ROOT / 'android' / 'patches'


def added(patch):
    return '\n'.join(l[1:] for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++'))


def removed(patch):
    return '\n'.join(l[1:] for l in patch.splitlines() if l.startswith('-') and not l.startswith('---'))


def series():
    return [l for l in (PATCHES / 'series').read_text().split() if not l.startswith('#')]


class TestOfferWithdrawn(unittest.TestCase):
    """A check that finds no newer version clears an offer an earlier check
    stored, so a pulled release stops being offered."""

    def setUp(self):
        self.added = added((PATCHES / 'update-check.patch').read_text())

    def test_java_clears_the_stored_offer(self):
        self.assertIn('static void withdraw() {', self.added)
        for key in ('KEY_CODE', 'KEY_NAME', 'KEY_URL'):
            self.assertIn(f'.remove({key})', self.added)

    def test_native_withdraws_when_not_newer(self):
        cc = self.added[self.added.index('void UpdateCheckService::OnFetched'):]
        not_newer = cc[cc.index('if (!IsNewer('):cc.index('LOG(WARNING) << "tark update: " << index->version_name')]
        self.assertIn('Java_TarkUpdate_withdraw(env);', not_newer)

    def test_e2e_case(self):
        run = (ROOT / 'android' / 'update' / 'e2e' / 'run.py').read_text()
        self.assertIn('def case_withdrawn(', run)


class TestNoScreenSharingService(unittest.TestCase):
    """Websites can't share the screen in Tark for Android
    (navigator.mediaDevices.getDisplayMedia is undefined), so the capture
    service doesn't declare or ask for the media projection type."""

    def setUp(self):
        self.patch = (PATCHES / 'media-no-projection.patch').read_text()

    def test_in_the_series(self):
        self.assertGreater(series().index('media-no-projection.patch'), series().index('update-check.patch'))

    def test_manifest(self):
        self.assertIn('+++ b/chrome/android/java/AndroidManifest.xml', self.patch)
        self.assertIn('android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION', removed(self.patch))
        self.assertIn('android:foregroundServiceType="camera|microphone|mediaProjection|mediaPlayback"',
                      removed(self.patch))
        self.assertNotIn('mediaProjection', added(self.patch))
        self.assertNotIn('MEDIA_PROJECTION', added(self.patch))

    def test_the_service_never_asks_for_it(self):
        self.assertIn('+++ b/chrome/android/java/src/org/chromium/chrome/browser/media/'
                      'MediaCaptureNotificationServiceImpl.java', self.patch)
        self.assertEqual(removed(self.patch).count('ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION'), 2)


class TestMediaNotificationMark(unittest.TestCase):
    """The media notification's small icon is Tark's three dots, not
    Chrome's logo."""

    def setUp(self):
        self.patch = (PATCHES / 'look-media-icon.patch').read_text()

    def test_in_the_series(self):
        self.assertIn('look-media-icon.patch', series())

    def test_three_dots(self):
        self.assertIn('+++ b/components/browser_ui/media/android/java/res/drawable/chrome_product_vd_24.xml',
                      self.patch)
        self.assertEqual(added(self.patch).count('android:pathData='), 3)
        self.assertEqual(removed(self.patch).count('android:pathData='), 4)


class TestRevision(unittest.TestCase):
    def test_r2(self):
        # r2's changes are in every later revision; release.json only counts up.
        self.assertGreaterEqual(json.loads((ROOT / 'android' / 'release.json').read_text())['revision'], 2)


if __name__ == '__main__':
    unittest.main()

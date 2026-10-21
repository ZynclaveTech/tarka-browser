"""A5 Task 3: the direct APK's daily update check (android/patches/
update-check.patch). The fetch, its rules and the menu's "Update" item; never
when Play installed the app."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANDROID = ROOT / 'android'


class TestUpdateCheck(unittest.TestCase):
    def setUp(self):
        self.patch = (ANDROID / 'patches' / 'update-check.patch').read_text()
        self.added = '\n'.join(l[1:] for l in self.patch.splitlines() if l.startswith('+'))

    def test_in_the_series_after_a3(self):
        series = (ANDROID / 'patches' / 'series').read_text().split()
        self.assertGreater(series.index('update-check.patch'), series.index('xlit-small-products.patch'))

    def test_the_index_rules_have_unit_tests(self):
        for f in ('update_index.h', 'update_index.cc', 'update_index_unittest.cc', 'BUILD.gn'):
            self.assertIn(f'+++ b/chrome/browser/tark_update/{f}', self.patch)
        for name in ('ParseIndex_ReadsTheIndex', 'ParseIndex_RejectsBadInput', 'IsNewer_HigherIs',
                     'IsNewer_SameOrLowerIsNot', 'ShouldCheckNow_FirstTime', 'ShouldCheckNow_23hNo_24hYes',
                     'ShouldCheckNow_FutureLastCheckChecks', 'FailedCheckWaitsADay'):
            self.assertIn(f'TEST(TarkUpdateIndexTest, {name})', self.added)

    def test_the_fetch_sends_nothing_about_the_person(self):
        self.assertIn('https://gettarka.com/android/v1/latest.json', self.added)
        self.assertIn('network::mojom::CredentialsMode::kOmit', self.added)
        self.assertIn('SetOnRedirectCallback', self.added)
        self.assertIn('DownloadToString', self.added)
        self.assertIn('kMaxIndexBytes', self.added)
        self.assertIn('"tark-update-base-url"', self.added)

    def test_never_when_play_installed_the_app(self):
        self.assertIn('"com.android.vending"', self.added)
        self.assertNotIn('com.google.android.play', self.added)
        self.assertNotIn('import com.google.android.gms', self.added)

    def test_the_offer_is_the_menus_update_item(self):
        # Tark's index replaces Google's update service (Omaha) and the Play
        # Store check as the source of "an update is available".
        self.assertIn('+++ b/chrome/browser/omaha/android/java/src/org/chromium/chrome/browser/omaha/'
                      'UpdateStatusProvider.java', self.patch)
        self.assertIn('-            if (VersionNumberGetter.isNewerVersionAvailable()) {', self.patch)
        # The APK's link opens in Tark itself, which downloads it: the
        # non-browser flag would have refused every browser.
        self.assertIn('-            intent.addFlags(Intent.FLAG_ACTIVITY_REQUIRE_NON_BROWSER);', self.patch)
        self.assertIn('intent.setPackage(context.getPackageName());', self.added)

    def test_what_tark_connects_to_lists_it(self):
        self.assertIn('name="IDS_TARK_CONNECTS_UPDATE"', self.added)
        self.assertIn('android:summary="@string/tark_connects_update"', self.added)
        xtb = [l for l in self.patch.splitlines()
               if l.startswith('+<translation') and 'gettarka.com' in l]
        self.assertTrue(xtb, 'the Hindi translation of the connects row')

    def test_build_runs_its_unit_tests(self):
        build = (ANDROID / 'build.sh').read_text()
        self.assertIn('chrome/browser/tark_update:host_unittests', build)
        self.assertIn('clang_x64/tark_update_unittests', build)


class TestUpdateE2E(unittest.TestCase):
    def test_cases(self):
        run = (ANDROID / 'update' / 'e2e' / 'run.py').read_text()
        for case in ('newer', 'same', 'offline', 'play_installed', 'redirect'):
            self.assertIn(f'def case_{case}(', run)


if __name__ == '__main__':
    unittest.main()

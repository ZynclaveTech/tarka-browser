"""A1: android/series.py writes Tark's Android patch series (Tark's patches
from patches/series minus android/desktop-only-patches.txt), and the Android
build config pins the spec's values."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ANDROID = REPO / 'android'
sys.path.insert(0, str(ANDROID))


def lines(path):
    return [l.strip() for l in path.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class TestAndroidSeries(unittest.TestCase):
    def setUp(self):
        import series  # noqa: E402  (android/series.py)
        self.series = series.series(REPO)
        self.tark = [e for e in lines(REPO / 'patches' / 'series') if e.startswith('tarka/')]
        self.skip = set(lines(ANDROID / 'desktop-only-patches.txt'))

    def test_tark_in_order_then_android_only(self):
        self.assertTrue(self.series)
        android = [e for e in self.series if e.startswith('android/')]
        tark = [e for e in self.series if not e.startswith('android/')]
        self.assertTrue(all(e.startswith('tarka/') for e in tark))
        self.assertEqual(tark, [e for e in self.tark if e not in self.skip])
        # Android-only patches (android/patches/series) come last.
        self.assertEqual(self.series[len(tark):], android)
        self.assertEqual(android, ['android/' + e for e in lines(ANDROID / 'patches' / 'series')])
        for e in android:
            self.assertTrue((ANDROID / 'patches' / e[len('android/'):]).is_file(), e)

    def test_locales_fix_is_android_only(self):
        self.assertIn('android/locales-android-branch.patch', self.series)
        self.assertNotIn('android/locales-android-branch.patch',
                         (REPO / 'patches' / 'series').read_text())

    def test_reset_template_url_callers_fixed(self):
        # ungoogled's add-suggestions-url-field.patch gives ResetTemplateURL a
        # fifth argument (and makes it overwrite suggestions_url); the
        # Android-only callers keep each engine's own suggestions URL.
        self.assertIn('android/search-engines-android-suggestions-url.patch', self.series)
        patch = (ANDROID / 'patches' / 'search-engines-android-suggestions-url.patch').read_text()
        self.assertIn('+++ b/components/search_engines/android/template_url_service_android.cc', patch)
        self.assertIn('+          regulatory_api_turl->suggestions_url());', patch)
        self.assertIn('+                                          search_url, template_url->suggestions_url());', patch)

    def test_rlz_ping_never_sent(self):
        # ungoogled's disable-untraceable-urls.patch removes Google's RLZ
        # server (kFinancialServer); Android's ping handler reports failure
        # without a request.
        self.assertIn('android/rlz-ping-handler-no-ping.patch', self.series)
        patch = (ANDROID / 'patches' / 'rlz-ping-handler-no-ping.patch').read_text()
        self.assertIn('+++ b/chrome/browser/android/rlz/rlz_ping_handler.cc', patch)
        self.assertIn('-  handler->Ping(brand, language, events, id, std::move(callback));', patch)
        self.assertIn('+  std::move(callback).Run(false);', patch)
        added = [l for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++')]
        self.assertFalse(any('kFinancialServer' in l for l in added))

    def test_safe_browsing_leftovers_fixed(self):
        # Android-only code that still names Safe Browsing pieces ungoogled
        # removes (safe_browsing_mode=0) is compiled out or loses the call.
        self.assertIn('android/safe-browsing-android-leftovers.patch', self.series)
        patch = (ANDROID / 'patches' / 'safe-browsing-android-leftovers.patch').read_text()
        for f in ('chrome/browser/download/chrome_download_manager_delegate.cc',
                  'chrome/browser/download/download_ui_safe_browsing_util.cc',
                  'chrome/browser/interstitials/enterprise_util.cc',
                  'chrome/browser/notifications/persistent_notification_handler.cc',
                  'components/enterprise/connectors/core/cloud_content_scanning/'
                  'cloud_binary_upload_service_base.cc'):
            self.assertIn('+++ b/' + f, patch)
        added = '\n'.join(l for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++'))
        for gone in ('ShouldUploadBinaryForDeepScanning', 'kSafeBrowsingProceedAnywayDisabled',
                     'AddToDeepScanRequests', 'NotificationContentDetectionUkmUtil'):
            self.assertNotIn(gone, added)
        self.assertIn('+#include "base/files/file_path.h"', patch)

    def test_extension_util_include_only_with_extensions(self):
        # ungoogled's add-flag-to-configure-extension-downloading.patch includes
        # extensions/browser/extension_util.h unconditionally; Android builds
        # no extensions, so the include follows the code's ENABLE_EXTENSIONS_CORE.
        self.assertIn('android/download-extension-util-include.patch', self.series)
        patch = (ANDROID / 'patches' / 'download-extension-util-include.patch').read_text()
        self.assertIn('-#include "extensions/browser/extension_util.h"', patch)
        self.assertIn(' #if BUILDFLAG(ENABLE_EXTENSIONS_CORE)\n+#include "extensions/browser/extension_util.h"\n'
                      ' #include "extensions/browser/webstore_installer.h"', patch)

    def test_safe_browsing_link_fixed(self):
        # libchrome.so links: Java's Safe Browsing natives and the settings
        # launchers get Tark's stand-ins (Safe Browsing reads as off); the
        # other callers of removed code drop or guard the call.
        self.assertIn('android/safe-browsing-android-link.patch', self.series)
        patch = (ANDROID / 'patches' / 'safe-browsing-android-link.patch').read_text()
        stubs = 'chrome/browser/android/tark/safe_browsing_stubs_android.cc'
        self.assertIn('--- /dev/null\n+++ b/' + stubs, patch)
        self.assertIn('+      "tark/safe_browsing_stubs_android.cc",', patch)
        prefix = 'Muxed_org_chromium_chrome_browser_safe_1browsing_'
        for native in ('SafeBrowsingBridge_enableSafeBrowsingSettingSetLocallyPref',
                       'SafeBrowsingBridge_getSafeBrowsingExtendedReportingEnabled',
                       'SafeBrowsingBridge_getSafeBrowsingExtendedReportingManaged',
                       'SafeBrowsingBridge_getSafeBrowsingState',
                       'SafeBrowsingBridge_isHashRealTimeLookupEligibleInSession',
                       'SafeBrowsingBridge_isSafeBrowsingManaged',
                       'SafeBrowsingBridge_setSafeBrowsingExtendedReportingEnabled',
                       'SafeBrowsingBridge_setSafeBrowsingState',
                       'SafeBrowsingBridge_umaValueForFile',
                       'SafeBrowsingPasswordReuseDialogBridge_checkPasswords',
                       'SafeBrowsingPasswordReuseDialogBridge_close',
                       'SafeBrowsingPasswordReuseDialogBridge_ignore',
                       'SafeBrowsingSuspiciousSiteDialogBridge_close',
                       'SafeBrowsingSuspiciousSiteDialogBridge_continueAnyway',
                       'SafeBrowsingSuspiciousSiteDialogBridge_goBack',
                       'SafeBrowsingSuspiciousSiteDialogBridge_onLearnMoreClicked'):
            self.assertIn('JNI_ZERO_MUXED_ENTRYPOINT', patch)
            self.assertIn(prefix + native + '(', patch, native)
        self.assertIn('+void ShowSafeBrowsingSettings(ui::WindowAndroid* window,', patch)
        self.assertIn('+void ShowAdvancedProtectionSettings(ui::WindowAndroid* window)', patch)
        added = '\n'.join(l for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++'))
        for gone in ('GetSafeBrowsingState(', 'RecordSuspiciousNotificationInteractionUkm',
                     'ChromePasswordReuseDetectionManagerClient'):
            self.assertNotIn(gone, added)
        # No Safe Browsing client is attached: the sheet must not call through null.
        self.assertIn('+  if (password_reuse_detection_manager_client_) {', patch)
        # The call needs the client's interface, not Chrome's (unbuilt) class.
        self.assertIn('+#include "components/safe_browsing/core/browser/password_protection/'
                      'password_reuse_detection_manager_client.h"', patch)

    def test_direct_apk_size(self):
        # Spec: direct APK ≤ 130 MB, native library compressed, no XR module
        # (the user's decision, 2026-10-20).
        self.assertIn('android/direct-apk-size.patch', self.series)
        patch = (ANDROID / 'patches' / 'direct-apk-size.patch').read_text()
        self.assertIn('-  xr_module_desc,', patch)
        self.assertIn('+    library_always_compress = [ "libchrome.so" ]', patch)
        self.assertIn('+    jinja_extra_variables = [ "extract_native_libs=true" ]', patch)
        self.assertIn('+        android:extractNativeLibs="true"', patch)

    def test_no_device_account_seeding(self):
        # ungoogled never calls LoadCredentials, so Android's account seeding
        # hit CHECK_NE(fire_refresh_token_loaded_, RT_LOAD_NOT_START) on every
        # start (A1 emulator run). Tark uses no Google accounts: seeding is
        # skipped when credentials were never loaded.
        self.assertIn('android/signin-android-no-account-seeding.patch', self.series)
        patch = (ANDROID / 'patches' / 'signin-android-no-account-seeding.patch').read_text()
        self.assertIn('+++ b/components/signin/internal/identity_manager/'
                      'profile_oauth2_token_service_delegate_android.cc', patch)
        self.assertIn('-  CHECK_NE(fire_refresh_token_loaded_, RT_LOAD_NOT_START);', patch)
        self.assertIn('+  if (fire_refresh_token_loaded_ == RT_LOAD_NOT_START) {\n+    return;\n+  }', patch)

    def test_signin_allowed_registered_off(self):
        # Android's first run reads signin.allowed, which ungoogled stops
        # registering (PrefService CHECK on first start, A1 emulator run).
        self.assertIn('android/signin-android-allowed-pref.patch', self.series)
        patch = (ANDROID / 'patches' / 'signin-android-allowed-pref.patch').read_text()
        self.assertIn('+++ b/components/signin/internal/identity_manager/primary_account_manager.cc', patch)
        # ungoogled drops signin_pref_names.cc from the build: the constant
        # does not link, so the pref is named by its string.
        self.assertNotIn('signin_pref_names.h', patch)
        self.assertNotIn('prefs::kSigninAllowed', patch)
        self.assertIn('+#if BUILDFLAG(IS_ANDROID)\n', patch)
        self.assertIn('+  registry->RegisterBooleanPref("signin.allowed", false);', patch)

    def test_google_callers_off(self):
        # A1's emulator run: Google contacts the Mac build never makes.
        self.assertIn('android/google-callers-off.patch', self.series)
        patch = (ANDROID / 'patches' / 'google-callers-off.patch').read_text()
        # First-run variations seed from clientservices.googleapis.com (Java,
        # outside the net log).
        self.assertIn('-        return VersionInfo.isOfficialBuild();', patch)
        self.assertIn('+        return false;', patch)
        # FCM tokens and IDs from Play Services (policy invalidations asked
        # at startup; Web Push uses the same door).
        self.assertIn('-  Java_InstanceIDBridge_getToken(env, java_ref_, request_id, authorized_entity,', patch)
        self.assertIn('-  Java_InstanceIDBridge_getId(env, java_ref_, request_id);', patch)
        self.assertIn('InstanceID::DISABLED', patch)
        # Widevine provisioning at startup (www.googleapis.com).
        self.assertIn('+BASE_FEATURE(kMediaDrmPreprovisioning, base::FEATURE_DISABLED_BY_DEFAULT);', patch)
        # The new tab page's built-in tiles fetched icons from freenode.net,
        # github.com and others.
        self.assertIn('+++ b/components/ntp_tiles/resources/default_popular_sites.json', patch)
        self.assertIn('-        "url": "https://freenode.net/"', patch)

    def test_app_named_tark(self):
        # The launcher label comes from Android resources, which name
        # substitution does not reach (A1's first APK was labelled Chromium).
        self.assertIn('android/app-name-tark.patch', self.series)
        patch = (ANDROID / 'patches' / 'app-name-tark.patch').read_text()
        self.assertIn('+++ b/chrome/android/java/res_chromium_base/values/channel_constants.xml', patch)
        self.assertIn('+    <string name="app_name" translatable="false">Tark</string>', patch)
        added = [l for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++')]
        self.assertEqual(len(added), 4)
        self.assertFalse(any('Chromium' in l for l in added if 'string name' in l))

    def test_home_is_shodhya_today(self):
        # As on the Mac: new tabs open shodhya.com (Shodhya Today); Incognito
        # and offline keep Android's own page; no first-run welcome.
        self.assertIn('android/home-shodhya-today.patch', self.series)
        patch = (ANDROID / 'patches' / 'home-shodhya-today.patch').read_text()
        self.assertIn('+++ b/chrome/android/java/src/org/chromium/chrome/browser/tab/TabImpl.java', patch)
        self.assertIn('"https://shodhya.com/"', patch)
        self.assertIn('UrlUtilities.isNtpUrl(UrlFormatter.fixupUrl(params.getUrl()))', patch)
        self.assertIn('!isIncognito()', patch)
        self.assertIn('NetworkChangeNotifier.isInitialized()', patch)
        self.assertIn('NetworkChangeNotifier.isOnline()', patch)
        self.assertIn('+++ b/chrome/android/java/src/org/chromium/chrome/browser/firstrun/FirstRunFlowSequencer.java', patch)
        self.assertIn('+        if (TARK_NO_FIRST_RUN\n', patch)

    def test_skip_list_entries_exist(self):
        self.assertTrue(self.skip)
        for entry in self.skip:
            self.assertIn(entry, self.tark, entry)

    def test_sparkle_skipped(self):
        self.assertNotIn('tarka/updater/sparkle.patch', self.series)

    def test_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / 'series'
            result = subprocess.run([sys.executable, str(ANDROID / 'series.py'), str(REPO), str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(lines(out), self.series)


class TestAndroidConfig(unittest.TestCase):
    def test_args_gn(self):
        args = (ANDROID / 'args.gn').read_text()
        for line in ('target_os = "android"', 'target_cpu = "arm64"',
                     'is_official_build = true', 'is_component_build = false',
                     'chrome_pgo_phase = 0', 'symbol_level = 0',
                     'chrome_public_manifest_package = "com.gettarka.tarka"',
                     'use_clang_modules = false'):
            self.assertIn(line, args)

    def test_arcore_stays_on(self):
        # enable_arcore=false leaves components/webxr's Java without its
        # generated natives (javac and the JNI registration check fail).
        # Without the XR module only its ARCore .so files are gone, which
        # WebXR AR loads on demand.
        self.assertNotIn('enable_arcore', (ANDROID / 'args.gn').read_text())

    def test_sysroot_stays_on(self):
        # base/BUILD.gn links a system libatomic on Android when use_sysroot is
        # false, which the NDK copy lacks; host tools get the Debian sysroot.
        self.assertNotIn('use_sysroot', (ANDROID / 'args.gn').read_text())

    def test_gclient_template(self):
        text = (ANDROID / 'gclient.android').read_text()
        # gclient's standard layout: .gclient beside a solution named "src"
        # (depot_tools rejects an absolute solution name).
        self.assertIn('"name": "src"', text)
        self.assertNotIn('UC_OUT', text)
        self.assertIn("target_os = ['android']", text)
        self.assertIn('target_os_only = False', text)
        # DEPS gates the Android SDK on 'checkout_android and non_git_source'.
        self.assertIn('"non_git_source": "True"', text)
        compile(text, 'gclient.android', 'exec')


if __name__ == '__main__':
    unittest.main()

"""Tark for Android's page translation UI (plan Task 6): the Page translation
setting (translate-settings-off.patch) and the offer, languages and download
card (page-translate-ui.patch). The Java behaviour is tested by Robolectric
(PageTranslationSettingsTest, PageTranslationOfferTest in chrome_junit_tests,
run by android/aws/jobs/tark-build.sh); this checks what ties the pieces
together. Runs offline."""
import hashlib
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATCHES = ROOT / 'android' / 'patches'
# The platform-neutral half, shared with the Mac (patches/series).
SHARED_WIRING = ROOT / 'patches' / 'tarka' / 'page-translate' / 'wiring.patch'
PREF = 'tark.page_translation.enabled'
INDIAN = ['as', 'bn', 'brx', 'doi', 'gu', 'hi', 'kn', 'ks', 'kok', 'mai', 'ml',
          'mni', 'mr', 'ne', 'or', 'pa', 'sa', 'sat', 'sd', 'ta', 'te', 'ur']


def series():
    return [l.strip() for l in (PATCHES / 'series').read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


def grit_id(text):
    """grit's message id (tclib's fingerprint) for a message's text."""
    value = int(hashlib.md5(text.encode()).hexdigest()[:16], 16)
    if value & 0x8000000000000000:
        value = -((~value & 0xFFFFFFFFFFFFFFFF) + 1)
    return str(value & 0x7FFFFFFFFFFFFFFF)


def section(patch, path):
    parts = patch.split('\n--- ')
    return ''.join(p for p in parts if f'+++ b/{path}\n' in p)


def added(text):
    return '\n'.join(l[1:] for l in text.splitlines()
                     if l.startswith('+') and not l.startswith('+++'))


class TestSettingsPatch(unittest.TestCase):
    def setUp(self):
        self.patch = (PATCHES / 'translate-settings-off.patch').read_text(encoding='utf-8')

    def test_pref_registered_on(self):
        prefs = added(section(self.patch, 'chrome/browser/ui/browser_ui_prefs.cc'))
        self.assertIn(f'RegisterBooleanPref("{PREF}", true)', prefs)

    def test_no_script_url_check(self):
        self.assertNotIn('translate-script-url"', added(self.patch))
        self.assertNotIn('CommandLine', added(self.patch))

    def test_switch_reads_the_pref_and_google_rows_hidden(self):
        java = added(self.patch)
        self.assertIn(f'TARK_PAGE_TRANSLATION_PREF = "{PREF}"', java)
        self.assertIn('"translation_settings_section"', java)
        self.assertIn('hideGoogleTranslateRows(getPreferenceScreen())', java)

    def test_strings_in_english_and_hindi(self):
        grd = added(section(self.patch, 'chrome/browser/ui/android/strings/android_chrome_strings.grd'))
        xtb = added(section(self.patch, 'chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb'))
        for text in ('Page translation',
                     "Translates pages on your phone with Tark's own model. Pages never leave your phone."):
            self.assertIn(text, grd)
            self.assertIn(f'<translation id="{grit_id(text)}">', xtb)

    def test_test_class_built(self):
        build = added(section(self.patch, 'chrome/browser/language/android/BUILD.gn'))
        self.assertIn('PageTranslationSettingsTest.java', build)


class TestUiPatch(unittest.TestCase):
    def setUp(self):
        self.patch = (PATCHES / 'page-translate-ui.patch').read_text(encoding='utf-8')

    def test_in_the_series_after_the_wiring_and_captions_ui(self):
        s = series()
        self.assertIn('page-translate-ui.patch', s)
        self.assertGreater(s.index('page-translate-ui.patch'), s.index('page-translate-wiring.patch'))
        self.assertGreater(s.index('page-translate-ui.patch'), s.index('captions-ui.patch'))
        self.assertLess(s.index('translate-settings-off.patch'), s.index('page-translate-ui.patch'))

    def test_offer_and_menu_read_the_pref(self):
        manager = added(section(self.patch, 'components/translate/core/browser/translate_manager.cc'))
        self.assertIn(f'"{PREF}"', manager)
        self.assertEqual(manager.count('TarkPageTranslationEnabled(translate_client_->GetPrefs())'), 2)
        offer = added(section(self.patch, 'chrome/browser/tark_captions_android/android/java/src/org/chromium/chrome/browser/tark_captions/TarkPageTranslationOffer.java'))
        self.assertIn(f'PREF = "{PREF}"', offer)

    def test_languages_match_the_engine(self):
        offer = added(section(self.patch, 'chrome/browser/tark_captions_android/android/java/src/org/chromium/chrome/browser/tark_captions/TarkPageTranslationOffer.java'))
        java = re.findall(r'"([a-z]{2,3})"', offer[offer.index('INDIAN ='):offer.index('private TarkPageTranslationOffer')])
        self.assertEqual(java, INDIAN)
        browser = (PATCHES / 'page-translate-browser.patch').read_text(encoding='utf-8')
        kindian = browser[browser.index('kIndian[] = {'):]
        self.assertEqual(re.findall(r'"([a-z]{2,3})"', kindian[:kindian.index('};')]), INDIAN)
        listcc = added(section(self.patch, 'components/translate/core/browser/translate_language_list.cc'))
        tark = listcc[listcc.index('kTarkLanguages[] = {'):]
        self.assertEqual(sorted(re.findall(r'"([a-z]{2,3})"', tark[:tark.index('};')])),
                         sorted(INDIAN + ['en', 'es']))

    def test_tap_asks_before_translating(self):
        manager = added(section(self.patch, 'components/translate/core/browser/translate_manager.cc'))
        self.assertIn('TarkReadyToTranslate(', manager)
        client = added(section(self.patch, 'chrome/browser/translate/chrome_translate_client.cc'))
        self.assertIn('Java_TarkPageTranslationCard_readyOrShowCard', client)
        self.assertIn('IsOffTheRecord()', client)

    def test_directions_offer_menu_and_fallback(self):
        shared = SHARED_WIRING.read_text(encoding='utf-8')
        header = added(section(shared, 'components/translate/core/browser/tark_translate_directions.h'))
        kindian = header[header.index('kIndian[] = {'):]
        self.assertEqual(re.findall(r'"([a-z]{2,3})"', kindian[:kindian.index('};')]), INDIAN)
        manager = added(section(self.patch, 'components/translate/core/browser/translate_manager.cc'))
        self.assertIn('TarkTargetFor(original_source_lang, target_lang)', manager)
        self.assertIn('TarkSupportsDirection(page_language_code, target_lang)', manager)
        message = added(section(self.patch, 'components/translate/content/android/translate_message.cc'))
        self.assertEqual(message.count('TarkSupportsDirection('), 2)
        # The blocked-language branch keeps upstream's label.
        self.assertNotIn('-        TriggerDecision::kDisabledNeverTranslateLanguage);', self.patch)

    def test_card_stays_ten_minutes(self):
        card = added(section(self.patch, 'chrome/browser/tark_captions_android/android/java/src/org/chromium/chrome/browser/tark_captions/TarkPageTranslationCard.java'))
        self.assertIn('DISMISSAL_DURATION_MS = 600_000L', card)
        self.assertNotIn('showOffer', added(self.patch))

    def test_owner_page_translation(self):
        java = added(section(self.patch, 'chrome/browser/tark_captions_android/android/java/src/org/chromium/chrome/browser/tark_captions/TarkCaptionsBridge.java'))
        self.assertIn('OWNER_PAGE_TRANSLATION = 2', java)
        cc = added(section(self.patch, 'chrome/browser/tark_captions_android/android/tark_captions_bridge.cc'))
        self.assertIn('Owner::kPageTranslation', cc)

    def test_private_string_in_english_and_hindi(self):
        grd = added(section(self.patch, 'chrome/browser/ui/android/strings/android_chrome_strings.grd'))
        xtb = added(section(self.patch, 'chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb'))
        self.assertIn('Download in a regular tab first', grd)
        self.assertIn(f'<translation id="{grit_id("Download in a regular tab first")}">', xtb)

    def test_junit_classes_run_and_must_have_run(self):
        job = (ROOT / 'android' / 'aws' / 'jobs' / 'tark-build.sh').read_text()
        filters = ' '.join(re.findall(r"--gtest_filter='([^']*)'", job))
        loop = job[job.index('for t in SpeechRecognitionImplTest'):]
        loop = loop[:loop.index('; do')]
        for test in ('PageTranslationSettingsTest', 'PageTranslationOfferTest'):
            self.assertIn(f'*{test}*', filters)
            self.assertIn(test, loop.split())
        build = added(section(self.patch, 'chrome/android/BUILD.gn'))
        self.assertIn('//chrome/browser/tark_captions_android/android:junit', build)


if __name__ == '__main__':
    unittest.main()

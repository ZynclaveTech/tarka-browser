"""A3: Indian-language rows in the Android address bar (spec §5). The model
and word lists are not in the APK: android/xlit/files.py splits the word
lists per language and pins every file's size and sha256 for the download.
These tests run offline."""
import hashlib
import json
import pathlib
import struct
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'android' / 'xlit'))
import files  # noqa: E402


def txlw_tags(path):
    data = pathlib.Path(path).read_bytes()
    assert data[:8] == b'TXLW\x01\x00\x00\x00'
    (length,) = struct.unpack('<I', data[8:12])
    return set(json.loads(data[12:12 + length]))


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        words = self.tmp / 'words'
        words.mkdir()
        (words / 'hi.tsv').write_text('नमस्ते\t5\nघर\t3\n', encoding='utf-8')
        (words / 'ta.tsv').write_text('வணக்கம்\t4\n', encoding='utf-8')
        (self.tmp / 'english.txt').write_text('the\nhello\n', encoding='utf-8')
        (self.tmp / 'model.bin').write_bytes(b'TXLM' + bytes(60))
        self.args = (words, self.tmp / 'english.txt', self.tmp / 'model.bin')

    def build(self, name='out'):
        out = self.tmp / name
        return out, files.build(*self.args, out)

    def test_one_file_per_language_each_with_english(self):
        out, _ = self.build()
        self.assertEqual(sorted(p.name for p in out.glob('xlit-words-*.bin')),
                         ['xlit-words-hi.bin', 'xlit-words-ta.bin'])
        self.assertEqual(txlw_tags(out / 'xlit-words-hi.bin'), {'hi', 'en'})
        self.assertEqual(txlw_tags(out / 'xlit-words-ta.bin'), {'ta', 'en'})
        self.assertEqual((out / 'xlit-model.bin').read_bytes(), self.args[2].read_bytes())

    def test_files_json_matches_bytes(self):
        out, table = self.build()
        self.assertEqual(json.loads((out / 'files.json').read_text()), table)
        self.assertEqual(set(table), {'xlit-model.bin', 'xlit-words-hi.bin', 'xlit-words-ta.bin'})
        for name, entry in table.items():
            data = (out / name).read_bytes()
            self.assertEqual(entry, {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})

    def test_header_lists_every_file_once(self):
        out, table = self.build()
        inc = self.tmp / 'xlit_files.inc'
        files.header(out / 'files.json', inc)
        text = inc.read_text()
        for name, entry in table.items():
            self.assertEqual(text.count(f'"{name}"'), 1)
            self.assertIn(f'{{"{name}", {entry["size"]}, "{entry["sha256"]}"}},', text)

    def test_build_is_deterministic(self):
        a, _ = self.build('a')
        b, _ = self.build('b')
        for p in a.iterdir():
            self.assertEqual(p.read_bytes(), (b / p.name).read_bytes(), p.name)

    def test_build_sh_runs_files_after_install_xlit(self):
        sh = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('android/xlit/files.py" build', sh)
        self.assertLess(sh.index('_install_xlit\n'), sh.index('android/xlit/files.py" build'))
        self.assertIn('third_party/indicxlit/android', sh)
        self.assertIn('chrome/browser/tark_xlit/xlit_files.inc', sh)
        self.assertIn("'android/xlit/files.py'", (ROOT / 'android' / 'prep_hash.py').read_text())


PATCHES = ROOT / 'android' / 'patches'


def series():
    return [l.strip() for l in (PATCHES / 'series').read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class TestFilesPatch(unittest.TestCase):
    """A3 Task 2: tark_xlit reads per-language lists from the app's data."""
    def setUp(self):
        self.patch = (PATCHES / 'xlit-android-files.patch').read_text()

    def test_in_the_android_series(self):
        self.assertIn('xlit-android-files.patch', series())

    def test_word_list_takes_several_files(self):
        self.assertIn('+      std::vector<std::unique_ptr<base::MemoryMappedFile>> files);', self.patch)
        self.assertIn('parts_[block.part]', self.patch)

    def test_part_files_are_never_read(self):
        self.assertIn('FILE_PATH_LITERAL("xlit-words-*.bin")', self.patch)

    def test_downloaded_directory_only_when_ready(self):
        self.assertIn('return FilesReady() ? LoadResourcesFromDirectory(downloaded) : nullptr;', self.patch)

    def test_unit_tests_built_for_the_machine(self):
        self.assertIn('tark_xlit_unittests($host_toolchain)', self.patch)
        self.assertIn('+      "android_files_unittest.cc",', self.patch)
        sh = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('components/tark_xlit:host_unittests', sh)
        self.assertIn('clang_x64/tark_xlit_unittests', sh)

    def test_build_sh_gives_the_tests_two_languages(self):
        sh = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('components/tark_xlit/test/data/android', sh)
        self.assertIn('xlit-words-hi.bin', sh)
        self.assertIn('xlit-words-ta.bin', sh)



class TestRowsPatch(unittest.TestCase):
    """A3 Task 3: the provider on Android, the offer row, rows Java can tell
    apart (the language label on the right, as on the Mac)."""
    def setUp(self):
        self.patch = (PATCHES / 'xlit-android-rows.patch').read_text()

    def section(self, path):
        parts = self.patch.split('--- ')
        return ''.join(p for p in parts if f'+++ b/{path}' in p)

    def test_in_the_android_series_after_the_files(self):
        s = series()
        self.assertLess(s.index('xlit-android-files.patch'), s.index('xlit-android-rows.patch'))

    def test_provider_built_on_android(self):
        self.assertIn('+  if (is_mac || is_android) {', self.section('components/omnibox/browser/BUILD.gn'))
        controller = self.section('components/omnibox/browser/autocomplete_controller.cc')
        self.assertEqual(controller.count('+#if BUILDFLAG(IS_MAC) || BUILDFLAG(IS_ANDROID)'), 3)

    def test_classifier_adds_query_tile_on_android(self):
        classifier = self.section('components/omnibox/browser/autocomplete_classifier.cc')
        # Right after TYPE_TAB_GROUP, which only the Android block lists.
        self.assertIn(' AutocompleteProvider::TYPE_TAB_GROUP |\n+      // Tark (A3): Indian-language rows, as on macOS.\n'
                      '+      AutocompleteProvider::TYPE_QUERY_TILE |', classifier)

    def test_provider_waits_for_the_download(self):
        provider = self.section('components/omnibox/browser/tark_transliteration_provider.cc')
        self.assertIn('tark_xlit::FilesReady()', provider)
        self.assertIn('kOfferInfoKey[] = "tark_xlit_offer"', provider)
        self.assertIn('kOfferRelevance = 1296', provider)
        self.assertIn('tark_xlit::ShouldOffer(', provider)

    def test_jni_carries_both_fields(self):
        self.assertIn('Java_AutocompleteMatch_setTarkXlit(', self.section('components/omnibox/browser/autocomplete_match_android.cc'))
        java = self.section('components/omnibox/browser/android/java/src/org/chromium/components/omnibox/AutocompleteMatch.java')
        self.assertIn('private void setTarkXlit(', java)
        self.assertIn('public boolean isTarkTransliteration()', java)
        self.assertIn('public @Nullable String getTarkXlitOfferTag()', java)

    def test_label_drawn_at_the_right_and_read_out(self):
        self.assertIn('@+id/tark_xlit_label', self.section('chrome/browser/ui/android/omnibox/java/res/layout/omnibox_basic_suggestion.xml'))
        processor = self.section('chrome/browser/ui/android/omnibox/java/src/org/chromium/chrome/browser/omnibox/suggestions/basic/BasicSuggestionProcessor.java')
        self.assertIn('SuggestionViewProperties.TARK_XLIT_LABEL', processor)
        self.assertIn('TarkXlitOffer.show(', processor)
        self.assertIn('TARK_XLIT_LABEL', self.section('chrome/browser/ui/android/omnibox/java/src/org/chromium/chrome/browser/omnibox/suggestions/basic/SuggestionViewViewBinder.java'))

    def test_offer_strings_in_english_and_hindi(self):
        grd = self.section('chrome/browser/ui/android/strings/android_chrome_strings.grd')
        self.assertIn('name="IDS_TARK_XLIT_OFFER"', grd)
        self.assertIn('Type in <ph name="LANGUAGE">%1$s<ex>हिन्दी</ex></ph>?', grd)
        xtb = self.section('chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb')
        self.assertIn('<ph name="LANGUAGE"/> में टाइप करें?', xtb)



class TestDownloadPatch(unittest.TestCase):
    """A3 Task 4: the download, only after the person says yes."""
    def setUp(self):
        self.patch = (PATCHES / 'xlit-android-download.patch').read_text()

    def section(self, path):
        return ''.join(p for p in self.patch.split('--- ') if f'+++ b/{path}' in p)

    def test_in_the_android_series_after_the_rows(self):
        s = series()
        self.assertLess(s.index('xlit-android-rows.patch'), s.index('xlit-android-download.patch'))

    def test_only_gettarka_without_cookies(self):
        service = self.section('chrome/browser/tark_xlit/xlit_download_service.cc')
        self.assertIn('DefineNetworkTrafficAnnotation("tark_xlit_download"', service)
        self.assertIn('destination_other: "gettarka.com"', service)
        self.assertIn('cookies_allowed: NO', service)
        self.assertIn('CredentialsMode::kOmit', service)
        files = self.section('chrome/browser/tark_xlit/xlit_files.cc')
        self.assertIn('"https://gettarka.com/xlit/android/v1/"', files)

    def test_no_redirects_and_a_timeout(self):
        service = self.section('chrome/browser/tark_xlit/xlit_download_service.cc')
        self.assertIn('SetOnRedirectCallback(', service)
        self.assertIn('SetTimeoutDuration(kTimeout)', service)

    def test_written_to_part_then_checked_then_renamed(self):
        service = self.section('chrome/browser/tark_xlit/xlit_download_service.cc')
        self.assertIn('".part"', service)
        self.assertIn('VerifyFile(part, file) && base::ReplaceFile(part, target, nullptr)', service)

    def test_nothing_fetched_until_accepted(self):
        service = self.section('chrome/browser/tark_xlit/xlit_download_service.cc')
        self.assertIn('GetOfferState() != OfferState::kAccepted) {\n+    return;', service)

    def test_started_with_the_browser_and_prefs_registered(self):
        self.assertIn('tark_xlit::XlitDownloadService::Get();', self.section('chrome/browser/chrome_browser_main_android.cc'))
        self.assertIn('tark_xlit::XlitDownloadService::RegisterPrefs(registry);', self.section('chrome/browser/prefs/browser_prefs.cc'))

    def test_the_dialog_can_use_the_browser_alert_style(self):
        # Found building A3: R.style.ThemeOverlay_BrowserUI_AlertDialog lives in
        # browser_ui/widget's resources.
        build = self.section('chrome/browser/tark_xlit/android/BUILD.gn')
        self.assertIn('"//components/browser_ui/widget/android:java_resources"', build)

    def test_the_dialog_offers_wifi_now_and_no(self):
        offer = self.section('chrome/browser/tark_xlit/android/java/src/org/chromium/chrome/browser/tark_xlit/TarkXlitOffer.java')
        for s in ('tark_xlit_download_on_wifi', 'tark_xlit_download_now', 'tark_xlit_no_thanks'):
            self.assertIn('R.string.' + s, offer)
        self.assertIn('TarkXlitBridge.accept(/* now= */ false)', offer)

    def test_strings_in_english_and_hindi(self):
        grd = self.section('chrome/browser/ui/android/strings/android_chrome_strings.grd')
        for name in ('IDS_TARK_XLIT_OFFER_MESSAGE', 'IDS_TARK_XLIT_DOWNLOAD_ON_WIFI', 'IDS_TARK_XLIT_DOWNLOAD_NOW',
                     'IDS_TARK_XLIT_NO_THANKS', 'IDS_TARK_CONNECTS_XLIT'):
            self.assertIn(f'name="{name}"', grd)
        xtb = self.section('chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb')
        for i in ('8851795724424030803', '854019961256078494', '8273905181216423293', '8533623660476485480'):
            self.assertIn(f'<translation id="{i}">', xtb)
        # "No thanks" is already in the Hindi file; a second copy would clash.
        self.assertNotIn('id="780301667611848630"', xtb)

    def test_listed_in_what_tark_connects_to(self):
        self.assertIn('android:summary="@string/tark_connects_xlit"', self.section('chrome/android/java/res/xml/privacy_preferences.xml'))

    def test_files_unit_tests_run_on_the_machine(self):
        self.assertIn('tark_xlit_files_unittests($host_toolchain)', self.section('chrome/browser/tark_xlit/BUILD.gn'))
        sh = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('chrome/browser/tark_xlit:host_unittests', sh)
        self.assertIn('clang_x64/tark_xlit_files_unittests', sh)



class TestSettingsPatch(unittest.TestCase):
    """A3 Task 5: Settings > Languages > Indian-language suggestions."""
    def setUp(self):
        self.patch = (PATCHES / 'xlit-android-settings.patch').read_text()

    def section(self, path):
        return ''.join(p for p in self.patch.split('--- ') if f'+++ b/{path}' in p)

    def test_in_the_android_series_after_the_download(self):
        s = series()
        self.assertLess(s.index('xlit-android-download.patch'), s.index('xlit-android-settings.patch'))

    def test_switch_in_languages_page(self):
        java = self.section('chrome/browser/language/android/java/src/org/chromium/chrome/browser/language/settings/LanguageSettings.java')
        self.assertIn('TARK_XLIT_SWITCH_KEY = "tark_xlit_switch"', java)
        self.assertIn('TarkXlitBridge.accept(/* now= */ false)', java)
        self.assertIn('TarkXlitBridge.decline()', java)
        # Both versions of the page get it.
        self.assertIn('+        addTarkXlitSwitch();', java)
        self.assertIn('"//chrome/browser/tark_xlit/android:java"', self.section('chrome/browser/language/android/BUILD.gn'))

    def test_summary_names_the_downloaded_languages(self):
        java = self.section('chrome/browser/language/android/java/src/org/chromium/chrome/browser/language/settings/LanguageSettings.java')
        self.assertIn('TarkXlitBridge.getDownloadedLanguageNames()', java)
        self.assertIn('TarkXlitBridge.isWaitingForWifi()', java)

    def test_settings_strings_in_english_and_hindi(self):
        grd = self.section('chrome/browser/ui/android/strings/android_chrome_strings.grd')
        for name in ('IDS_TARK_XLIT_SWITCH_TITLE', 'IDS_TARK_XLIT_SWITCH_OFF', 'IDS_TARK_XLIT_SWITCH_WAITING',
                     'IDS_TARK_XLIT_SWITCH_DOWNLOADING', 'IDS_TARK_XLIT_SWITCH_DOWNLOADED'):
            self.assertIn(f'name="{name}"', grd)
        xtb = self.section('chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb')
        for i in ('6612875707773743625', '8304126055697421220', '9054517922063697959'):
            self.assertIn(f'<translation id="{i}">', xtb)
        # "Off" and "Downloading…" are already translated.
        for i in ('5860033963881614850', '6738867403308150051'):
            self.assertNotIn(f'id="{i}"', xtb)



class TestSiteSearch(unittest.TestCase):
    """A3 Task 6: @ sources open a chip on Android (Chromium's site search)."""
    def test_site_search_enabled_on_android(self):
        patch = (PATCHES / 'omnibox-site-search-on.patch').read_text()
        self.assertIn('-BASE_FEATURE(kOmniboxSiteSearch, DISABLED);', patch)
        self.assertIn('+BASE_FEATURE(kOmniboxSiteSearch, ENABLED);', patch)
        self.assertIn('omnibox-site-search-on.patch', series())



class TestE2E(unittest.TestCase):
    """A3 Task 8: the emulator checks (android/xlit/e2e/run.py)."""
    def setUp(self):
        # By path: A2's e2e script is also called run.py.
        import importlib.util
        spec = importlib.util.spec_from_file_location('xlit_e2e_run', ROOT / 'android' / 'xlit' / 'e2e' / 'run.py')
        self.run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.run)

    def test_every_case_of_the_plan(self):
        self.assertEqual(set(self.run.CASES),
                         {'offer', 'decline', 'wifi', 'now', 'rows', 'keyword', 'tamper', 'languages'})

    def test_rows_read_the_label(self):
        xml = ('<node text="नमस्ते" resource-id="com.gettarka.tarka:id/line_1" />'
               '<node text="हिन्दी" resource-id="com.gettarka.tarka:id/tark_xlit_label" />'
               '<node text="namaste" resource-id="com.gettarka.tarka:id/line_1" />')
        self.assertEqual(self.run.rows(xml)[0], ('नमस्ते', 'हिन्दी'))

    def test_the_build_uploads_the_files_it_pins(self):
        job = (ROOT / 'android' / 'aws' / 'jobs' / 'tark-build.sh').read_text()
        self.assertIn('-C /tark/work/src/third_party/indicxlit android', job)
        self.assertIn('upload /tark/xlit-files.tgz xlit-files.tgz', job)

    def test_served_under_their_hashes(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / 'xlit-model.bin').write_bytes(b'model')
        digest = hashlib.sha256(b'model').hexdigest()
        (tmp / 'files.json').write_text(json.dumps({'xlit-model.bin': {'size': 5, 'sha256': digest}}))
        self.assertEqual(self.run.load_files(tmp), {digest + '.bin': 'xlit-model.bin'})



class TestPatchesWellFormed(unittest.TestCase):
    """Found applying A3 on the build machine: a file without a final newline
    (the Hindi .xtb) needs "\\ No newline at end of file" in a patch, or GNU
    patch (unlike macOS's) reads its last line and the next file's header as
    one line."""
    def test_a_last_line_without_newline_is_marked(self):
        for path in sorted(PATCHES.glob('*.patch')):
            lines = path.read_text().split('\n')
            for i, line in enumerate(lines):
                if line[1:].startswith('</translationbundle>') and line[:1] in ' +-':
                    self.assertEqual(line[1:], '</translationbundle>', f'{path.name}:{i + 1}')
                    self.assertEqual(lines[i + 1], '\\ No newline at end of file', f'{path.name}:{i + 1}')


if __name__ == '__main__':
    unittest.main()

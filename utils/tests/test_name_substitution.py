"""Review Focus 3: the product rename must leave chrome:// URLs and the
names of Google's own services alone."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import name_substitution_utils as util  # noqa: E402

CASES = [
    ("Chromium", "Tark"),
    ("Google Chrome", "Tark"),
    ("Chrome", "Tark"),
    ("Chrome Web Store", "Chrome Web Store"),
    ("Chromium Web Store", "Chromium Web Store"),
    ("Chrome Root Program", "Chrome Root Program"),
    ("chrome://about", "chrome://about"),
    ("chrome://settings/search", "chrome://settings/search"),
    ("The Chromium Authors", "Zynclave Tech Private Limited"),
    ("Chromium's", "Tark's"),
    ("ChromiumOS", "ChromiumOS"),
    ("chromium.org", "chromium.org"),
]


def test_replace_text():
    for source, expected in CASES:
        got, _ = util.replace_text(source)
        assert got == expected, f"{source!r}: {got!r} != {expected!r}"


# The copyright line on About and chrome://version names the company that
# makes Tark, in English and in every translation.
def test_copyright_names_the_company():
    english = "Copyright {0,date,y} The Chromium Authors. All rights reserved."
    assert util.replace_text(english)[0] == (
        "Copyright {0,date,y} Zynclave Tech Private Limited. All rights reserved.")
    hindi = "\u0915\u0949\u092a\u0940\u0930\u093e\u0907\u091f YEAR The Chromium Authors."
    assert util.replace_text(hindi, translation=True)[0] == (
        "\u0915\u0949\u092a\u0940\u0930\u093e\u0907\u091f YEAR Zynclave Tech Private Limited.")
    # Persian and Armenian translate the company name without "The".
    assert util.replace_text("Chromium Authors", translation=True)[0] == (
        "Zynclave Tech Private Limited")


# M3 Task 7: "Incognito" becomes "private" in English UI text only.
PRIVATE_CASES = [
    ("New Incognito window", "New private window"),
    ("Incognito", "Private"),
    ("incognito", "private"),
    ("You've gone Incognito", "You've gone private"),
    ("Open Link in Incognito Window", "Open Link in Private Window"),
    ("Close Incognito tabs? You have 3 tabs open.", "Close private tabs? You have 3 tabs open."),
    ("Done. Incognito is on.", "Done. Private is on."),
    ("chrome://settings/incognito", "chrome://settings/incognito"),
    ("IncognitoMode", "IncognitoMode"),
    ("New Incognito window in Chromium", "New private window in Tark"),
    # An ICU plural branch is a label of its own: the toolbar badge.
    ("{0, plural,\n =1 {Incognito}\n other {Incognito (#)}}",
     "{0, plural,\n =1 {Private}\n other {Private (#)}}"),
]


def test_incognito_becomes_private_in_english():
    for source, expected in PRIVATE_CASES:
        got, _ = util.replace_text(source)
        assert got == expected, f"{source!r}: {got!r} != {expected!r}"


def test_translations_keep_their_own_word():
    # Italian and Dutch use "incognito" inside their own phrases.
    for text in ("Navigazione in incognito", "Nieuw incognitovenster", "Incognito"):
        got, _ = util.replace_text(text, translation=True)
        assert got == text, f"{text!r} changed to {got!r}"


def test_a_translation_follows_its_changed_message():
    # A translation with nothing to replace must still move to the new id when
    # its English message changed, or the locale falls back to English.
    import xml.etree.ElementTree as xml
    msg = xml.fromstring('<translation id="111">Neues Inkognitofenster</translation>')
    assert util.replace_xtb_translation(msg, {"111": "222"}) is True
    assert msg.get("id") == "222"
    assert msg.text == "Neues Inkognitofenster"


# M3b Task 4: words outside .grd files, in string literals and HTML text only.
LITERAL_CASES = [
    ('inline constexpr char kName[] = "Chrome History page";',
     'inline constexpr char kName[] = "Tark History page";'),
    ('inline constexpr char kChromeRefreshName[] = "Refresh";',
     'inline constexpr char kChromeRefreshName[] = "Refresh";'),
    ('"Chrome Web Store"', '"Chrome Web Store"'),
    ('"chrome://flags"', '"chrome://flags"'),
    ('"Restore Pages? Chromium didn\'t shut down correctly"',
     '"Restore Pages? Tark didn\'t shut down correctly"'),
    ('"Shows \\"Chrome\\" here" Chrome "and Chromium"',
     '"Shows \\"Tark\\" here" Chrome "and Tark"'),
]


def test_replace_string_literals():
    for source, expected in LITERAL_CASES:
        assert util.replace_string_literals(source) == expected, source


HTML_CASES = [
    ('<h1>List of Chrome URLs</h1>', '<h1>List of Tark URLs</h1>'),
    ('<a href="chrome://settings" title="Chrome">Chrome settings</a>',
     '<a href="chrome://settings" title="Chrome">Tark settings</a>'),
    ('<div class="ChromeThing">${this.chromeUrl}</div>',
     '<div class="ChromeThing">${this.chromeUrl}</div>'),
]


def test_replace_html_text():
    for source, expected in HTML_CASES:
        assert util.replace_html_text(source) == expected, source


def test_literal_files_are_named():
    import name_substitution
    assert 'chrome/browser/flag_descriptions.h' in name_substitution.LITERAL_FILES
    assert 'components/webui/chrome_urls/resources/app.html.ts' in name_substitution.LITERAL_FILES
    assert 'chrome/browser/existing_switch_flag_entries.h' in name_substitution.LITERAL_FILES


# Found previewing M3b Task 4: a Google product name and a hyphenated prose word.
M3B_TEXT_CASES = [
    ("Learn about connecting to Chrome DevTools MCP", "Learn about connecting to Chrome DevTools MCP"),
    ("Inspect with Chrome Developer Tools", "Inspect with Tark Developer Tools"),
    ("private and non-incognito tabs", "private and non-private tabs"),
    ("--enable-incognito-themes", "--enable-incognito-themes"),
]


def test_m3b_text_cases():
    for source, expected in M3B_TEXT_CASES:
        got, _ = util.replace_text(source)
        assert got == expected, f"{source!r}: {got!r} != {expected!r}"


# M3d: Tark's own sentences say "Chromium" on purpose and must stay as written.
def test_tark_sentences_keep_chromium():
    sentence = "Tark 155.0.1, built on Chromium for this Mac."
    assert util.replace_text(sentence)[0] == sentence
    assert util.replace_text("Chromium")[0] == "Tark"


def test_default_workers_fit_windows_limit():
    # W1: ProcessPoolExecutor on Windows refuses more than 61 workers; the
    # 64-core build machine hit it ("max_workers must be <= 61").
    import name_substitution
    assert name_substitution.default_workers(64) == 61
    assert name_substitution.default_workers(8) == 8
    assert name_substitution.default_workers(None) == 1


# A4 Task 6: Android's plain words for whole messages, by message name.
def test_plain_word_renames_have_hindi():
    assert set(util.MESSAGE_RENAMES) == {'IDS_PASSWORD_MANAGER_SETTINGS_TITLE',
                                         'IDS_CLEAR_BROWSING_DATA_TITLE', 'IDS_PREFS_SITE_SETTINGS',
                                         # A2: Site permissions' "Intrusive ads" is Tark's blocker.
                                         'IDS_SITE_SETTINGS_PAGE_INTRUSIVE_ADS_LABEL',
                                         'IDS_SITE_SETTINGS_PAGE_INTRUSIVE_ALLOWED_SUB_LABEL',
                                         'IDS_SITE_SETTINGS_PAGE_INTRUSIVE_BLOCKED_SUB_LABEL',
                                         'IDS_SITE_SETTINGS_PAGE_INTRUSIVE_ADS_A11Y',
                                         'IDS_WEBSITE_SETTINGS_ADS_PAGE_DESCRIPTION',
                                         # A5: the menu's update item names Tark.
                                         'IDS_MENU_UPDATE'}
    for english, old_id, new_id, by_lang in util.MESSAGE_RENAMES.values():
        assert english and old_id != new_id and 'hi' in by_lang


def _xtb(lang, *translations):
    body = ''.join(f'<translation id="{i}">{t}</translation>' for i, t in translations)
    return f'<?xml version="1.0" ?><translationbundle lang="{lang}">{body}</translationbundle>'


def test_hindi_gets_tark_words_and_old_translations_stay():
    out = util.replace_xtb_tree(_xtb('hi', ('961856697154696964', 'ब्राउज़िंग डेटा मिटाएं'),
                                     ('4165986682804962316', 'साइट सेटिंग')), {}, android=True)
    # The old ids stay: other messages share their English text ("Site settings").
    assert '<translation id="961856697154696964">ब्राउज़िंग डेटा मिटाएं</translation>' in out
    assert '<translation id="7602233293931907714">इतिहास और साइट का डेटा मिटाएं</translation>' in out
    assert '<translation id="523862956770478816">साइट की अनुमतियां</translation>' in out


def test_other_languages_keep_their_word_under_the_new_id():
    out = util.replace_xtb_tree(_xtb('ta', ('961856697154696964', 'உலாவல் தரவை நீக்கு')), {}, android=True)
    assert '<translation id="7602233293931907714">உலாவல் தரவை நீக்கு</translation>' in out


def test_an_existing_translation_is_not_duplicated():
    # "Passwords" is already a message: its own translation stays the only one.
    out = util.replace_xtb_tree(_xtb('ta', ('6247557882553405851', 'Google கடவுச்சொல் நிர்வாகி'),
                                     ('7029809446516969842', 'கடவுச்சொற்கள்')), {}, android=True)
    assert out is None or out.count('id="7029809446516969842"') == 1
    assert out is None or '<translation id="7029809446516969842">கடவுச்சொற்கள்</translation>' in out


def test_a_grd_with_only_a_rename_is_written():
    assert util.has_message_renames('<message name="IDS_PREFS_SITE_SETTINGS" desc="x">')
    assert not util.has_message_renames('<message name="IDS_OTHER" desc="x">')


def test_rename_ids_match_grit():
    import os
    import xml.etree.ElementTree as xml
    tree = os.environ.get('TARK_SRC')
    if not tree or not pathlib.Path(tree, 'tools', 'grit').is_dir():
        import pytest
        pytest.skip('set TARK_SRC to a Chromium tree with tools/grit')
    util.add_grit_to_path(pathlib.Path(tree))
    grd = ('<grit><release><messages><message name="IDS_CLEAR_BROWSING_DATA_TITLE" desc="d">\n'
           '        Delete browsing data\n      </message></messages></release></grit>')
    out, _ = util.replace_grit_tree(grd, android=True)
    assert 'Clear history and site data' in out
    for english, old_id, new_id, _ in util.MESSAGE_RENAMES.values():
        m = xml.Element('message')
        m.text = english
        assert util.compute_fp(m) == new_id, english


def test_renames_only_in_android_strings():
    # Final review: IDS_CLEAR_BROWSING_DATA_TITLE also lives in the desktop
    # .grd; the Mac's strings must not change.
    assert util.is_android_strings('chrome/browser/ui/android/strings/android_chrome_strings.grd')
    assert util.is_android_strings('components/browser_ui/strings/android/translations/browser_ui_strings_hi.xtb')
    assert not util.is_android_strings('chrome/app/generated_resources.grd')
    assert not util.is_android_strings('chrome/app/resources/generated_resources_hi.xtb')
    out = util.replace_xtb_tree(_xtb('hi', ('961856697154696964', 'ब्राउज़िंग डेटा मिटाएं')), {}, android=False)
    assert out is None


def test_the_ads_category_is_tarks_blocker_in_hindi_too():
    # A2 final review: "Intrusive ads" (Chromium's) becomes "Ads" (Tark's
    # blocker); its old Hindi stays under the old id.
    out = util.replace_xtb_tree(_xtb('hi', ('8899807382908246773', 'परेशान करने वाले विज्ञापन')), {}, android=True)
    assert '<translation id="1919345977826869612">विज्ञापन</translation>' in out
    assert '<translation id="8899807382908246773">परेशान करने वाले विज्ञापन</translation>' in out


# Found on the user's phone (en-IN, which Android maps to Chromium's en-GB
# strings): British English showed Chromium's words. en-GB is English, so it
# gets Tark's English, not a copy of its old translation.
def test_british_english_gets_tarks_plain_words():
    out = util.replace_xtb_tree(_xtb('en-GB', ('8899807382908246773', 'Intrusive ads'),
                                     ('4165986682804962316', 'Site settings')), {}, android=True)
    assert '<translation id="1919345977826869612">Ads</translation>' in out
    assert '<translation id="523862956770478816">Site permissions</translation>' in out
    # The old ids stay for the other messages that share them.
    assert '<translation id="4165986682804962316">Site settings</translation>' in out


def test_british_english_says_private():
    out = util.replace_xtb_tree(_xtb('en-GB', ('111', 'New Incognito tab'),
                                     ('333', 'Close Incognito tabs?')), {'111': '222'})
    assert '<translation id="222">New private tab</translation>' in out
    assert '<translation id="333">Close private tabs?</translation>' in out


def test_other_translations_still_keep_incognito():
    out = util.replace_xtb_tree(_xtb('it', ('111', 'Navigazione in incognito')), {'111': '222'})
    assert '<translation id="222">Navigazione in incognito</translation>' in out


def test_which_languages_are_english():
    assert util.is_english('en-GB') and util.is_english('en') and util.is_english('en-US')
    assert not util.is_english('hi') and not util.is_english('es-419') and not util.is_english('')


def test_the_update_item_names_tark_in_hindi_too():
    # A5: the app menu's "Update Chrome" (the direct APK's update check).
    out = util.replace_xtb_tree(_xtb('hi', ('1553358976309200471', 'Chrome अपडेट करें')), {}, android=True)
    assert '<translation id="8033778296507731171">Tark अपडेट करें</translation>' in out

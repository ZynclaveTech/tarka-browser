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

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
    ("The Chromium Authors", "The Tark Authors"),
    ("Chromium's", "Tark's"),
    ("ChromiumOS", "ChromiumOS"),
    ("chromium.org", "chromium.org"),
]


def test_replace_text():
    for source, expected in CASES:
        got, _ = util.replace_text(source)
        assert got == expected, f"{source!r}: {got!r} != {expected!r}"


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

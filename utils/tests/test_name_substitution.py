"""Review Focus 3: the product rename must leave chrome:// URLs and the
names of Google's own services alone."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import name_substitution_utils as util  # noqa: E402

CASES = [
    ("Chromium", "Tarka"),
    ("Google Chrome", "Tarka"),
    ("Chrome", "Tarka"),
    ("Chrome Web Store", "Chrome Web Store"),
    ("Chromium Web Store", "Chromium Web Store"),
    ("Chrome Root Program", "Chrome Root Program"),
    ("chrome://about", "chrome://about"),
    ("chrome://settings/search", "chrome://settings/search"),
    ("The Chromium Authors", "The Tarka Authors"),
]


def test_replace_text():
    for source, expected in CASES:
        got, _ = util.replace_text(source)
        assert got == expected, f"{source!r}: {got!r} != {expected!r}"

"""M3 Task 2: Tark's colour tokens (spec §6) and the contrast they promise
(Review Focus 4): secondary text must read as body text in both modes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tokens import DARK, LIGHT, contrast  # noqa: E402


def test_tokens_are_the_spec_values():
    assert DARK["paper"] == "#12121c" and LIGHT["paper"] == "#f6f1e7"
    assert DARK["indigo"] == "#8f88ff" and LIGHT["indigo"] == "#4338ca"
    assert set(DARK) == set(LIGHT)


def test_contrast_of_black_on_white_is_21():
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0


def test_soft_text_on_paper_passes_aa_in_both_modes():
    for name, t in (("dark", DARK), ("light", LIGHT)):
        ratio = contrast(t["soft"], t["paper"])
        assert ratio >= 4.5, f"soft on paper, {name}: {ratio:.2f}"


def test_faint_text_on_raised_is_at_least_3():
    for name, t in (("dark", DARK), ("light", LIGHT)):
        ratio = contrast(t["faint"], t["raised"])
        assert ratio >= 3.0, f"faint on raised, {name}: {ratio:.2f}"


def test_ink_on_paper_and_on_raised_passes_aa():
    for t in (DARK, LIGHT):
        assert contrast(t["ink"], t["paper"]) >= 4.5
        assert contrast(t["ink"], t["raised"]) >= 4.5

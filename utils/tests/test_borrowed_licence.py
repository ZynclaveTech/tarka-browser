"""Borrowed GPL-3.0 files keep their original notice (GPLv3 §5) and the
licence text they point to exists in the repo."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BORROWED = [ROOT / "utils" / "name_substitution.py", ROOT / "utils" / "name_substitution_utils.py"]


def test_gpl_text_present():
    text = (ROOT / "LICENSE.GPL-3.0").read_text()
    assert text.startswith("                    GNU GENERAL PUBLIC LICENSE\n                       Version 3")


def test_borrowed_headers_intact():
    for f in BORROWED:
        head = "\n".join(f.read_text().splitlines()[:8])
        assert "Copyright 2025 The Helium Authors" in head, f.name
        assert "GPL-3.0" in head, f.name
        assert "LICENSE.GPL-3.0" in head, f.name
        assert "Modifications Copyright 2026 The Tark Authors" in head, f.name

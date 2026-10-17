"""M4 Task 1: domain substitution must skip the files that carry the Chrome
Web Store's hosts, and nothing else; a typo in the skip list must fail
loudly rather than leave substitution silently on."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from filter_substitution_list import filter_list  # noqa: E402


def test_filter_drops_skipped_paths_only():
    lines = ["a.cc\n", "extensions/common/extension_urls.cc\n", "b.json\n"]
    assert filter_list(lines, {"extensions/common/extension_urls.cc"}) == ["a.cc\n", "b.json\n"]


def test_unknown_skip_entry_is_an_error():
    with pytest.raises(ValueError, match="extensions/common/extension_url.cc"):
        filter_list(["a.cc\n"], {"extensions/common/extension_url.cc"})


def test_the_real_skip_file_matches_ungoogled_list():
    root = pathlib.Path(__file__).resolve().parents[2]
    lines = (root / "ungoogled-chromium" / "domain_substitution.list").read_text().splitlines(keepends=True)
    skip = {l.strip() for l in (root / "utils" / "domain_substitution_skip.txt").read_text().splitlines() if l.strip() and not l.startswith("#")}
    out = filter_list(lines, skip)
    assert len(out) == len(lines) - len(skip)

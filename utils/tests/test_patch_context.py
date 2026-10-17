"""Patches apply before domain and name substitution, so a Tark patch's
context and removed lines must read as upstream does. A patch refreshed from a
substituted dev tree carries substituted text there and fails on a clean tree
(M3b clean build: no-chromium-words.patch had ch40me.qjz9zk)."""
import pathlib
import re

PATCHES = pathlib.Path(__file__).resolve().parents[2] / "patches" / "tarka"
# Domain substitution's replacement hosts (ungoogled-chromium domain_regex.list).
SUBSTITUTED_DOMAIN = re.compile(r"qjz9zk|9oo91e|ch40me|g00g1e|9oo91eapis|youtu6e")


def test_no_substituted_domains_in_context_or_removed_lines():
    found = []
    for patch in sorted(PATCHES.rglob("*.patch")):
        for number, line in enumerate(patch.read_text(errors="replace").splitlines(), 1):
            if line.startswith(("---", "+++")):
                continue
            if line[:1] in (" ", "-") and SUBSTITUTED_DOMAIN.search(line):
                found.append(f"{patch.relative_to(PATCHES)}:{number}: {line.strip()[:100]}")
    assert not found, "substituted text in context/removed lines:\n" + "\n".join(found)

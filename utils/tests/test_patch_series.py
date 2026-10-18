"""patches/series is the build's patch list; a merge step renames it while a
dev tree is set up, and a commit made then can delete it (b85b708 did). The
committed list must exist and name every Tark patch exactly once."""
import pathlib

PATCHES = pathlib.Path(__file__).resolve().parents[2] / "patches"


def test_series_names_every_tark_patch_once():
    series = PATCHES / "series"
    assert series.is_file(), "patches/series is missing (unmerge before committing)"
    listed = [line.strip() for line in series.read_text().splitlines()
              if line.strip() and not line.startswith("#")]
    tark = [entry for entry in listed if entry.startswith("tarka/")]
    assert len(tark) == len(set(tark)), "a Tark patch is listed twice"
    on_disk = sorted(str(p.relative_to(PATCHES)) for p in (PATCHES / "tarka").rglob("*.patch"))
    assert sorted(tark) == on_disk, (
        "not listed: %s; listed but missing: %s"
        % (sorted(set(on_disk) - set(tark)), sorted(set(tark) - set(on_disk))))

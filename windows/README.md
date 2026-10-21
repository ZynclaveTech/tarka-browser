# Tark for Windows (W1)

Tark's Windows build is upstream
[ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows)
plus Tark's patches and build steps. It builds natively on a Windows machine
(an AWS EC2 instance); everything else (patches, scripts, fixes) is done on
the Mac.

- `upstream/` — upstream's build files and Windows platform patches at the
  tag in `upstream/UPSTREAM_COMMIT` (BSD-3-Clause, `upstream/LICENSE`). Two
  local changes: a hook in `upstream/build.py`, after patching and domain
  substitution, that runs `tark_post_patch.py`; and Tark's names in
  `upstream/package.py` (`tark_stem`: `Tark-<chromium>-<revision>-x64.zip`
  and `-setup.exe`, as the DMG is named). When bumping upstream, copy the
  new files over and re-add both.
- `prepare_workdir.py REPO WORKDIR` — assembles the folder `build.py` runs in:
  upstream's files, this repo's `ungoogled-chromium` core, Tark's patches
  after the Windows ones (minus `mac-only-patches.txt`), Tark's filtered
  domain substitution list. Test: `pytest utils/tests/test_windows_workdir.py`.
- `tark_post_patch.py` — Tark's steps from `build.sh` that are not Mac-only:
  name substitution, the mark, Inter, uBlock Origin, IndicXlit.
- `mac-only-patches.txt` — patches the Windows build leaves out (Sparkle).
- `aws/` — the build machine: `bootstrap.ps1` (one-time setup, idle stop),
  `winbuild.sh` (drive it from the Mac over SSM), `jobs/*.ps1`.

Build from the Mac:

    windows/aws/winbuild.sh start
    windows/aws/winbuild.sh job windows/aws/jobs/tark-build.ps1   # prints command id and S3 prefix
    windows/aws/winbuild.sh wait <command id>
    windows/aws/winbuild.sh fetch <prefix> build/windows/

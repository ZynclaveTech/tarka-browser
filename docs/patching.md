# How Tark changes Chromium

Nothing in the Chromium tree is committed. `./dev.sh setup` (and `build.sh`)
rebuild `build/src` from the tarball in this order:

1. `prune_binaries.py` removes prebuilt binaries ungoogled-chromium refuses to ship.
2. `devutils/update_patches.sh merge` prepends ungoogled-chromium's patch
   series to ours and writes `patches/series.merged`.
3. `quilt push -a` applies that merged series: ungoogled-chromium's patches,
   then the macOS ones, then Tark's (`patches/tarka/…`, `patches/borrowed/…`).
4. `domain_substitution.py` rewrites Google hostnames in the tree.
5. `utils/name_substitution.py --sub` renames Chromium/Chrome to Tark in
   `.grd`, `.grdp` and `.xtb` string files, keeping a backup tarball at
   `build/namesubs.tar` so it can be undone (`--unsub`). It leaves
   `chrome://` URLs and the names of Google's own services alone.
6. `resources/branding/app.icns` is copied over the Chromium app icon.
   Binary files never go in patches; they live in `resources/` and are copied.
7. `gn gen`.

## Making or changing a patch

```sh
source devutils/set_quilt_vars.sh    # QUILT_PATCHES, QUILT_SERIES=series.merged, quilt alias
cd build/src
quilt new tarka/<area>/<name>.patch  # appends to series.merged, after everything applied
quilt add path/to/file               # before editing each file
# edit
quilt refresh                        # writes the patch file
cd ../..
./devutils/update_patches.sh unmerge # restores patches/series with the new entry
git add patches && git commit
./devutils/update_patches.sh merge   # back to the working state
```

`merge` renames `patches/series` to `series.merged` while it is in effect,
so `git status` shows `D patches/series` until you `unmerge`. Commit only in
the unmerged state. The merged copies of upstream patches are gitignored.

Borrowed patches (from Helium or others) go under `patches/borrowed/<vendor>/`
and keep their original licence header.

## Updating to a new Chromium

Bump the `ungoogled-chromium` submodule to the matching tag, then
`./dev.sh reset && ./dev.sh setup`. If a patch fails to apply, setup stops
there; fix it in `build/src` with `quilt push -f`, edit, `quilt refresh`,
then `./dev.sh setup --continue`, which finishes the remaining steps
(substitutions, icon, toolchain, gn gen) without re-fetching. Rebuild,
smoke test.

Name substitution runs after the patches, so before `quilt refresh` or
`quilt pop` on any patch that touches a `.grd`, `.grdp` or `.xtb` file,
run `python3 utils/name_substitution.py --unsub -t build/src --backup-path
build/namesubs.tar`, and `--sub` again afterwards. Keep Tark patches off
string files where you can.

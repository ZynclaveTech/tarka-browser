"""A1: android/build.sh runs the Android build's steps in order. With
TARK_ANDROID_DRYRUN=1 every external command is printed ("tark: run ...")
instead of run, so the order is tested on the Mac without a Chromium tree."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'android' / 'build.sh'


def dryrun(*args):
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, TARK_ANDROID_DRYRUN='1')
        result = subprocess.run(['bash', str(SCRIPT), *args, tmp], capture_output=True,
                                text=True, env=env)
        work = pathlib.Path(tmp)
        files = {
            'gclient': (work / 'gclient').read_text() if (work / 'gclient').exists() else '',
            'series': (work / 'tark-patches' / 'series').read_text()
            if (work / 'tark-patches' / 'series').exists() else '',
            'args': (work / 'src' / 'out' / 'Default' / 'args.gn').read_text()
            if (work / 'src' / 'out' / 'Default' / 'args.gn').exists() else '',
            'clone': (work / 'uc' / 'utils' / 'clone.py').read_text()
            if (work / 'uc' / 'utils' / 'clone.py').exists() else '',
            'dt_patch': (work / 'uc' / 'utils' / 'depot_tools.patch').read_text()
            if (work / 'uc' / 'utils' / 'depot_tools.patch').exists() else '',
            'uc_files': sorted(str(f.relative_to(work / 'uc')) for f in (work / 'uc').rglob('*')
                               if f.is_file()) if (work / 'uc').exists() else [],
            'base_stamp': (work / 'base.stamp').read_text() if (work / 'base.stamp').exists() else '',
        }
        runs = [l[len('tark: run '):] for l in result.stdout.splitlines()
                if l.startswith('tark: run ')]
        return result, runs, files, tmp


def index_of(runs, needle):
    for i, line in enumerate(runs):
        if needle in line:
            return i
    raise AssertionError(f'{needle!r} not run; runs were:\n' + '\n'.join(runs))


class TestAndroidBuildSh(unittest.TestCase):
    def test_steps_in_order_and_stop_before_gn(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertEqual(result.returncode, 3, result.stderr)
        order = [index_of(runs, n) for n in (
            '/clone.py',
            'utils/patches.py apply',
            'utils/filter_substitution_list.py',
            'utils/domain_substitution.py apply',
            'utils/name_substitution.py --sub',
            'utils/install_branding.py',
            '_install_xlit',
        )]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('gn gen', '\n'.join(runs))
        self.assertNotIn('ninja', '\n'.join(runs))

    def test_clone_uses_the_filled_android_config(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertIn(f'-c {tmp}/gclient', runs[index_of(runs, '/clone.py')])
        self.assertIn('"name": "src"', files['gclient'])
        self.assertIn("target_os = ['android']", files['gclient'])

    def test_clone_runs_a_copy_with_the_custom_config_fixed(self):
        # ungoogled's clone.py crashes on -c (it calls Path.replace(old, new)
        # on the path copy() returns); build.sh runs a copy with that line fixed.
        result, runs, files, tmp = dryrun('--stop-before-gn')
        clone = runs[index_of(runs, '/clone.py')]
        self.assertIn(f'{tmp}/uc/utils/clone.py', clone)
        # clone.py reads files beside it and ../chromium_version.txt.
        for f in ('utils/depot_tools.patch', 'utils/gsutil.patch', 'utils/_common.py',
                  'chromium_version.txt'):
            self.assertIn(f, files['uc_files'])
        self.assertNotIn(".gclient').replace('UC_OUT'", files['clone'])
        # .gclient goes beside src (WORKDIR), not inside src/uc_staging.
        self.assertIn("environ['GCLIENT_FILE'] = str(args.output.parent / '.gclient')", files['clone'])
        self.assertIn("copy(args.custom_config, args.output.parent / '.gclient')", files['clone'])
        self.assertIn('def clone(args)', files['clone'])

    def test_depot_tools_patch_keeps_gn_args_file_relative(self):
        # Current depot_tools rejects an absolute gclient_gn_args_file; with
        # .gclient beside src the relative one is right, so that hunk goes.
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertNotIn('self._gn_args_file = r"UC_OUT"', files['dt_patch'])
        self.assertIn('name = r"UC_OUT"+name[3:]', files['dt_patch'])  # other hunks stay
        self.assertIn("parser.add_option('--sysroot')", files['dt_patch'])

    def test_runs_from_the_work_folder(self):
        # gclient writes state files (.gcs_entries) into its working directory;
        # under SSM that is the agent's folder, so build.sh works from WORKDIR.
        script = SCRIPT.read_text()
        self.assertIn('cd "$work"', script)
        self.assertLess(script.index('cd "$work"'), script.index('clone.py" -o'))

    def test_android_cipd_deps_with_stock_gclient(self):
        # ungoogled's depot_tools patch skips CIPD deps, which is how Chromium
        # ships the Android SDK and NDK: a second sync with an unpatched
        # depot_tools (same commit) fetches them, before pruning and patching.
        result, runs, files, tmp = dryrun('--stop-before-gn')
        sync = index_of(runs, 'depot_tools-stock/gclient sync')
        self.assertLess(index_of(runs, '/clone.py'), sync)
        self.assertLess(sync, index_of(runs, 'utils/patches.py apply'))
        line = runs[sync]
        self.assertIn('--nohooks', line)
        self.assertNotIn(' -D', line)  # never delete what clone.py fetched
        self.assertIn('depot_tools-stock fetch -q --depth=1 origin', runs[index_of(runs, 'depot_tools-stock fetch')])

    def test_fails_without_the_android_sdk(self):
        script = SCRIPT.read_text()
        self.assertIn('third_party/android_sdk/public', script)
        self.assertIn('no Android SDK after the sync', script)

    def test_stale_name_substitution_backup_is_cleared(self):
        # clone.py resets the tree each run, so an earlier run's namesubs.tar
        # is stale; name_substitution.py refuses to overwrite it.
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / 'namesubs.tar').write_text('stale')
            env = dict(os.environ, TARK_ANDROID_DRYRUN='1')
            result = subprocess.run(['bash', str(SCRIPT), '--stop-before-gn', tmp],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertFalse((pathlib.Path(tmp) / 'namesubs.tar').exists())

    def test_prepared_tree_is_reused_when_inputs_match(self):
        # A tree prepared from the same inputs skips clone/patch/substitution
        # and goes straight to gn and ninja.
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, TARK_ANDROID_DRYRUN='1')
            first = subprocess.run(['bash', str(SCRIPT), '--stop-before-gn', tmp],
                                   capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 3, first.stderr)
            stamp = pathlib.Path(tmp) / 'prepared.stamp'
            self.assertTrue(stamp.exists())
            second = subprocess.run(['bash', str(SCRIPT), tmp], capture_output=True, text=True, env=env)
            self.assertEqual(second.returncode, 0, second.stderr)
            runs = [l for l in second.stdout.splitlines() if l.startswith('tark: run ')]
            self.assertFalse(any('clone.py' in l or 'patches.py' in l for l in runs), runs)
            self.assertTrue(any('chrome_public_apk' in l for l in runs))

    def test_changed_inputs_wipe_and_prepare_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / 'prepared.stamp').write_text('an older preparation\n')
            (pathlib.Path(tmp) / 'src').mkdir()
            (pathlib.Path(tmp) / 'src' / 'old-file').write_text('x')
            env = dict(os.environ, TARK_ANDROID_DRYRUN='1')
            result = subprocess.run(['bash', str(SCRIPT), '--stop-before-gn', tmp],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn('tark: run rm -rf', result.stdout)
            self.assertIn('clone.py', result.stdout)

    def test_toolchains_fetched_before_domain_substitution(self):
        # Domain substitution rewrites googleapis.com inside the clang and
        # Rust update scripts, so both toolchains are fetched while preparing.
        result, runs, files, tmp = dryrun('--stop-before-gn')
        clang = index_of(runs, 'tools/clang/scripts/update.py')
        rust = index_of(runs, 'tools/rust/update_rust.py')
        self.assertLess(index_of(runs, 'depot_tools-stock/gclient sync'), clang)
        self.assertLess(max(clang, rust), index_of(runs, 'utils/domain_substitution.py apply'))

    def test_chromium_clang_on_path_for_gn_and_ninja(self):
        script = SCRIPT.read_text()
        build = script[script.index('# --- end prepare ---'):]
        self.assertIn('third_party/llvm-build/Release+Asserts/bin', build)
        self.assertIn('CXX=clang++', build)
        self.assertLess(build.index('llvm-build'), build.index('bootstrap.py'))

    def test_prep_hash_covers_only_the_preparation(self):
        import sys
        sys.path.insert(0, str(REPO / 'android'))
        import prep_hash
        section = prep_hash.prep_section(SCRIPT.read_text())
        self.assertIn('clone.py', section)
        self.assertIn('patches.py', section)
        self.assertNotIn('bootstrap.py', section)
        self.assertNotIn('chrome_public_apk', section)

    def test_gn_uses_system_python_like_the_tarball(self):
        # Chromium's tarball .gn says script_executable = "python3"; a git
        # checkout points at a bundled Python the Android tree lacks.
        script = SCRIPT.read_text()
        build = script[script.index('# --- end prepare ---'):]
        self.assertIn('script_executable = \\"python3\\"', build)
        self.assertLess(build.index('script_executable'), build.index('gn" gen'))

    def test_no_pruning_on_android(self):
        # ungoogled's pruning is for the desktop lite tarball: it deletes
        # chrome/android/, android_webview/, the JDK and other CIPD folders,
        # and r8's custom_d8.jar/custom_r8.jar, all of which Android needs.
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertNotIn('prune_binaries.py', '\n'.join(runs))
        self.assertIn('chrome/android/', SCRIPT.read_text())  # the reason is written down

    def test_host_sysroot_installed_before_domain_substitution(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        sysroot = index_of(runs, 'install-sysroot.py --arch=amd64')
        self.assertLess(index_of(runs, 'depot_tools-stock/gclient sync'), sysroot)
        self.assertLess(sysroot, index_of(runs, 'utils/domain_substitution.py apply'))

    def test_core_patches_then_tark_series(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        # Two runs: the core patches belong to the base, Tark's series to
        # Tark's layer (android/layers.py).
        core = index_of(runs, 'utils/patches.py apply')
        self.assertIn('ungoogled-chromium/patches', runs[core])
        self.assertNotIn('tark-patches', runs[core])
        tark = index_of(runs, f'{tmp}/tark-patches')
        self.assertIn('utils/patches.py apply', runs[tark])
        self.assertNotIn('ungoogled-chromium/patches', runs[tark])
        self.assertLess(core, tark)
        self.assertNotIn('tarka/updater/sparkle.patch', files['series'])
        self.assertIn('tarka/omnibox-translit/translit-provider.patch', files['series'])
        self.assertIn('android/locales-android-branch.patch', files['series'])
        self.assertIn('ln -sfn', SCRIPT.read_text())
        self.assertIn('android/patches" "$work/tark-patches/android"', SCRIPT.read_text())

    def test_android_icons_installed_with_the_shared_ones(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertIn('install.txt install-android.txt', runs[index_of(runs, 'utils/install_branding.py')])

    def test_no_ublock(self):
        # The engine-level blocker replaced uBlock Origin everywhere: nothing
        # fetches or keys it.
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertFalse(any('ublock' in r.lower() or 'downloads-tark.ini' in r for r in runs))

    def test_full_build_writes_args_and_builds_the_apk(self):
        result, runs, files, tmp = dryrun()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('enable_hangout_services_extension=false', files['args'])  # core flags.gn
        self.assertIn('chrome_public_manifest_package = "com.gettarka.tarka"', files['args'])
        gn = index_of(runs, 'gn gen')
        ninja = index_of(runs, 'chrome_public_apk')
        self.assertLess(index_of(runs, '_install_xlit'), gn)
        self.assertLess(gn, ninja)

    def test_release_identity_and_bundle(self):
        # A5: Tark's own version name and code, and the app bundle for Play.
        result, runs, files, tmp = dryrun()
        self.assertEqual(result.returncode, 0, result.stderr)
        sys.path.insert(0, str(REPO / 'android' / 'release'))
        import version
        import json
        chromium = (REPO / 'ungoogled-chromium' / 'chromium_version.txt').read_text().strip()
        revision = json.loads((REPO / 'android' / 'release.json').read_text())['revision']
        self.assertIn(f'android_override_version_code = "{version.version_code(chromium, revision)}"',
                      files['args'])
        self.assertIn(f'android_override_version_name = "{version.version_name(chromium, revision)}"',
                      files['args'])
        self.assertLess(index_of(runs, 'chrome_public_apk'), index_of(runs, 'chrome_public_bundle'))
        # Outside the preparation: a new revision never re-prepares.
        import prep_hash
        self.assertNotIn('version.py', prep_hash.prep_section(SCRIPT.read_text()))

    def test_ninja_keeps_going_past_failures(self):
        # A build is ~an hour on the machine: one run reports every failing
        # step, not just the first.
        result, runs, files, tmp = dryrun()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ninja -k 0 -C', runs[index_of(runs, 'chrome_public_apk')])


def hash_of(*flags):
    return subprocess.run([sys.executable, str(REPO / 'android' / 'prep_hash.py'), *flags, str(REPO)],
                          capture_output=True, text=True, check=True).stdout.strip()


def build_in(work, *args):
    env = dict(os.environ, TARK_ANDROID_DRYRUN='1')
    result = subprocess.run(['bash', str(SCRIPT), *args, str(work)], capture_output=True, text=True, env=env)
    runs = [l[len('tark: run '):] for l in result.stdout.splitlines() if l.startswith('tark: run ')]
    return result, runs


class TestLayers(unittest.TestCase):
    """The base (Chromium, toolchains, core patches) is kept in src-base;
    when only Tark's layer changed, it is put back and applied again
    (android/layers.py), out/ kept."""

    def test_a_new_base_is_kept_after_the_core_patches(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertEqual(result.returncode, 3, result.stderr)
        core = index_of(runs, 'ungoogled-chromium/patches')
        copy = index_of(runs, f'cp -a {tmp}/src {tmp}/src-base')
        tark = index_of(runs, f'{tmp}/tark-patches')
        self.assertLess(core, copy)
        self.assertLess(copy, tark)
        self.assertLess(index_of(runs, '_install_xlit'), index_of(runs, 'layers.py settle'))
        self.assertNotIn('layers.py reset', '\n'.join(runs))
        self.assertEqual(files['base_stamp'].strip(), hash_of('--base'))

    def test_base_reused_when_only_tarks_layer_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / 'base.stamp').write_text(hash_of('--base') + '\n')
            (work / 'src-base').mkdir()
            (work / 'src' / 'out' / 'Default').mkdir(parents=True)
            (work / 'prepared.stamp').write_text('an older preparation\n')
            result, runs = build_in(work, '--stop-before-gn')
            self.assertEqual(result.returncode, 3, result.stderr)
            joined = '\n'.join(runs)
            for absent in ('clone.py', 'gclient sync', 'update_rust.py', 'ungoogled-chromium/patches',
                           'rm -rf', 'cp -a'):
                self.assertNotIn(absent, joined)
            order = [index_of(runs, n) for n in (
                f'layers.py reset {tmp}/src-base {tmp}/src {tmp}/layers.json',
                f'{tmp}/tark-patches',
                'utils/domain_substitution.py apply',
                'utils/name_substitution.py --sub',
                '_install_xlit',
                f'layers.py settle {tmp}/src-base {tmp}/src {tmp}/layers.json',
            )]
            self.assertEqual(order, sorted(order))
            self.assertEqual((work / 'prepared.stamp').read_text().strip(), hash_of())
            self.assertTrue((work / 'src' / 'out' / 'Default').is_dir())

    def test_a_changed_base_wipes_the_tree_and_its_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / 'base.stamp').write_text('an older base\n')
            (work / 'src-base').mkdir()
            (work / 'src').mkdir()
            (work / 'src' / 'old-file').write_text('x')
            (work / 'layers.json').write_text('{}')
            result, runs = build_in(work, '--stop-before-gn')
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn(f'rm -rf {tmp}/src {tmp}/src-base', runs)
            self.assertIn('clone.py', '\n'.join(runs))
            self.assertNotIn('layers.py reset', '\n'.join(runs))
            self.assertFalse((work / 'layers.json').exists())

    def test_a_missing_copy_means_a_new_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / 'base.stamp').write_text(hash_of('--base') + '\n')
            result, runs = build_in(work, '--stop-before-gn')
            self.assertIn('clone.py', '\n'.join(runs))

    def test_a_layer_cut_short_is_never_taken_as_prepared(self):
        # The stamp goes before the layer is put back, and is written only
        # once Tark's layer is settled.
        s = SCRIPT.read_text()
        self.assertLess(s.index('rm -f "$stamp"'), s.index('layers.py" reset'))
        self.assertLess(s.index('layers.py" settle'), s.index('echo "$prep" > "$stamp"'))

    def test_base_hash_covers_only_the_base(self):
        sys.path.insert(0, str(REPO / 'android'))
        import prep_hash
        section = prep_hash.base_section(SCRIPT.read_text())
        for step in ('clone.py', 'sync --nohooks', 'update_rust.py', 'install-sysroot.py', 'ungoogled-chromium/patches'):
            self.assertIn(step if step != 'ungoogled-chromium/patches' else '$_main_repo/patches', section)
        for step in ('tark-patches', 'domain_substitution.py', 'name_substitution.py', '_install_xlit', 'settle'):
            self.assertNotIn(step, section)
        self.assertTrue(set(prep_hash.BASE_INPUTS) <= set(prep_hash.INPUTS))
        self.assertIn('android/layers.py', prep_hash.INPUTS)
        for f in prep_hash.BASE_INPUTS:
            self.assertFalse(f.startswith(('android/patches', 'patches/', 'utils/', 'resources/')), f)
        self.assertNotEqual(hash_of('--base'), hash_of())


if __name__ == '__main__':
    unittest.main()

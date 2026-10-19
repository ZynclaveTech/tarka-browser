"""A1: android/build.sh runs the Android build's steps in order. With
TARK_ANDROID_DRYRUN=1 every external command is printed ("tark: run ...")
instead of run, so the order is tested on the Mac without a Chromium tree."""
import os
import pathlib
import subprocess
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
            'utils/prune_binaries.py',
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
        self.assertLess(sync, index_of(runs, 'utils/prune_binaries.py'))
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

    def test_core_patches_then_tark_series(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        apply = runs[index_of(runs, 'utils/patches.py apply')]
        core = apply.index('ungoogled-chromium/patches')
        tark = apply.index(f'{tmp}/tark-patches')
        self.assertLess(core, tark)
        self.assertNotIn('tarka/updater/sparkle.patch', files['series'])
        self.assertIn('tarka/omnibox-translit/translit-provider.patch', files['series'])

    def test_no_ublock_on_android(self):
        result, runs, files, tmp = dryrun('--stop-before-gn')
        self.assertNotIn('downloads-tark.ini', '\n'.join(runs))
        self.assertNotIn('ublock', '\n'.join(runs).lower())

    def test_full_build_writes_args_and_builds_the_apk(self):
        result, runs, files, tmp = dryrun()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('enable_hangout_services_extension=false', files['args'])  # core flags.gn
        self.assertIn('chrome_public_manifest_package = "com.gettarka.tarka"', files['args'])
        gn = index_of(runs, 'gn gen')
        ninja = index_of(runs, 'chrome_public_apk')
        self.assertLess(index_of(runs, '_install_xlit'), gn)
        self.assertLess(gn, ninja)


if __name__ == '__main__':
    unittest.main()

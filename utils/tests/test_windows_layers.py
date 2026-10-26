"""W1: windows/layered_build.py builds Windows as Android does: a kept base
(Chromium, ungoogled-chromium's core patches, the Windows platform patches)
and Tark's layer applied again on every run, so a change to Tark's patches
rebuilds only what it changed (android/layers.py keeps unchanged files'
times; out/ is kept)."""
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'windows'))
import layered_build  # noqa: E402


def make_work(root):
    """The files of a workdir (prepare_workdir.py) that the base hash reads."""
    w = pathlib.Path(root)
    for rel, text in {
        'ungoogled-chromium/chromium_version.txt': '156.0.8078.47\n',
        'ungoogled-chromium/downloads.ini': '[chromium]\n',
        'ungoogled-chromium/pruning.list': 'a\n',
        'ungoogled-chromium/patches/series': 'core/a.patch\n',
        'ungoogled-chromium/patches/core/a.patch': 'core a\n',
        'ungoogled-chromium/utils/patches.py': '#\n',
        'downloads.ini': '[x]\n',
        'pruning.list': 'b\n',
        'build.py': '# build\n',
        'patches/series': 'ungoogled-chromium/windows/w.patch\ntarka/core/t.patch\n',
        'patches/ungoogled-chromium/windows/w.patch': 'windows w\n',
        'patches/tarka/core/t.patch': 'tark t\n',
        'tark_post_patch.py': '# hook\n',
        'tark_repo.txt': str(REPO) + '\n',
    }.items():
        p = w / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return w


class FakeRunner:
    def __init__(self):
        self.steps = []

    def __call__(self, step, *args, env=None):
        phase = (env or {}).get('TARK_PHASE')
        self.steps.append(f'{step}:{phase}' if phase else step)


class TestBaseHash(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = make_work(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tark_patches_and_hook_are_not_the_base(self):
        before = layered_build.base_hash(self.work)
        (self.work / 'patches/tarka/core/t.patch').write_text('tark t, changed\n')
        (self.work / 'tark_post_patch.py').write_text('# hook, changed\n')
        series = self.work / 'patches/series'
        series.write_text(series.read_text() + 'tarka/core/u.patch\n')
        self.assertEqual(layered_build.base_hash(self.work), before)

    def test_core_and_platform_patches_are_the_base(self):
        for rel in ('ungoogled-chromium/patches/core/a.patch', 'patches/ungoogled-chromium/windows/w.patch',
                    'ungoogled-chromium/chromium_version.txt', 'downloads.ini', 'build.py'):
            before = layered_build.base_hash(self.work)
            (self.work / rel).write_text('changed ' + rel + '\n')
            self.assertNotEqual(layered_build.base_hash(self.work), before, rel)


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = make_work(self.tmp.name)
        self.runner = FakeRunner()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kwargs):
        layered_build.run(self.work, runner=self.runner, **kwargs)
        return self.runner.steps

    def test_first_run_makes_and_keeps_the_base(self):
        steps = self.build()
        self.assertEqual(steps, ['build.py:base', 'copy-base', 'build.py:layer', 'settle', 'build.py:build'])
        self.assertEqual((self.work / 'build' / 'base.stamp').read_text().strip(),
                         layered_build.base_hash(self.work))

    def test_same_base_applies_only_the_layer(self):
        self.build()
        (self.work / 'build' / 'src-base').mkdir(parents=True, exist_ok=True)
        self.runner.steps.clear()
        steps = self.build()
        self.assertEqual(steps, ['reset', 'build.py:layer', 'settle', 'build.py:build'])

    def test_a_changed_base_starts_again(self):
        self.build()
        (self.work / 'build' / 'src-base').mkdir(parents=True, exist_ok=True)
        (self.work / 'patches/ungoogled-chromium/windows/w.patch').write_text('windows w, changed\n')
        self.runner.steps.clear()
        steps = self.build()
        self.assertEqual(steps[0], 'wipe')
        self.assertEqual(steps[1:3], ['build.py:base', 'copy-base'])

    def test_a_missing_base_copy_starts_again(self):
        self.build()
        self.runner.steps.clear()
        self.assertEqual(self.build()[:3], ['wipe', 'build.py:base', 'copy-base'])

    def test_a_tree_without_a_stamp_starts_again(self):
        # A run cut short after the base (or before it was copied) leaves a
        # tree but no stamp: it is wiped, never patched twice.
        (self.work / 'build' / 'src').mkdir(parents=True)
        self.assertEqual(self.build()[:3], ['wipe', 'build.py:base', 'copy-base'])

    def test_the_base_copy_keeps_links_as_links(self):
        # Chromium's tree has symbolic links; robocopy follows them without
        # /SL and is refused.
        self.assertIn('/SL', layered_build.ROBOCOPY_FLAGS)
        self.assertIn('/COPY:DAT', layered_build.ROBOCOPY_FLAGS)
        self.assertIn('/DCOPY:DAT', layered_build.ROBOCOPY_FLAGS)

    def test_fresh_starts_again(self):
        self.build()
        (self.work / 'build' / 'src-base').mkdir(parents=True, exist_ok=True)
        self.runner.steps.clear()
        self.assertEqual(self.build(fresh=True)[:3], ['wipe', 'build.py:base', 'copy-base'])

    def test_patch_only_stops_before_gn(self):
        steps = self.build(patch_only=True)
        self.assertNotIn('build.py:build', steps)
        self.assertEqual(steps[-1], 'settle')

    def test_stale_name_substitution_backup_is_cleared_before_the_layer(self):
        backup = self.work / 'build' / 'namesubs.tar'
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text('old')
        self.build()
        self.assertFalse(backup.exists())


class TestWipe(unittest.TestCase):
    def test_wipe_removes_read_only_entries(self):
        # git's objects (bindgen's checkout) are read-only, which rmtree
        # cannot delete on Windows; a read-only folder fails it here too.
        import os
        import stat
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            locked = work / 'build' / 'src' / 'third_party' / 'x' / '.git' / 'objects'
            locked.mkdir(parents=True)
            (locked / 'pack').write_text('object')
            os.chmod(locked / 'pack', stat.S_IREAD)
            os.chmod(locked, stat.S_IREAD | stat.S_IEXEC)
            layered_build._system_runner(work, 1)('wipe')
            self.assertFalse((work / 'build' / 'src').exists())


class TestBuildPyPhases(unittest.TestCase):
    """Tark's local change to upstream's build.py: TARK_PHASE splits it."""

    def setUp(self):
        self.text = (REPO / 'windows' / 'upstream' / 'build.py').read_text()

    def test_phases_are_read(self):
        self.assertIn("os.environ.get('TARK_PHASE')", self.text)

    def test_base_skips_the_layer_and_stops_before_ninja(self):
        # The base runs everything but Tark's layer and ninja: the Rust
        # toolchain, bindgen and gn are base, so a layer reset never touches
        # them (new times there would rebuild every Rust target).
        main = self.text[self.text.index('def main():'):]
        self.assertIn("if tark_phase != 'base':\n            _tark_substitute_and_hook(args, source_tree)", main)
        base_exit = main.index("if tark_phase == 'base':\n        return")
        self.assertLess(main.index('bindgen.exe'), base_exit)
        self.assertLess(base_exit, main.index("ninja_commandline = ["))
        self.assertNotIn("if tark_phase == 'base':\n            return", main)

    def test_layer_applies_only_tarks_entries(self):
        self.assertIn("if e.strip().startswith('tarka/')]", self.text)
        self.assertIn("not e.strip().startswith(('#', 'tarka/'))", self.text)

    def test_build_phase_has_no_ci_timeout(self):
        self.assertIn("if args.ci:\n        _run_build_process_timeout", self.text)


if __name__ == '__main__':
    unittest.main()

"""L1: android/aws/jobs/tark-linux-build.sh builds Tark for Linux on the
Android build machine. It must share the machine without touching Android's
work: one job at a time (the same lock), its own folder, and a refusal when
the disk is too full for a Chromium tree."""
import os
import pathlib
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
JOB = REPO / 'android' / 'aws' / 'jobs' / 'tark-linux-build.sh'
SUB = '0' * 40


def run(root, *extra, free_gb=400, env=None):
    e = dict(os.environ, TARK_ROOT=str(root), TARK_FREE_GB=str(free_gb), **(env or {}))
    return subprocess.run(['bash', str(JOB), 'bucket', 'jobs/x', SUB, '--dry-run', *extra],
                          capture_output=True, text=True, env=e)


class TestLinuxJob(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_plans_the_build_in_its_own_folder(self):
        r = run(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'work {self.root}/linux/tl', r.stdout)
        self.assertIn(f'repo {self.root}/linux/repo', r.stdout)

    def test_package_only_skips_the_build(self):
        r = run(self.root, '--package-only')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('package only', r.stdout)

    def test_never_names_androids_folders(self):
        text = JOB.read_text()
        for android in ('/tark/work', '/tark/repo', '$ROOT/work', '$ROOT/repo'):
            self.assertNotIn(android, text)

    def test_refuses_while_another_job_holds_the_lock(self):
        lock = self.root / 'job.lock'
        lock.touch()
        holder = subprocess.Popen(['flock', str(lock), 'sleep', '5']) if \
            subprocess.run(['which', 'flock'], capture_output=True).returncode == 0 else None
        if holder is None:
            self.skipTest('no flock(1) on this machine')
        try:
            import time
            time.sleep(0.3)
            r = run(self.root)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('another Tark job is running', r.stdout + r.stderr)
        finally:
            holder.kill()

    def test_clears_earlier_output_before_packaging(self):
        # A tarball left by an earlier run must never be checked or uploaded
        # as this job's.
        text = JOB.read_text()
        clear = text.find('rm -rf "$L/out" "$L/checks"')
        self.assertNotEqual(clear, -1)
        self.assertLess(clear, text.find('package_tarball.sh" "$repo"'))

    def test_fresh_also_drops_the_name_substitution_backup(self):
        # name_substitution.py --sub refuses to run when its backup exists.
        text = JOB.read_text()
        self.assertIn('rm -rf "$work/build/src" "$work/build/namesubs.tar"', text)

    def test_runs_the_captions_tests_before_packaging(self):
        text = JOB.read_text()
        tests = text.find('linux/run_tests.sh')
        self.assertNotEqual(tests, -1)
        self.assertLess(tests, text.find('package_tarball.sh" "$repo"'))

    def test_refuses_below_150_gb_free(self):
        r = run(self.root, free_gb=149)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('150 GB', r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()

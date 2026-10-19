"""A1: the Android build machine's scripts (android/aws/). Static checks only:
the machine is reachable over SSM alone, sized as approved, stops itself,
and is created only after the user's OK."""
import pathlib
import re
import subprocess
import unittest

AWS = pathlib.Path(__file__).resolve().parents[2] / 'android' / 'aws'


def text(name):
    return (AWS / name).read_text()


class TestCreate(unittest.TestCase):
    def setUp(self):
        self.s = text('create.sh')

    def test_needs_the_users_ok(self):
        # The instance costs money: create.sh refuses without TARK_ANDROID_APPROVED=1.
        self.assertIn('TARK_ANDROID_APPROVED', self.s)
        result = subprocess.run(['zsh', str(AWS / 'create.sh')], capture_output=True, text=True,
                                env={'PATH': '/usr/bin:/bin'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TARK_ANDROID_APPROVED', result.stderr)

    def test_machine(self):
        self.assertIn('ubuntu-noble-24.04-amd64', self.s)
        self.assertIn('${TARK_ANDROID_TYPE:-c7i.16xlarge}', self.s)
        self.assertRegex(self.s, r'VolumeSize["\']?\s*[:=]\s*500')
        self.assertIn('gp3', self.s)
        self.assertIn('--instance-initiated-shutdown-behavior stop', self.s)
        self.assertIn('tark-android-builder', self.s)

    def test_ssm_only_no_inbound(self):
        self.assertIn('AmazonSSMManagedInstanceCore', self.s)
        self.assertNotIn('authorize-security-group-ingress', self.s)
        self.assertNotRegex(self.s, r'--key-name')

    def test_bucket_scoped_access(self):
        self.assertIn('tark-android-builds-', self.s)
        self.assertNotIn('AmazonS3FullAccess', self.s)


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.s = text('bootstrap.sh')

    def test_build_deps_and_swap(self):
        self.assertIn('install-build-deps', self.s)
        self.assertIn('--android', self.s)
        self.assertIn('swapon', self.s)
        self.assertIn('libarchive-tools', self.s)  # bsdtar, for .zip downloads
        # install-build-deps.sh execs the .py directly: both must be executable.
        self.assertIn('chmod +x install-build-deps.sh install-build-deps.py', self.s)
        # googlesource answers 503 under load: the fetch retries.
        self.assertIn('--retry 8 --retry-delay 15 --retry-all-errors', self.s)

    def test_idle_watchdog_30_minutes(self):
        self.assertIn('tark-idle-stop', self.s)
        self.assertRegex(self.s, r'OnUnitActiveSec=10min')
        self.assertRegex(self.s, r'-ge 3')
        self.assertIn('poweroff', self.s)


class TestDriverAndJob(unittest.TestCase):
    def test_driver_subcommands(self):
        s = text('andbuild.sh')
        for sub in ('status)', 'start)', 'job)', 'wait)', 'fetch)', 'stop)'):
            self.assertIn(sub, s)
        self.assertIn('AWS-RunShellScript', s)
        self.assertIn('tark-android-builder', s)
        self.assertIn('git archive', s)  # the source goes over S3, not GitHub

    def test_job(self):
        s = text('jobs/tark-build.sh')
        self.assertIn('android/build.sh', s)
        self.assertIn('--stop-before-gn', s)
        self.assertIn('ChromePublic.apk', s)
        self.assertIn('tark-build.log', s)
        self.assertIn('poweroff', s)
        self.assertIn('cd /tark', s)  # never the SSM agent's folder

    def test_driver_archive_in_private_temp_dir(self):
        s = text('andbuild.sh')
        self.assertIn('mktemp -d', s)
        self.assertNotIn('/tmp/tark-src-$$', s)

    def test_job_setup_is_fatal_and_pins_the_submodule(self):
        s = text('jobs/tark-build.sh')
        # The exact commit is fetched, checked out, and verified before building.
        self.assertIn('fetch --quiet origin "$SUB"', s)
        self.assertIn('rev-parse HEAD', s)
        self.assertIn('must ', s)
        for step in ('aws s3 cp --quiet "s3://$B/$P/src.tar.gz"', 'tar -xzf', 'git clone'):
            line = next(l for l in s.splitlines() if step in l)
            self.assertTrue(line.lstrip().startswith(('must ', '[[')), line)

    def test_shell_syntax(self):
        for name in ('create.sh', 'andbuild.sh'):
            self.assertEqual(subprocess.run(['zsh', '-n', str(AWS / name)]).returncode, 0, name)
        for name in ('bootstrap.sh', 'jobs/tark-build.sh'):
            self.assertEqual(subprocess.run(['bash', '-n', str(AWS / name)]).returncode, 0, name)


if __name__ == '__main__':
    unittest.main()

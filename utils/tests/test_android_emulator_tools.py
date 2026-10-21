"""A4 Task 0: the A1 emulator checks as tools (android/emulator/). They default
to the emulator and never act on a real phone by accident: the first A1
install went to the user's phone because adb was given no serial."""
import os
import pathlib
import subprocess
import sys
import unittest

EMU = pathlib.Path(__file__).resolve().parents[2] / 'android' / 'emulator'


class TestEmulatorTools(unittest.TestCase):
    def test_files(self):
        for name in ('walk_settings.py', 'session.sh', 'README.md'):
            self.assertTrue((EMU / name).is_file(), name)

    def test_session_defaults_to_the_emulator(self):
        s = (EMU / 'session.sh').read_text()
        self.assertIn('${TARK_SERIAL:-emulator-5554}', s)
        self.assertIn('-s "$serial"', s)

    def test_session_refuses_a_phone(self):
        # The capture is the emulator console's: a phone is refused outright.
        env = dict(os.environ, TARK_SERIAL='bf678949', PATH='/usr/bin:/bin')
        result = subprocess.run(['bash', str(EMU / 'session.sh'), 'run'], capture_output=True,
                                text=True, env=env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('emulator', result.stderr)

    def test_walk_refuses_a_phone_unless_asked(self):
        result = subprocess.run([sys.executable, str(EMU / 'walk_settings.py'), '--serial', 'bf678949'],
                                capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('--allow-device', result.stderr)


if __name__ == '__main__':
    unittest.main()

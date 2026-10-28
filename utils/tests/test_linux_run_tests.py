"""L2: linux/run_tests.sh judges each test program by its exit code and its
summary: Chromium's test launcher ends with "SUCCESS: all tests passed.",
gtest run in one process with "[  PASSED  ] N tests."."""
import os
import pathlib
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'linux' / 'run_tests.sh'


def program(path, text, code=0):
    path.write_text(f'#!/bin/sh\ncat <<"OUT"\n{text}\nOUT\nexit {code}\n')
    path.chmod(0o755)


class TestRunTests(unittest.TestCase):
    def run_with(self, captions, captions_code=0):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        out = root / 'src' / 'out' / 'Default'
        out.mkdir(parents=True)
        fonts = root / 'src' / 'third_party' / 'test_fonts' / 'test_fonts'
        fonts.mkdir(parents=True)
        (fonts / 'Ahem.ttf').write_text('font')
        program(out / 'tark_captions_unittests', captions, captions_code)
        program(out / 'tark_speech_unittests', '[1/1] A.B (0 ms)\nSUCCESS: all tests passed.')
        program(out / 'tark_xlit_unittests', '[==========] 2 tests ran.\n[  PASSED  ] 2 tests.')
        bin_dir = root / 'bin'
        bin_dir.mkdir()
        program(bin_dir / 'ninja', '')
        program(bin_dir / 'curl', '', 1)
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}')
        return subprocess.run(['bash', str(SCRIPT), str(root / 'src'), str(root / 'report')],
                              capture_output=True, text=True, env=env).stdout

    def test_the_launchers_success_line_passes(self):
        out = self.run_with('[211/211] A.B (0 ms)\nSUCCESS: all tests passed.')
        self.assertIn('ok captions', out)
        self.assertIn('ok speech', out)
        self.assertIn('ok xlit', out)

    def test_a_failing_program_fails(self):
        self.assertIn('FAIL captions', self.run_with('1 test failed', 1))

    def test_no_summary_fails(self):
        self.assertIn('FAIL captions', self.run_with('nothing ran'))


if __name__ == '__main__':
    unittest.main()

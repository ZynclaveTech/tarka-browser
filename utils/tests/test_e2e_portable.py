"""L4: the desktop end-to-end checks (utils/adblock_e2e.py, utils/zynclave_e2e.py)
run Tark on Linux too: from the tarball's folder, and against production
Zynclave, which a release build uses."""
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'utils'))
import adblock_e2e  # noqa: E402
import zynclave_e2e  # noqa: E402


class TestBinary(unittest.TestCase):
    def test_mac_app(self):
        self.assertEqual(adblock_e2e.binary_of('/x/Tark.app'), pathlib.Path('/x/Tark.app/Contents/MacOS/Tark'))

    def test_linux_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = pathlib.Path(tmp) / 'tark'
            launcher.write_text('#!/bin/sh\n')
            self.assertEqual(adblock_e2e.binary_of(tmp), launcher)


class TestZynclaveServers(unittest.TestCase):
    def test_staging_for_dev_builds(self):
        s = zynclave_e2e.servers(production=False)
        self.assertEqual(s['auth'], 'auth.staging.zynclave.com')
        self.assertEqual(s['client_id'], '254e0cf8-e515-4ea8-846c-86b5510c5499')
        self.assertEqual(s['login'], 'https://accounts.staging.zynclave.com/login')

    def test_production_for_release_builds(self):
        s = zynclave_e2e.servers(production=True)
        self.assertEqual(s['auth'], 'auth.zynclave.com')
        self.assertEqual(s['client_id'], 'f6beeeca-b521-4360-a39e-48257675b6c1')
        self.assertEqual(s['login'], 'https://accounts.zynclave.com/login')


if __name__ == '__main__':
    unittest.main()

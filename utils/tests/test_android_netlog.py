"""A1 Task 6: android/check_netlog.sh checks an Android net log against
android/allowed_hosts.txt with the Mac's checker (utils/net_hosts.py)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CHECK = REPO / 'android' / 'check_netlog.sh'
sys.path.insert(0, str(REPO / 'utils'))
from net_hosts import load_allowed  # noqa: E402

TYPES = {"HOST_RESOLVER_MANAGER_REQUEST": 1, "URL_REQUEST_START_JOB": 2}


def netlog(*hosts):
    return {"constants": {"logEventTypes": TYPES},
            "events": [{"type": 1, "params": {"host": h}} for h in hosts]}


class TestCheckNetlog(unittest.TestCase):
    def run_check(self, log):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'netlog.json'
            path.write_text(json.dumps(log))
            return subprocess.run(['bash', str(CHECK), str(path)], capture_output=True, text=True)

    def test_google_host_fails(self):
        result = self.run_check(netlog('shodhya.com', 'clients4.google.com'))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('clients4.google.com', result.stdout)

    def test_shodhya_only_passes(self):
        result = self.run_check(netlog('shodhya.com', 'api.shodhya.com'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_usage(self):
        result = subprocess.run(['bash', str(CHECK)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('usage', result.stderr)


class TestAllowedHosts(unittest.TestCase):
    def test_mac_list_without_ublock_and_web_store(self):
        android = load_allowed(REPO / 'android' / 'allowed_hosts.txt')
        mac = load_allowed(REPO / 'utils' / 'allowed_hosts.txt')
        self.assertLessEqual(android, mac)
        self.assertIn('shodhya.com', android)
        self.assertIn('api.shodhya.com', android)
        # Widevine on Android comes from the OS (MediaDrm), not the component
        # updater: its desktop hosts would only hide updater traffic.
        for gone in ('update.googleapis.com', 'edgedl.me.gvt1.com',
                     'chromewebstore.google.com', 'clients2.google.com',
                     'ublockorigin.github.io', 'cdn.jsdelivr.net', 'raw.githubusercontent.com'):
            self.assertNotIn(gone, android)


if __name__ == '__main__':
    unittest.main()

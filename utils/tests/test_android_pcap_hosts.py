"""A1 Task 6: android/pcap_hosts.py lists the names a whole-device capture
(emulator -tcpdump) looked up in DNS and checks them against
android/allowed_hosts.txt. It sees what the net log cannot: Android's own
HTTP stack and Play Services."""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / 'android' / 'pcap_hosts.py'
sys.path.insert(0, str(REPO / 'android'))


def dns_query(name, qid=1):
    labels = b''.join(bytes([len(p)]) + p.encode() for p in name.split('.')) + b'\0'
    return struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0) + labels + struct.pack('>HH', 1, 1)


def dns_response(name):
    q = dns_query(name)
    return q[:2] + struct.pack('>H', 0x8180) + q[4:]


def udp_ipv4(payload, dport=53, sport=40000):
    udp = struct.pack('>HHHH', sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack('>BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
                     bytes([10, 0, 2, 15]), bytes([10, 0, 2, 3]))
    return ip + udp


def udp_ipv6(payload, dport=53):
    udp = struct.pack('>HHHH', 40000, dport, 8 + len(payload), 0) + payload
    return struct.pack('>IHBB16s16s', 0x60000000, len(udp), 17, 64, b'\0' * 15 + b'\1',
                       b'\0' * 15 + b'\2') + udp


def ethernet(packet, ethertype):
    return b'\x02' * 6 + b'\x04' * 6 + struct.pack('>H', ethertype) + packet


def pcap(frames):
    out = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    for f in frames:
        out += struct.pack('<IIII', 0, 0, len(f), len(f)) + f
    return out


class TestPcapHosts(unittest.TestCase):
    def write(self, frames):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / 'cap.pcap'
        path.write_bytes(pcap(frames))
        return path

    def test_queries_over_ipv4_and_ipv6(self):
        import pcap_hosts
        path = self.write([ethernet(udp_ipv4(dns_query('shodhya.com')), 0x0800),
                           ethernet(udp_ipv6(dns_query('Clients4.Google.com.')), 0x86dd)])
        self.assertEqual(set(pcap_hosts.queried_hosts(path)), {'shodhya.com', 'clients4.google.com'})

    def test_responses_and_other_ports_are_not_queries(self):
        import pcap_hosts
        path = self.write([ethernet(udp_ipv4(dns_response('a.example')), 0x0800),
                           ethernet(udp_ipv4(dns_query('b.example'), dport=5353), 0x0800)])
        self.assertEqual(pcap_hosts.queried_hosts(path), {})

    def test_check_fails_on_google_and_passes_on_shodhya(self):
        bad = self.write([ethernet(udp_ipv4(dns_query('clientservices.googleapis.com')), 0x0800)])
        result = subprocess.run([sys.executable, str(TOOL), str(bad)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('clientservices.googleapis.com', result.stdout)
        good = self.write([ethernet(udp_ipv4(dns_query('api.shodhya.com')), 0x0800)])
        result = subprocess.run([sys.executable, str(TOOL), str(good)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_baseline_names_are_left_out(self):
        # The emulator's own traffic (an idle capture) is not Tark's.
        run = self.write([ethernet(udp_ipv4(dns_query('pool.ntp.org')), 0x0800),
                          ethernet(udp_ipv4(dns_query('shodhya.com')), 0x0800)])
        idle = self.write([ethernet(udp_ipv4(dns_query('pool.ntp.org')), 0x0800)])
        result = subprocess.run([sys.executable, str(TOOL), str(run), '--baseline', str(idle)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('pool.ntp.org', result.stdout.split('Left out')[0])
        self.assertIn('shodhya.com', result.stdout)

    def test_baseline_never_hides_google(self):
        # Final review: Android's own idle traffic includes Google names; the
        # baseline must not hide Tark contacting the same ones.
        run = self.write([ethernet(udp_ipv4(dns_query('www.google.com')), 0x0800)])
        idle = self.write([ethernet(udp_ipv4(dns_query('www.google.com')), 0x0800)])
        result = subprocess.run([sys.executable, str(TOOL), str(run), '--baseline', str(idle)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('www.google.com', result.stdout.split('Not on the allowed list:')[1])

    def test_every_google_name_is_google(self):
        # Review (2026-10-21): names where "google" is not a whole label, and
        # Google's other domains, were taken for strangers to Google, so the
        # idle baseline could hide Tark contacting them.
        import pcap_hosts
        for host in ('google-analytics.com', 'www.googletagmanager.com', 'googleadservices.com',
                     'rr1---sn-ab.googlevideo.com', 'youtu.be', 'android.com', 'www.android.com',
                     'myapp.firebaseio.com', 'x.firebaseapp.com', 'app-measurement.com',
                     'www.google.co.in', 'fonts.gstatic.com', 'redirector.gvt1.com', 'lh3.ggpht.com',
                     'ad.doubleclick.net', 'goo.gl', 'www.gmail.com', 'www.recaptcha.net'):
            self.assertTrue(pcap_hosts.is_google(host), host)
        for host in ('shodhya.com', 'gettarka.com', 'pool.ntp.org', 'easylist.to', 'notandroid.com',
                     'mygoogle-fan.example'):
            self.assertFalse(pcap_hosts.is_google(host), host)

    def test_baseline_never_hides_googles_other_domains(self):
        run = self.write([ethernet(udp_ipv4(dns_query('www.google-analytics.com')), 0x0800)])
        idle = self.write([ethernet(udp_ipv4(dns_query('www.google-analytics.com')), 0x0800)])
        result = subprocess.run([sys.executable, str(TOOL), str(run), '--baseline', str(idle)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('www.google-analytics.com', result.stdout.split('Not on the allowed list:')[1])

    def test_os_host_is_named_and_shown(self):
        # A Google name Android itself looks up is left out only when named.
        run = self.write([ethernet(udp_ipv4(dns_query('android.googleapis.com')), 0x0800),
                          ethernet(udp_ipv4(dns_query('shodhya.com')), 0x0800)])
        idle = self.write([ethernet(udp_ipv4(dns_query('android.googleapis.com')), 0x0800)])
        result = subprocess.run([sys.executable, str(TOOL), str(run), '--baseline', str(idle),
                                 '--os-host', 'android.googleapis.com'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Left out (the idle baseline', result.stdout)
        self.assertIn('android.googleapis.com', result.stdout)

    def test_not_a_pcap(self):
        path = pathlib.Path(tempfile.mkdtemp()) / 'x.pcap'
        path.write_bytes(b'nope')
        result = subprocess.run([sys.executable, str(TOOL), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()

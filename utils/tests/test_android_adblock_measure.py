"""A2 Task 9: the measurement's pass marks (spec §4)."""
import pathlib
import sys
import unittest

MEASURE = pathlib.Path(__file__).resolve().parents[2] / 'android' / 'adblock' / 'measure'
sys.path.insert(0, str(MEASURE))
import report  # noqa: E402


def runs(*blocked, load=None):
    return [{'blocked': b, 'requests': 100, 'load_ms': load} for b in blocked]


class TestBlocked(unittest.TestCase):
    def test_95_percent_of_ubo_across_all_sites_passes(self):
        ubo = {'a': runs(100), 'b': runs(100)}
        tark = {'a': runs(100), 'b': runs(90)}
        *_, ratio, ok = report.blocked_report(tark, ubo)
        self.assertAlmostEqual(ratio, 0.95)
        self.assertTrue(ok)

    def test_less_fails(self):
        *_, ok = report.blocked_report({'a': runs(94)}, {'a': runs(100)})
        self.assertFalse(ok)

    def test_a_site_tark_did_not_load_counts_as_zero(self):
        rows, tt, tu, ratio, ok = report.blocked_report({}, {'a': runs(10)})
        self.assertEqual((tt, tu, ok), (0, 10, False))

    def test_medians_of_runs(self):
        rows, *_ = report.blocked_report({'a': runs(10, 20, 30)}, {'a': runs(5, 50, 50)})
        self.assertEqual(rows, [('a', 20, 50)])


class TestLoadTime(unittest.TestCase):
    def test_within_five_percent_passes(self):
        rows, ratio, ok = report.loadtime_report({'a': runs(0, load=1040)}, {'a': runs(0, load=1000)})
        self.assertTrue(ok)

    def test_slower_fails(self):
        *_, ok = report.loadtime_report({'a': runs(0, load=1100)}, {'a': runs(0, load=1000)})
        self.assertFalse(ok)

    def test_a_page_that_never_loaded_has_no_time(self):
        # loadEventEnd is 0 when the load never fired: the old tool wrote
        # 0 - navigationStart, a large negative number.
        on = {'a': [{'blocked': 0, 'requests': 1, 'load_ms': v} for v in (1000, -1792490828900, None)]}
        off = {'a': runs(0, load=1000)}
        rows, ratio, ok = report.loadtime_report(on, off)
        self.assertEqual(rows, [('a', 1000, 1000)])

    def test_measure_script_times_out_and_resumes(self):
        src = (MEASURE / 'measure.mjs').read_text()
        self.assertIn('timed out', src)
        self.assertIn("'--from'", src)
        self.assertIn('writeFileSync(outFile', src)


class TestSites(unittest.TestCase):
    def test_twenty_sites_with_youtube(self):
        sites = [l for l in (MEASURE / 'sites.txt').read_text().split('\n') if l and not l.startswith('#')]
        self.assertEqual(len(sites), 20)
        self.assertIn('https://m.youtube.com/', sites)


if __name__ == '__main__':
    unittest.main()

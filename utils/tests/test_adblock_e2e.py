"""utils/adblock_e2e.py reads a test page's results from its title."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import adblock_e2e  # noqa: E402


class TestResultsFromTitle(unittest.TestCase):
    def test_devtools_escapes_titles_as_html(self):
        self.assertEqual(adblock_e2e.results_from_title('done:{&quot;blocked&quot;:&quot;failed&quot;}'),
                         {'blocked': 'failed'})

    def test_a_page_still_running_has_no_results(self):
        self.assertIsNone(adblock_e2e.results_from_title('net.html'))

    def test_the_network_case_leaves_websockets_to_their_own(self):
        self.assertNotIn('ws', adblock_e2e.CASES['network'][1])
        self.assertEqual(adblock_e2e.CASES['websocket'][1], {'ws': 'failed'})


if __name__ == '__main__':
    unittest.main()

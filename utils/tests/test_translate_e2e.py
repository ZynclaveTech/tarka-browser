"""Desktop page translation's end-to-end check (utils/translate_e2e.py):
what counts as English, the page it serves, and where the models go."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import translate_e2e  # noqa: E402


class TestTranslateE2e(unittest.TestCase):
    def test_english_means_latin_words_and_no_devanagari(self):
        self.assertTrue(translate_e2e.english('India is a vast country.'))
        self.assertFalse(translate_e2e.english('भारत एक विशाल देश है।'))
        self.assertFalse(translate_e2e.english('India भारत'))
        self.assertFalse(translate_e2e.english(''))
        self.assertFalse(translate_e2e.english(None))

    def test_the_page_is_hindi_with_a_late_paragraph_and_a_link(self):
        page = translate_e2e.PAGE
        self.assertIn('<html lang="hi">', page)
        self.assertIn("p.id = 'late'", page)
        self.assertIn('<a id="a"', page)

    def test_the_profile_always_translates_hindi_into_english(self):
        self.assertEqual(translate_e2e.PREFS['translate_allowlists'], {'hi': 'en'})
        self.assertTrue(translate_e2e.PREFS['translate']['enabled'])

    def test_models_go_where_tark_looks(self):
        with tempfile.TemporaryDirectory() as models:
            (pathlib.Path(models) / 'it2_indic_en').mkdir()
            home = translate_e2e.models_home(models)
            self.assertTrue((home / 'tark' / 'Captions' / 'models' / 'it2_indic_en').is_dir())


if __name__ == '__main__':
    unittest.main()

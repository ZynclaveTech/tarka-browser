"""A4 (spec §13): Tark for Android looks like the Mac. Each Android-only look
patch is pinned here by the values the spec fixes."""
import pathlib
import re
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ANDROID = REPO / 'android'
sys.path.insert(0, str(ANDROID))


def series():
    import series as s  # android/series.py
    return s.series(REPO)


def patch(name):
    return (ANDROID / 'patches' / name).read_text()


def added(text):
    return '\n'.join(l[1:] for l in text.splitlines() if l.startswith('+') and not l.startswith('+++'))


class TestPaperPalette(unittest.TestCase):
    def setUp(self):
        self.assertIn('android/look-paper-palette.patch', series())
        self.p = patch('look-paper-palette.patch')
        self.add = added(self.p)

    def test_indigo_is_primary(self):
        self.assertIn('<color name="baseline_primary_40">#4338CA</color>', self.add)
        self.assertIn('<color name="baseline_primary_80">#8F88FF</color>', self.add)

    def test_paper_tokens(self):
        for name, light, dark in (('paper', 'F6F1E7', '12121C'), ('raised', 'FFFDF8', '1B1B29'),
                                  ('ink', '14142B', 'F3EFE6'), ('soft', '4D473D', 'BDB6A8'),
                                  ('rule', 'D9D0BF', '2C2C3D'), ('indigo', '4338CA', '8F88FF')):
            self.assertIn(f'<color name="tark_{name}_light">#{light}</color>', self.add)
            self.assertIn(f'<color name="tark_{name}_dark">#{dark}</color>', self.add)

    def test_surfaces_are_paper_and_raised(self):
        self.assertIn('<color name="gm3_baseline_surface_light">#F6F1E7</color>', self.add)
        self.assertIn('<color name="gm3_baseline_surface_dark">#12121C</color>', self.add)
        self.assertIn('<color name="gm3_baseline_surface_container_high_light">#FFFDF8</color>', self.add)
        self.assertIn('<color name="gm3_baseline_surface_container_high_dark">#1B1B29</color>', self.add)

    def test_dark_text_is_ink(self):
        # Review focus 1: text on dark paper is the Mac's ink.
        self.assertIn('<item name="colorOnSurface">@color/tark_ink_dark</item>', self.add)
        self.assertIn('<item name="colorOnSurface">@color/tark_ink_light</item>', self.add)
        self.assertIn('<item name="colorOutlineVariant">@color/tark_rule_dark</item>', self.add)

    def test_no_dynamic_colour(self):
        self.assertIn('private static final boolean TARK_DYNAMIC_COLORS = false;', self.add)
        self.assertIn('if (TARK_DYNAMIC_COLORS && shouldApplyDynamicColors()) {', self.add)
        self.assertIn('-        DynamicColors.applyToActivityIfAvailable(this);', self.p)
        self.assertIn('-        themedContext = DynamicColors.wrapContextIfAvailable(themedContext);', self.p)
        # Android 12+ resources no longer point at wallpaper colours.
        self.assertNotIn('material_dynamic_', self.add)


if __name__ == '__main__':
    unittest.main()

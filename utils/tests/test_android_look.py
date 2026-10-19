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


class TestAddressBar(unittest.TestCase):
    def setUp(self):
        self.assertIn('android/look-address-bar.patch', series())
        self.p = patch('look-address-bar.patch')
        self.add = added(self.p)

    def test_no_home_or_profile_button(self):
        self.assertIn('boolean defaultEnabled = false;', self.add)
        self.assertIn('mButtonDataProviders = List.of(adaptiveToolbarButtonController);', self.add)
        self.assertIn('-            mButtonDataProviders = List.of(identityDiscController, adaptiveToolbarButtonController);', self.p)

    def test_mark_is_the_menu_button(self):
        self.assertIn('android:src="@drawable/tark_mark_menu"', self.add)
        self.assertIn('-           app:tint="@color/default_icon_color_tint_list" />', self.p)
        # MenuButton cast the icon to BitmapDrawable: a vector would crash it.
        self.assertIn('-                (BitmapDrawable)', self.p)
        self.assertIn('-        ImageViewCompat.setImageTintList(mMenuImageButton, tintList);', self.p)

    def test_mark_vectors(self):
        for name in ('tark_mark_menu.xml', 'tark_mark_24dp.xml'):
            self.assertIn(name, self.p)
        # Three circles in the mid palette, no tint.
        for colour in ('#B78100', '#E63E5C', '#6C63FF'):
            self.assertEqual(self.p.count(f'android:fillColor="{colour}"'), 2, colour)

    def test_shodhya_shows_the_mark(self):
        # The user's report: Shodhya's favicon showed as a dark square.
        self.assertIn('"shodhya.com".equals(templateUrl.getKeyword())', self.add)
        self.assertIn('new StatusIconResource(R.drawable.tark_mark_24dp, Resources.ID_NULL)', self.add)

    def test_pill_hairline(self):
        self.assertIn('setHairlineBehavior(HairlineBehavior.SOLID)', self.add)
        self.assertIn('R.color.tark_rule_dark', self.add)


class TestAppIcon(unittest.TestCase):
    def setUp(self):
        self.assertIn('android/look-app-icon.patch', series())
        self.p = patch('look-app-icon.patch')

    def test_launcher_is_the_mark_on_dark_paper(self):
        self.assertEqual(self.p.count('+    <background android:drawable="@color/tark_paper_dark"/>'), 2)
        self.assertEqual(self.p.count('+    <foreground android:drawable="@mipmap/layered_app_icon_foreground"/>'), 1)
        # The Mac icon's dots: amber, coral, indigo of the dark palette.
        for colour in ('#FFC53D', '#FF6B85', '#8F88FF'):
            self.assertIn(f'android:fillColor="{colour}"', self.p)

    def test_themed_icon_is_the_mark(self):
        themed = self.p.split('+++ b/chrome/android/java/res_chromium_base/drawable/themed_app_icon.xml')[1]
        themed = themed.split('\n--- ')[0]
        self.assertEqual(themed.count('+        android:pathData="M'), 3)

    def test_in_app_icon_pngs(self):
        lines = (REPO / 'resources' / 'branding' / 'mark' / 'install.txt').read_text().splitlines()
        for size, dpi in ((48, 'mdpi'), (72, 'hdpi'), (96, 'xhdpi'), (144, 'xxhdpi'), (192, 'xxxhdpi')):
            path = f'chrome/android/java/res_chromium_base/mipmap-{dpi}/app_icon.png'
            self.assertIn(f'png {size}x{size} center mid {path}', lines)
            self.assertTrue((REPO / 'resources' / 'branding' / 'mark' / 'tree' / path).is_file(), path)


class TestMenu(unittest.TestCase):
    def setUp(self):
        self.assertIn('android/look-menu.patch', series())
        self.p = patch('look-menu.patch')
        self.add = added(self.p)

    def test_removed_items(self):
        for gone in ('            modelList.add(buildQuickDeleteItem());',
                     '            modelList.add(mHistoryItemBuilder.buildRecentTabsItem(shouldShowIconBeforeItem));',
                     '        modelList.add(buildHelpItem());',
                     '                    mMoreToolsItemBuilder.buildNtpCustomizationsItem(shouldShowIconBeforeItem));'):
            self.assertIn('-' + gone, self.p, gone)

    def test_tiles_type(self):
        self.assertIn('int TARK_TILES = AppMenuHandler.AppMenuItemType.NUM_ENTRIES + 3;', self.add)
        self.assertIn('TabbedAppMenuItemType.TARK_TILES,', self.add)
        self.assertIn('<item type="id" name="tark_tiles_menu_id" />', self.add)

    def test_tiles_use_the_old_items(self):
        # Review focus 3: each tile is the old item's own model, so a tap does
        # what the old row did (the menu's click handler, by menu item id).
        for builder in ('buildNewTabItem(isIncognitoForced).model', 'buildNewIncognitoTabItem().model',
                        'mHistoryItemBuilder.buildHistoryItem(shouldShowIconBeforeItem).model',
                        'buildDownloadsItem().model'):
            self.assertIn(builder, self.add)
        self.assertIn('handler.onItemClick(item)', self.add)
        self.assertIn('R.id.tark_tiles_menu_id', self.add)


if __name__ == '__main__':
    unittest.main()

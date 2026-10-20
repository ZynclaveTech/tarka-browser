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

    def test_controls_keep_3_to_1(self):
        # Final review: colorOutline draws off switches and field borders; the
        # rule colour gave 1.3:1. Faint keeps 5:1; hairlines stay on rule.
        self.assertIn('<item name="colorOutline">@color/tark_faint_light</item>', self.add)
        self.assertIn('<item name="colorOutline">@color/tark_faint_dark</item>', self.add)

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
        # Final review: a vector fills its bounds (no gravity): the mark is
        # centred at its own size, or it stretches while the toolbar slides.
        self.assertIn('mMenuImageButtonAnimationDrawable.getIntrinsicWidth()', self.add)

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

    def test_tiles_height_is_known_to_the_menu(self):
        # Final review: without a sizing supplier the menu counts the tiles as
        # one 48dp row and ends early.
        self.assertIn('customSizingSuppliers.append(', self.add.split('TabbedAppMenuItemType.TARK_TILES,')[1][:600])


class TestTabSwitcher(unittest.TestCase):
    def setUp(self):
        self.assertIn('android/look-tab-switcher.patch', series())
        self.p = patch('look-tab-switcher.patch')
        self.add = added(self.p)

    def test_pane_switcher_is_a_pill(self):
        self.assertIn('<corners android:radius="999dp" />', self.add)

    def test_cards_are_raised(self):
        # Paper cards: raised, not Chromium's darkest container.
        self.assertIn('SemanticColorUtils.getColorSurfaceContainerHigh(context)', self.add)
        self.assertIn('R.color.gm3_baseline_surface_container_high_dark', self.add)


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.assertIn('android/look-settings.patch', series())
        self.p = patch('look-settings.patch')
        self.add = added(self.p)

    def test_google_rows_gone(self):
        for key in ('PREF_SIGN_IN', 'PREF_GOOGLE_SERVICES', 'PREF_ACCOUNT_AND_GOOGLE_SERVICES_SECTION'):
            self.assertIn(f'removePreferenceIfPresent({key});', self.add)
        # Safety check is Google's checks.
        self.assertIn('-        return !DeviceInfo.isAutomotive();', self.p)
        # Final review: Settings search no longer finds them.
        self.assertIn('indexData.removeEntry(getUniqueId(PREF_GOOGLE_SERVICES));', self.add)

    def test_header_with_tiles(self):
        self.assertIn('mTarkHeader.setOrder(-1);', self.add)
        for key in ('search_engine', 'privacy', 'appearance', 'passwords', 'content_settings',
                    'languages', 'downloads', 'about_chrome'):
            self.assertIn(f'"{key}"', self.add.split('TARK_TILE_KEYS')[1], key)
        # Tiles open their row through its own listener or the fragment, never
        # Preference.performClick (restricted API: lint fails the build).
        self.assertNotIn('performClick', self.add)
        self.assertIn('onPreferenceTreeClick(row)', self.add)

    def test_tiles_even_and_narrow_gutters(self):
        # The user's phone: tiles had uneven heights and wide side padding.
        self.assertIn('root.setPaddingRelative(tarkDp(context, 12), 0, tarkDp(context, 12), 0);', self.add)
        self.assertIn('row.setBaselineAligned(false);', self.add)
        self.assertIn('0, ViewGroup.LayoutParams.MATCH_PARENT, 1f);', self.add)
        self.assertIn('tile.setMinimumHeight(tarkDp(context, 64));', self.add)
        # The user: an extra gap under the tiles, before the first section.
        self.assertIn('column.setPadding(0, tarkDp(context, 8), 0, 0);', self.add)

    def test_settings_rows_have_dividers(self):
        # The user: "no divider anywhere". Every settings screen draws the rule
        # hairline between rows, as on the Mac.
        self.assertIn('+++ b/chrome/browser/settings/android/java/src/org/chromium/chrome/browser/settings/ChromeBaseSettingsFragment.java', self.p)
        self.assertIn('+        // Tark: hairline dividers between settings rows, as on the Mac.\n+        return true;', self.p)

    def test_summary_strings_in_english_and_hindi(self):
        self.assertIn('name="IDS_TARK_SETTINGS_SUMMARY_TITLE"', self.add)
        self.assertIn('Private by default.', self.add)
        self.assertIn('name="IDS_TARK_SETTINGS_SUMMARY_DETAIL"', self.add)
        self.assertIn('डिफ़ॉल्ट रूप से निजी।', self.add)
        self.assertIn('Google नहीं · सिंक नहीं', self.add)


if __name__ == '__main__':
    unittest.main()


class TestConnects(unittest.TestCase):
    """The Mac's "What Tark connects to" on Android (spec §5.3)."""

    def setUp(self):
        self.p = (REPO / 'android' / 'patches' / 'look-connects.patch').read_text()

    def test_in_the_series(self):
        self.assertIn('look-connects.patch', (REPO / 'android' / 'patches' / 'series').read_text().split())

    def test_every_host_android_contacts_is_named(self):
        hosts = [l.strip() for l in (REPO / 'android' / 'allowed_hosts.txt').read_text().splitlines()
                 if l.strip() and not l.startswith('#')]
        english = ''.join(l for l in self.p.splitlines() if l.startswith('+        '))
        for host in hosts:
            self.assertIn(host, english, host)

    def test_english_and_hindi(self):
        for fp in ('7144670775258466422', '5542059870322282057', '3441881045024360042', '4695926840610114405'):
            self.assertIn(f'+<translation id="{fp}">', self.p)


sys.path.insert(0, str(ANDROID / 'emulator'))
import walk_settings  # noqa: E402


def _image(width, height, lines=(), background=(255, 253, 248)):
    """A raw screencap (16-byte header, RGBA) with grey lines: (y, x_from, x_to)."""
    import struct
    px = bytearray(bytes(background) + b'\xff') * (width * height)
    for y, x_from, x_to in lines:
        for x in range(x_from, x_to):
            i = (y * width + x) * 4
            px[i:i + 3] = bytes((200, 196, 188))
    return struct.pack('<IIII', width, height, 1, 0) + bytes(px)


class TestDividers(unittest.TestCase):
    """A3 Task 7 (the user: "add divider in all screens in settings")."""
    ITEMS = [(0, 0, 200, 40), (0, 40, 200, 80), (0, 80, 200, 120)]

    def test_screencap_with_either_header(self):
        img = walk_settings.parse_screencap(_image(4, 3))
        self.assertEqual(img[:2], (4, 3))
        legacy = _image(4, 3)[:12] + _image(4, 3)[16:]
        self.assertEqual(walk_settings.parse_screencap(legacy)[:2], (4, 3))

    def test_a_hairline_between_rows_is_found(self):
        img = walk_settings.parse_screencap(_image(200, 120, [(39, 16, 200)]))
        self.assertTrue(walk_settings.screen_has_dividers(img, self.ITEMS))

    def test_a_divider_in_the_gap_between_rows_is_found(self):
        # Found on the emulator: the hairline fills a 6 px gap between items.
        items = [(0, 0, 200, 40), (0, 46, 200, 86)]
        lines = [(y, 16, 200) for y in range(40, 46)]
        img = walk_settings.parse_screencap(_image(200, 90, lines))
        self.assertTrue(walk_settings.screen_has_dividers(img, items))

    def test_no_line_is_missing(self):
        img = walk_settings.parse_screencap(_image(200, 120))
        self.assertFalse(walk_settings.screen_has_dividers(img, self.ITEMS))

    def test_text_near_the_boundary_is_not_a_divider(self):
        # A short run of ink (a word) is not a line across the row.
        img = walk_settings.parse_screencap(_image(200, 120, [(39, 60, 100)]))
        self.assertFalse(walk_settings.screen_has_dividers(img, self.ITEMS))

    def test_rows_are_the_list_children(self):
        xml = ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][200,300]">'
               '<node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,0][200,300]">'
               '<node class="android.widget.LinearLayout" bounds="[0,0][200,40]">'
               '<node class="android.widget.TextView" bounds="[16,8][180,30]"/></node>'
               '<node class="android.widget.LinearLayout" bounds="[0,40][200,80]"/>'
               '</node></node></hierarchy>')
        self.assertEqual(walk_settings.list_items(xml), [(0, 0, 200, 40), (0, 40, 200, 80)])

    def test_rows_are_the_front_screens_list(self):
        # Found on the emulator: the screen behind keeps its list in the tree,
        # first; the one shown is the last.
        xml = ('<hierarchy>'
               '<node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,0][200,300]">'
               '<node class="android.widget.LinearLayout" bounds="[0,0][200,40]"/></node>'
               '<node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,0][200,300]">'
               '<node class="android.widget.LinearLayout" bounds="[0,10][200,50]"/>'
               '<node class="android.widget.LinearLayout" bounds="[0,50][200,90]"/></node>'
               '</hierarchy>')
        self.assertEqual(walk_settings.list_items(xml), [(0, 10, 200, 50), (0, 50, 200, 90)])

    def test_dividers_forced_where_settings_reads_them(self):
        patch = (ANDROID / 'patches' / 'look-settings-dividers.patch').read_text()
        self.assertIn('+++ b/chrome/android/java/src/org/chromium/chrome/browser/settings/WideDisplayPadding.java', patch)
        self.assertIn('-        if ((customDividerFragment != null && !customDividerFragment.hasDivider())', patch)
        self.assertIn('+        if (dividerDrawable == null) {', patch)
        series = (ANDROID / 'patches' / 'series').read_text()
        self.assertIn('\nlook-settings-dividers.patch\n', series)

    def test_no_fragment_override_patched(self):
        # One place decides; the screens' own hasDivider() stay as they are.
        patch = (ANDROID / 'patches' / 'look-settings-dividers.patch').read_text()
        self.assertEqual(patch.count('+++ b/'), 1)

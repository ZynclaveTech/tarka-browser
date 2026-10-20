"""Tark for Android's offline new tab page is the Mac's (spec §13, left for
later at A4): the mark, the search pill and one line, on paper, English and
Hindi. android/patches/look-offline-new-tab.patch is pinned here by the values
the Mac's page (patches/tarka/core/offline-new-tab.patch) fixes."""
import hashlib
import pathlib
import re
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ANDROID = REPO / 'android'
sys.path.insert(0, str(ANDROID))

NAME = 'look-offline-new-tab.patch'


def series():
    import series as s  # android/series.py
    return s.series(REPO)


def files(text):
    """{path: (added lines, removed lines)} for a unified diff."""
    out = {}
    for part in re.split(r'^--- ', text, flags=re.M)[1:]:
        path = re.search(r'^\+\+\+ b/(\S+)', part, flags=re.M).group(1)
        lines = part.splitlines()[2:]
        out[path] = ('\n'.join(l[1:] for l in lines if l.startswith('+')),
                     '\n'.join(l[1:] for l in lines if l.startswith('-')))
    return out


def grit_id(message):
    """grit's message id (tools/grit/grit/extern/tclib.py, no meaning)."""
    fp = int(hashlib.md5(message.encode('utf-8')).hexdigest()[:16], 16)
    if fp & 0x8000000000000000:
        fp = -((~fp & 0xFFFFFFFFFFFFFFFF) + 1)
    return str(fp & 0x7FFFFFFFFFFFFFFF)


NTP = 'chrome/android/java/src/org/chromium/chrome/browser/ntp/'


class TestOfflineNewTab(unittest.TestCase):
    def setUp(self):
        self.p = (ANDROID / 'patches' / NAME).read_text()
        self.f = files(self.p)

    def add(self, path):
        return self.f[path][0]

    def test_in_the_series_after_home(self):
        s = series()
        self.assertIn('android/' + NAME, s)
        # The page is offline-only because home-shodhya-today sends online
        # new tabs to Shodhya Today.
        self.assertLess(s.index('android/home-shodhya-today.patch'), s.index('android/' + NAME))

    def test_mark_is_the_macs(self):
        # The Mac's offline page: a 64x52 mark, viewBox 44x36, amber on top,
        # coral bottom left, indigo bottom right, radius 7.
        mark = self.add('chrome/android/java/res/drawable/tark_ntp_mark.xml')
        self.assertIn('android:width="64dp"', mark)
        self.assertIn('android:height="52dp"', mark)
        self.assertIn('android:viewportWidth="44"', mark)
        self.assertIn('android:viewportHeight="36"', mark)
        dots = re.findall(r'fillColor="@color/tark_ntp_(\w+)"\s+android:pathData="M(\d+),(\d+)a7,7', mark)
        # A circle at (cx, cy) starts at (cx - 7, cy).
        self.assertEqual(dots, [('amber', '15', '9'), ('coral', '2', '27'), ('indigo', '28', '27')])
        self.assertIn('"java/res/drawable/tark_ntp_mark.xml",',
                      self.add('chrome/android/chrome_java_resources.gni'))

    def test_colours_follow_light_and_dark(self):
        light = self.add('chrome/android/java/res/values/colors.xml')
        dark = self.add('chrome/android/java/res/values-night/colors.xml')
        for name in ('raised', 'rule', 'soft', 'amber', 'coral', 'indigo'):
            self.assertIn(f'<color name="tark_ntp_{name}">@color/tark_{name}_light</color>', light)
            self.assertIn(f'<color name="tark_ntp_{name}">@color/tark_{name}_dark</color>', dark)

    def test_palette_matches_the_macs_page(self):
        # The tokens A4 defined are the Mac offline page's CSS values.
        mac = (REPO / 'patches' / 'tarka' / 'core' / 'offline-new-tab.patch').read_text().lower()
        palette = (ANDROID / 'patches' / 'look-paper-palette.patch').read_text()
        css = {'light': mac.split('@media')[0], 'dark': mac.split('@media')[1]}
        for name in ('paper', 'raised', 'rule', 'soft', 'amber', 'coral', 'indigo'):
            for mode in ('light', 'dark'):
                value = re.search(rf'<color name="tark_{name}_{mode}">#(\w+)</color>', palette).group(1)
                self.assertIn(f'--{name}: #{value.lower()};', css[mode], (name, mode))

    def test_layout_mark_pill_line(self):
        layout = self.add('chrome/android/java/res/layout/new_tab_page_layout.xml')
        self.assertIn('android:id="@+id/tark_ntp_mark"', layout)
        self.assertIn('android:id="@+id/tark_ntp_offline_line"', layout)
        self.assertIn('android:text="@string/tark_ntp_offline"', layout)
        self.assertIn('android:textColor="@color/tark_ntp_soft"', layout)
        # Mark, then the search box, then the line, 28dp apart as on the Mac.
        whole = self.p.split('+++ b/chrome/android/java/res/layout/new_tab_page_layout.xml')[1]
        mark, box, line = (whole.index(k) for k in
                           ('tark_ntp_mark"', 'search_box_stub', 'tark_ntp_offline_line'))
        self.assertLess(mark, box)
        self.assertLess(box, line)
        self.assertEqual(layout.count('28dp'), 2)
        # The line is hidden until the page knows it is offline.
        self.assertIn('android:visibility="gone"', layout.split('tark_ntp_offline_line')[1])

    def test_line_follows_the_connection(self):
        java = self.add(NTP + 'NewTabPageLayout.java')
        self.assertIn('NetworkChangeNotifier.isInitialized() && !NetworkChangeNotifier.isOnline()', java)
        self.assertIn('offline ? View.VISIBLE : View.GONE', java)
        # Observed only while attached; every add has its remove.
        self.assertEqual(java.count('NetworkChangeNotifier.addConnectionTypeObserver(mTarkConnectionObserver)'), 1)
        self.assertEqual(java.count('NetworkChangeNotifier.removeConnectionTypeObserver(mTarkConnectionObserver)'), 1)
        self.assertIn('protected void onDetachedFromWindow()', java)
        # The search box's no-logo margin goes: the mark's 28dp is the gap.
        self.assertIn('showFakeSearchBoxWithoutLogo && !TARK_OFFLINE_NTP', self.add(NTP + 'NewTabPageCoordinator.java'))

    def test_pill_is_raised_with_a_hairline(self):
        java = self.add(NTP + 'search/SearchBoxContainerView.java')
        self.assertIn('pill.setColor(context.getColor(R.color.tark_ntp_raised));', java)
        self.assertIn('context.getColor(R.color.tark_ntp_rule)', java)
        self.assertIn('pill.setCornerRadius(999 * density);', java)
        self.assertIn('mSearchBoxView.setElevation(0);', java)
        # Applied after Chromium's background code (inflation and theme
        # changes), so Chromium never paints over it, and never lifted.
        self.assertEqual(java.count('applyTarkPill();'), 2)
        self.assertIn('if (!apply || TARK_FLAT_PILL) {', java)
        self.assertIn('private static final boolean TARK_FLAT_PILL = true;', java)

    def test_loupe_not_the_engine_icon(self):
        java = self.add(NTP + 'search/SearchBoxMediator.java')
        self.assertIn('private static final boolean TARK_LOUPE = true;', java)
        self.assertIn('(TARK_LOUPE || isGoogleDseOnDesktop()) ? null : newIcon;', java)

    def test_no_tiles(self):
        java = self.add('chrome/android/java/src/org/chromium/chrome/browser/suggestions/tile/MostVisitedTilesMediator.java')
        self.assertIn('private static final boolean TARK_TILES = false;', java)
        self.assertIn('TARK_TILES && NtpCustomizationConfigManager.getInstance().getPrefIsMvtToggleOn()', java)

    def test_no_magic_stack(self):
        # Seen on the emulator before this patch: a "Tark tips" card offering
        # Safe Browsing's enhanced protection under the pill.
        java = self.add(NTP + 'NewTabPageCoordinator.java')
        self.assertIn('private static final boolean TARK_OFFLINE_NTP = true;', java)
        self.assertIn('if (TARK_OFFLINE_NTP || mModuleRegistrySupplier.get() == null) {', java)

    def test_page_is_paper(self):
        # Seen on the emulator: the home surface colour (the page, the feed
        # surface that hosts it and the toolbar above it) was raised in light
        # mode, so the raised pill only showed by its hairline. Dark mode
        # already used colorSurface (paper).
        light = 'components/browser_ui/widget/android/java/res/color/home_surface_background_color.xml'
        self.assertIn('<item android:color="?attr/colorSurface"/>', self.add(light))
        self.assertIn('<item android:color="?attr/colorSurfaceContainerHigh"/>', self.f[light][1])
        # A4 makes colorSurface paper.
        palette = (ANDROID / 'patches' / 'look-paper-palette.patch').read_text()
        self.assertIn('<color name="gm3_baseline_surface_light">#F6F1E7</color>', palette)

    def test_no_customize_sheet(self):
        # Seen on the emulator: Chromium's one-time "Customize your homepage"
        # theme sheet; A4 already took Customize new tab page out of the menu.
        self.assertIn('if (!TARK_OFFLINE_NTP\n                    && NtpCustomizationPromoManager.canTriggerCustomizationBottomSheet(',
                      self.add(NTP + 'NewTabPageCoordinator.java'))

    def test_english_and_hindi(self):
        grd = self.add('chrome/browser/ui/android/strings/android_chrome_strings.grd')
        self.assertIn('<message name="IDS_TARK_NTP_OFFLINE"', grd)
        english = re.search(r'IDS_TARK_NTP_OFFLINE[^>]*>\s*(.+?)\s*</message>', grd, flags=re.S).group(1)
        # The Mac's words.
        self.assertEqual(english.replace('’', "'"), "You're offline. Searches will run when you're back.")
        xtb = self.add('chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb')
        self.assertIn(f'<translation id="{grit_id(english)}">आप ऑफ़लाइन हैं।', xtb)

    def test_grit_id_matches_an_existing_tark_string(self):
        # The fingerprint helper is grit's: look-connects' Hindi uses it.
        self.assertEqual(grit_id('What Tark connects to'), '7144670775258466422')


if __name__ == '__main__':
    unittest.main()

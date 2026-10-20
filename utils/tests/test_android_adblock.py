"""A2: adblock-rust in Tark for Android (spec §4). Task 3: the adblock crate
and its new dependencies, placed into Chromium's vendored crates by
android/adblock/crates.py (each .crate checked against a pinned sha256) and
wired up by android/patches/adblock-crates.patch."""
import hashlib
import re
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'android' / 'adblock'))
import crates  # noqa: E402

PATCHES = ROOT / 'android' / 'patches'


def patch_text(name):
    return (PATCHES / name).read_text()


def added(text):
    return '\n'.join(l[1:] for l in text.splitlines() if l.startswith('+') and not l.startswith('+++'))


class TestCrateList(unittest.TestCase):
    def test_the_new_crates(self):
        self.assertEqual(sorted(n for n, _, _ in crates.CRATES), sorted([
            'adblock', 'arrayvec', 'flatbuffers', 'idna', 'idna_adapter', 'percent-encoding',
            'precomputed-hash', 'rustc-hash', 'rustc_version', 'seahash', 'semver']))
        for n, v, sha in crates.CRATES:
            self.assertRegex(sha, r'^[0-9a-f]{64}$', n)
        self.assertIn(('adblock', '0.13.3'), [(n, v) for n, v, _ in crates.CRATES])

    def test_epochs(self):
        self.assertEqual(crates.epoch('0.13.3'), 'v0_13')
        self.assertEqual(crates.epoch('25.12.19'), 'v25')
        self.assertEqual(crates.epoch('1.1.0'), 'v1')
        self.assertEqual(crates.epoch('0.0.18'), 'v0_0_18')


def fake_crate(name, version, files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f'{name}-{version}/{path}')
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestPlace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = pathlib.Path(self.tmp.name) / 'src'
        self.cio = self.src / 'third_party/rust/chromium_crates_io'
        (self.cio / 'vendor').mkdir(parents=True)
        self.data = fake_crate('demo', '0.2.1', {'Cargo.toml': '[package]\nname = "demo"\n',
                                                  'src/lib.rs': 'pub fn f() {}\n'})
        self.sha = hashlib.sha256(self.data).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_places_a_checked_crate(self):
        crates.place(self.src, 'demo', '0.2.1', self.sha, self.data)
        d = self.cio / 'vendor' / 'demo-v0_2'
        self.assertEqual((d / 'src/lib.rs').read_text(), 'pub fn f() {}\n')
        self.assertEqual(json.loads((d / '.cargo-checksum.json').read_text()), {'files': {}})

    def test_refuses_a_crate_with_the_wrong_sha256(self):
        with self.assertRaises(ValueError):
            crates.place(self.src, 'demo', '0.2.1', '0' * 64, self.data)
        self.assertFalse((self.cio / 'vendor' / 'demo-v0_2').exists())

    def test_applies_the_crate_patches(self):
        pdir = self.cio / 'patches' / 'demo-v0_2'
        pdir.mkdir(parents=True)
        p = 'third_party/rust/chromium_crates_io/vendor/demo-v0_2/LICENSE'
        (pdir / '0001-licence.diff').write_text(
            f'diff --git a/{p} b/{p}\nnew file mode 100644\n--- /dev/null\n+++ b/{p}\n@@ -0,0 +1 @@\n+MIT\n')
        crates.place(self.src, 'demo', '0.2.1', self.sha, self.data)
        self.assertEqual((self.cio / 'vendor/demo-v0_2/LICENSE').read_text(), 'MIT\n')


class TestCratesPatch(unittest.TestCase):
    def setUp(self):
        self.p = patch_text('adblock-crates.patch')
        self.add = added(self.p)

    def test_in_the_series(self):
        self.assertIn('adblock-crates.patch', (PATCHES / 'series').read_text().split())

    def test_adblock_pinned_with_only_its_two_features(self):
        self.assertIn('adblock = { version = "=0.13.3", default-features = false, '
                      'features = ["full-regex-handling", "single-thread"] }', self.add)
        self.assertNotIn('embedded-domain-resolver', self.add)
        self.assertNotIn('css-validation', self.add)

    def test_regex_becomes_shippable(self):
        # Chromium ships regex as test-only; adblock-rust needs it in the browser.
        self.assertRegex(self.p, r"-group = 'test'")
        self.assertIn('-  testonly = true', self.p)

    def test_build_files_for_every_new_crate(self):
        for n, v, _ in crates.CRATES:
            d = n.replace('-', '_')
            self.assertIn(f'+++ b/third_party/rust/{d}/{crates.epoch(v)}/BUILD.gn', self.p, n)

    def test_crate_patches_recorded(self):
        self.assertIn('patches/adblock-v0_13/0001-Tark-thiserror-2-and-no-url.diff', self.p)
        self.assertIn('patches/seahash-v4/0001-Tark-add-licence.diff', self.p)


class TestBuildSh(unittest.TestCase):
    def test_crates_placed_after_substitution(self):
        s = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('android/adblock/crates.py', s)
        self.assertLess(s.index('domain_substitution.py" apply'), s.index('android/adblock/crates.py'))
        self.assertLess(s.index('android/adblock/crates.py'), s.index('# --- end prepare ---'))

    def test_prep_hash_covers_the_crates(self):
        h = (ROOT / 'android' / 'prep_hash.py').read_text()
        self.assertIn('android/adblock/crates.py', h)


if __name__ == '__main__':
    unittest.main()


class TestEnginePatch(unittest.TestCase):
    """A2 Task 4: the engine (Brave's bridge, trimmed) and Tark's service."""

    def setUp(self):
        self.p = patch_text('adblock-engine.patch')
        self.add = added(self.p)

    def test_in_the_series_after_the_crates(self):
        series = (PATCHES / 'series').read_text().split()
        self.assertLess(series.index('adblock-crates.patch'), series.index('adblock-engine.patch'))

    def test_borrowed_files_keep_mpl_and_say_what_changed(self):
        for f in re.findall(r'^\+\+\+ b/(third_party/brave_adblock/\S+\.(?:rs|h|cc))$', self.p, re.M):
            body = self.p.split(f'+++ b/{f}\n', 1)[1].split('\n--- ', 1)[0]
            self.assertIn('Mozilla Public', body, f)
            self.assertIn('Modifications Copyright 2026 The Tark Authors', body, f)

    def test_licence_and_readme(self):
        self.assertIn('+++ b/third_party/brave_adblock/LICENSE', self.p)
        self.assertIn('+License: MPL-2.0', self.p)

    def test_the_asset_is_stored_uncompressed(self):
        self.assertIn('renaming_destinations = [ "tark_adblock/lists.zip" ]', self.add)
        self.assertIn('disable_compression = true', self.add)
        self.assertIn('"//chrome/browser/tark_adblock:lists_assets",', self.add)

    def test_each_engine_on_its_own_sequence(self):
        self.assertIn('base::SequenceBound<EngineHolder> active_;', self.add)
        self.assertIn('base::SequenceBound<EngineHolder> pending_;', self.add)
        self.assertIn('{base::MayBlock(), base::TaskPriority::USER_BLOCKING,', self.add)
        self.assertIn('base::TaskShutdownBehavior::SKIP_ON_SHUTDOWN}', self.add)

    def test_fails_open_until_ready(self):
        self.assertIn('  if (!active_) {\n    std::move(reply).Run(BlockResult());', self.add)

    def test_the_cache_is_keyed_by_bundle_and_crate(self):
        self.assertIn('constexpr char kCrateVersion[] = "adblock 0.13.3";', self.add)
        self.assertIn('bundle->sha256 + " " + kCrateVersion', self.add)

    def test_the_public_key_is_the_lists_key(self):
        key = bytes.fromhex((ROOT / 'android/adblock/lists_pubkey.txt').read_text().strip())
        literal = ', '.join('0x%02x' % b for b in key[:8])
        self.assertIn(literal, self.add)

    def test_started_after_browser_start(self):
        self.assertIn('  tark_adblock::AdblockService::Get();', self.add)


class TestNoUblockPak(unittest.TestCase):
    def test_android_ships_no_ublock_pak(self):
        p = patch_text('adblock-no-ublock-pak.patch')
        self.assertIn('-      "$root_gen_dir/third_party/ublock/resources/ublock_resources.pak",', p)
        self.assertIn('-      "//third_party/ublock",', p)
        self.assertIn('adblock-no-ublock-pak.patch', (PATCHES / 'series').read_text().split())


class TestListsInTheBuild(unittest.TestCase):
    def test_build_verifies_the_bundle_before_the_apk_gets_it(self):
        s = (ROOT / 'android' / 'build.sh').read_text()
        verify = s.index('android/adblock/bundle.py" verify')
        self.assertLess(verify, s.index('chrome/browser/tark_adblock/lists.zip"'))
        self.assertGreater(verify, s.index('# --- end prepare ---'))
        self.assertIn('https://gettarka.com/lists/android/v1', s)

    def test_job_passes_a_staged_bundle(self):
        j = (ROOT / 'android' / 'aws' / 'jobs' / 'tark-build.sh').read_text()
        self.assertIn('TARK_LISTS_DIR', j)


class TestNetworkPatch(unittest.TestCase):
    """A2 Task 5: requests are checked before they leave."""

    def setUp(self):
        self.p = patch_text('adblock-network.patch')
        self.add = added(self.p)

    def test_in_the_series_after_the_engine(self):
        series = (PATCHES / 'series').read_text().split()
        self.assertLess(series.index('adblock-engine.patch'), series.index('adblock-network.patch'))

    def test_blocked_like_ublock(self):
        self.assertIn('network::URLLoaderCompletionStatus status(net::ERR_BLOCKED_BY_CLIENT);', self.add)
        self.assertIn('status.should_collapse_initiator = true;', self.add)

    def test_redirect_rules_get_their_stub(self):
        self.assertIn('brave_shields::MakeStubResponse(data_url, request_, &head, &body);', self.add)

    def test_redirects_are_checked_again(self):
        self.assertIn('redirect_info.new_url, *request_.request_initiator, request_type_,', self.add)

    def test_the_site_switch_is_honoured(self):
        self.assertIn('settings->GetContentSetting(url, url, ContentSettingsType::ADS) ==', self.add)
        self.assertIn('CONTENT_SETTING_ALLOW', self.add)

    def test_main_frames_pass(self):
        self.assertIn('static_cast<int>(blink::mojom::ResourceType::kMainFrame)', self.add)

    def test_hooked_into_chrome(self):
        self.assertIn('tark_adblock::ProxyingURLLoaderFactory::MaybeProxyRequest(', self.add)
        self.assertIn('return frame && tark_adblock::AdblockService::Get()->IsReady();', self.add)
        self.assertIn('tark_adblock::ProxyingURLLoaderFactory::MaybeConnectWebSocket(', self.add)


class TestE2E(unittest.TestCase):
    def test_run_refuses_a_phone(self):
        r = subprocess.run([sys.executable, str(ROOT / 'android/adblock/e2e/run.py'), '--serial', 'bf678949'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_network_cases_named(self):
        sys.path.insert(0, str(ROOT / 'android/adblock/e2e'))
        import run
        self.assertEqual(set(run.CASES['network'][1]),
                         {'blocked', 'exception', 'redirect', 'chain', 'ws', 'worker', 'frame', 'real'})


class TestCosmeticPatch(unittest.TestCase):
    """A2 Task 6: hiding rules and scriptlets."""

    def setUp(self):
        self.p = patch_text('adblock-cosmetic.patch')
        self.add = added(self.p)

    def test_in_the_series_after_the_network(self):
        series = (PATCHES / 'series').read_text().split()
        self.assertLess(series.index('adblock-network.patch'), series.index('adblock-cosmetic.patch'))

    def test_resources_arrive_before_the_page_scripts(self):
        # Sync at commit, applied first at document start: YouTube's ads
        # come through when scriptlets run after the page's scripts.
        self.assertIn('  [Sync]\n+  UrlCosmeticResources(string url)', self.p.replace('+  [Sync]', '  [Sync]'))
        self.assertIn('  if (auto* adblock = tark_adblock::FrameObserver::Get(render_frame)) {', self.add)
        self.assertIn('    adblock->RunScriptsAtDocumentStart();', self.add)

    def test_scriptlets_in_the_page_world_hide_rules_as_user_styles(self):
        self.assertIn('frame->ExecuteScript(blink::WebScriptSource(', self.add)
        self.assertIn('const scriptletGlobals = ', self.add)
        self.assertIn('blink::WebCssOrigin::kUser', self.add)

    def test_one_rule_per_selector(self):
        self.assertIn('{selector, "{display:none !important}\\n"}', self.add)

    def test_the_site_switch_is_honoured(self):
        self.assertIn('if (!gurl.SchemeIsHTTPOrHTTPS() || AdsAllowedFor(gurl)) {', self.add)

    def test_bound_for_every_frame(self):
        self.assertIn('map->Add<tark_adblock::mojom::CosmeticResources>(', self.add)
        self.assertIn('new tark_adblock::FrameObserver(render_frame);', self.add)


class TestUpdater(unittest.TestCase):
    """A2 Task 7: daily updates (in the engine patch)."""

    def setUp(self):
        self.add = added(patch_text('adblock-engine.patch'))

    def test_only_gettarka_without_cookies_or_query(self):
        self.assertIn('constexpr char kListsBase[] = "https://gettarka.com/lists/android/v1/";', self.add)
        self.assertIn('request->credentials_mode = network::mojom::CredentialsMode::kOmit;', self.add)
        self.assertIn('std::string(kListsBase) + "latest.json"', self.add)

    def test_schedule(self):
        self.assertIn('return now - last_success >= base::Hours(24);', self.add)
        self.assertIn('return now - last_success >= base::Hours(72);', self.add)
        self.assertIn('timer_.Start(FROM_HERE, base::Hours(6),', self.add)

    def test_never_an_older_bundle(self):
        self.assertIn('if (!bundle || bundle->created <= current_created) {', self.add)

    def test_unit_tests_built_and_run(self):
        self.assertIn('test("tark_adblock_unittests") {', self.add)
        s = (ROOT / 'android' / 'build.sh').read_text()
        self.assertIn('run "$_src_dir/out/Default/clang_x64/tark_adblock_unittests"', s)

    def test_only_gettarka_is_new(self):
        hosts = (ROOT / 'android' / 'allowed_hosts.txt').read_text().split()
        self.assertIn('gettarka.com', hosts)


class TestSiteSwitchPatch(unittest.TestCase):
    """A2 Task 8: "Block ads on this site"."""

    def setUp(self):
        self.p = patch_text('adblock-site-switch.patch')
        self.add = added(self.p)

    def test_in_the_series(self):
        self.assertIn('adblock-site-switch.patch', (PATCHES / 'series').read_text().split())

    def test_the_row_in_page_info(self):
        self.assertIn('TarkAdblockSiteSwitch.create(', self.add)
        self.assertIn('"java/src/org/chromium/chrome/browser/page_info/TarkAdblockSiteSwitch.java",', self.add)

    def test_stored_as_the_ads_setting_and_reloads(self):
        self.assertIn('ContentSettingsType.ADS', self.add)
        self.assertIn('checked ? ContentSetting.DEFAULT : ContentSetting.ALLOW', self.add)
        self.assertIn('webContents.getNavigationController().reload(true);', self.add)

    def test_english_and_hindi(self):
        self.assertIn('<message name="IDS_TARK_PAGE_INFO_BLOCK_ADS"', self.add)
        self.assertIn('Block ads on this site', self.add)
        self.assertIn('<translation id="502232591958917855">', self.add)


class TestJavaSourceList(unittest.TestCase):
    def test_the_source_list_only_gains_the_switch(self):
        p = patch_text('adblock-site-switch.patch')
        gni = p.split('+++ b/chrome/android/chrome_java_sources.gni\n', 1)[1].split('\n--- ', 1)[0]
        self.assertEqual([l for l in gni.splitlines() if l.startswith('-')], [])
        self.assertEqual([l for l in gni.splitlines() if l.startswith('+')],
                         ['+  "java/src/org/chromium/chrome/browser/page_info/TarkAdblockSiteSwitch.java",'])

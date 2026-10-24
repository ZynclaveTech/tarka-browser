"""Tark for Android's live captions (spec: Android captions; plan Phase 1).
The engine is the Mac's: android/captions/engine.py extracts it from the
captions patches into one Android-only patch, which must stay identical to
what the Mac builds. These tests run offline."""
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANDROID = ROOT / 'android'
sys.path.insert(0, str(ANDROID / 'captions'))
import engine  # noqa: E402
import models  # noqa: E402

ENGINE_PATCH = ANDROID / 'patches' / 'captions-engine.patch'
ORT_SHA256 = '72683787a80d0608a3121b967d8e1239aef48286826661c953211626690540a7'


def android_series():
    return [l.strip() for l in (ANDROID / 'patches' / 'series').read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


class TestEnginePatch(unittest.TestCase):
    def test_engine_patch_is_current(self):
        self.assertEqual(ENGINE_PATCH.read_text(encoding='utf-8'), engine.build(ROOT),
                         'run android/captions/engine.py build after changing a captions patch')

    def test_engine_patch_only_touches_component(self):
        paths = re.findall(r'^\+\+\+ b/(\S+)', ENGINE_PATCH.read_text(encoding='utf-8'), re.M)
        self.assertIn('components/tark_captions/caption_engine.cc', paths)
        self.assertIn('components/tark_captions/model_source.cc', paths)
        for path in paths:
            self.assertTrue(path.startswith('components/tark_captions/') or path == 'BUILD.gn', path)

    def test_engine_builds_host_tests_without_the_macs_suite(self):
        build = engine.component_files(ROOT)['components/tark_captions/BUILD.gn']
        self.assertIn('group("host_unittests")', build)
        self.assertIn('tark_captions_engine_unittests', build)
        self.assertRegex(build, r'if \(!is_android\) \{\s*test\("tark_captions_unittests"\)')

    def test_engine_patch_is_in_the_android_series(self):
        self.assertIn('captions-engine.patch', android_series())

    def test_desktop_only_still_excludes_captions_folder(self):
        text = (ANDROID / 'desktop-only-patches.txt').read_text(encoding='utf-8')
        self.assertIn('tarka/captions/\n', text)


def hunk_count_errors(text):
    """Hunks whose @@ -a,b +c,d @@ counts disagree with their lines."""
    errors, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = re.match(r'@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@', lines[i])
        if not m:
            i += 1
            continue
        old, new = int(m.group(1) or 1), int(m.group(2) or 1)
        header, i = lines[i], i + 1
        while i < len(lines) and (old or new) and not lines[i].startswith('@@'):
            kind = lines[i][:1]
            if kind in (' ', ''):
                old, new = old - 1, new - 1
            elif kind == '-':
                old -= 1
            elif kind == '+':
                new -= 1
            elif lines[i].startswith('\\'):
                pass
            else:
                break
            i += 1
        if old or new:
            errors.append(header)
    return errors


class TestPatchShapes(unittest.TestCase):
    def test_hunk_counts_match(self):
        for name in sorted(p.name for p in (ANDROID / 'patches').glob('captions-*.patch')):
            text = (ANDROID / 'patches' / name).read_text(encoding='utf-8')
            self.assertEqual(hunk_count_errors(text), [], name)
        conventions = ROOT / 'patches' / 'tarka' / 'captions' / 'engine-conventions.patch'
        self.assertEqual(hunk_count_errors(conventions.read_text(encoding='utf-8')), [])

    def test_counter_finds_a_wrong_count(self):
        self.assertTrue(hunk_count_errors('@@ -1,1 +1,3 @@\n a\n+b\n'))


class TestCaptionsAudio(unittest.TestCase):
    def test_muted_players_send_no_audio(self):
        # A muted player (a background or preview video) never feeds captions.
        added = '\n'.join(added_lines('captions-audio.patch', 'media/renderers/audio_renderer_impl.cc'))
        self.assertRegex(added, r'if \(transcribe_audio_callback_ && volume_ != 0\)')


class TestOnnxRuntime(unittest.TestCase):
    def test_ort_pinned(self):
        text = (ANDROID / 'captions' / 'ort.sh').read_text(encoding='utf-8')
        self.assertIn('VERSION=1.31.0', text)
        self.assertIn(f'SHA256={ORT_SHA256}', text)
        self.assertIn('repo1.maven.org', text)

    def test_ort_in_the_apk_compressed(self):
        patch = (ANDROID / 'patches' / 'captions-ort.patch').read_text(encoding='utf-8')
        self.assertIn('third_party/tark_onnxruntime/arm64-v8a/libonnxruntime.so', patch)
        self.assertRegex(patch, r'library_always_compress = \[[^\]]*"libonnxruntime\.so"')

    def test_ort_in_the_play_bundle(self):
        # Play installs come from chrome_public_bundle, whose base module is
        # a separate target from chrome_public_apk.
        patch = (ANDROID / 'patches' / 'captions-ort.patch').read_text(encoding='utf-8')
        hunks = re.split(r'(?m)^@@ ', patch)
        base = [h for h in hunks if 'target_type = "android_app_bundle_module"' in h]
        self.assertTrue(base, 'no hunk in the bundle base module')
        self.assertTrue(any(
            re.search(r'(?m)^\+\s*loadable_modules = \[.*libonnxruntime\.so', h) for h in base))

    def test_build_sh_checks_the_bundle_has_ort(self):
        text = (ANDROID / 'build.sh').read_text(encoding='utf-8')
        check = text.index('base/lib/arm64-v8a/libonnxruntime.so')
        self.assertLess(text.index('chrome_public_bundle'), check)
        self.assertIn('ChromePublic.aab', text[check - 400:check + 400])

    def test_ort_credited(self):
        text = (ANDROID / 'captions' / 'ort.sh').read_text(encoding='utf-8')
        for name in ('README.chromium', 'LICENSE', 'ThirdPartyNotices.txt'):
            self.assertIn(name, text)
            self.assertTrue((ANDROID / 'captions' / 'onnxruntime' / name).exists(), name)

    def test_build_sh_fetches_ort_before_gn(self):
        text = (ANDROID / 'build.sh').read_text(encoding='utf-8')
        self.assertLess(text.index('android/captions/ort.sh'), text.index('/out/Default/gn" gen'))
        self.assertIn('components/tark_captions:host_unittests', text)
        self.assertIn('tark_captions_engine_unittests', text)



def fake_export(folder, lang, blank):
    folder.mkdir(parents=True)
    for name in ('encoder.int8.onnx', 'ctc_decoder.onnx', 'window.f32', 'mel_fb.f32'):
        (folder / name).write_bytes(name.encode())
    (folder / 'vocab.json').write_text(json.dumps({lang: ['x'] * (blank + 1)}))
    (folder / 'language_masks.json').write_text(json.dumps({lang: [True] * (blank + 1)}))
    (folder / 'engine.json').write_text(json.dumps(
        {'lang': lang, 'blank': blank, 'valid_frames': 'n/hop', 'pad': 'constant'}))


def fake_translation_export(folder, language_tags):
    folder.mkdir(parents=True)
    for name in models.TRANSLATION_FILES:
        (folder / name).write_bytes(name.encode())
    config = {'decoder_layers': 6, 'decoder_attention_heads': 8, 'decoder_embed_dim': 512,
              'decoder_start_token_id': 2, 'eos_token_id': 2}
    if not language_tags:
        config['language_tags'] = False
    (folder / 'config.json').write_text(json.dumps(config))


class TestModels(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        exports = self.tmp / 'exports'
        for unit, folder in models.SPEECH_UNITS.items():
            fake_export(exports / folder, unit, 1024 if unit in ('en', 'es') else 256)
        for unit, folder in models.TRANSLATION_UNITS.items():
            fake_translation_export(exports / folder, language_tags=unit != 'tr_es_en')
        (self.tmp / 'silero_vad.onnx').write_bytes(b'vad')
        self.files = models.build(exports, self.tmp / 'silero_vad.onnx', self.tmp / 'out')

    def test_units_files_have_engine_json(self):
        self.assertEqual(set(models.units(self.files)),
                         {'common', 'hi', 'ta', 'en', 'es', 'tr_indic_en', 'tr_en_indic', 'tr_es_en'})
        for unit in models.SPEECH_UNITS:
            names = {n.split('/', 1)[1] for n, f in self.files.items() if f['unit'] == unit}
            self.assertEqual(names, set(models.SPEECH_FILES), unit)
            engine_json = json.loads((self.tmp / 'out' / unit / 'engine.json').read_text())
            self.assertEqual(engine_json['lang'], unit)
            self.assertIn(engine_json['valid_frames'], ('n/hop', 'n/hop+1'))
            vocab = json.loads((self.tmp / 'out' / unit / 'vocab.json').read_text())
            self.assertEqual(list(vocab), [unit])
        self.assertEqual(self.files['common/silero_vad.onnx']['size'], 3)

    def test_an_export_of_the_wrong_language_is_refused(self):
        exports = self.tmp / 'bad'
        fake_export(exports / models.SPEECH_UNITS['hi'], 'ta', 256)
        with self.assertRaises(SystemExit):
            models.build(exports, self.tmp / 'silero_vad.onnx', self.tmp / 'out2')

    def test_translation_units_have_their_six_files(self):
        self.assertEqual(models.TRANSLATION_UNITS,
                         {'tr_indic_en': 'it2_indic_en', 'tr_en_indic': 'it2_en_indic', 'tr_es_en': 'opus_es_en'})
        for unit in models.TRANSLATION_UNITS:
            names = {n.split('/', 1)[1] for n, f in self.files.items() if f['unit'] == unit}
            self.assertEqual(names, set(models.TRANSLATION_FILES), unit)

    def test_marian_export_must_say_no_language_tags(self):
        # IndicTrans2 prefixes language tags, opus-mt must not: a config that
        # gets this wrong would translate garbage.
        exports = self.tmp / 'bad'
        for unit, folder in models.SPEECH_UNITS.items():
            fake_export(exports / folder, unit, 1024 if unit in ('en', 'es') else 256)
        for unit, folder in models.TRANSLATION_UNITS.items():
            fake_translation_export(exports / folder, language_tags=True)
        with self.assertRaises(SystemExit):
            models.build(exports, self.tmp / 'silero_vad.onnx', self.tmp / 'out3')

    def test_committed_files_json_pins_translation_units(self):
        committed = json.loads((ANDROID / 'captions' / 'files.json').read_text(encoding='utf-8'))
        total = {u: sum(f['size'] for f in committed.values() if f['unit'] == u)
                 for u in models.TRANSLATION_UNITS}
        self.assertTrue(200e6 <= total['tr_indic_en'] <= 240e6, total)
        self.assertTrue(240e6 <= total['tr_en_indic'] <= 290e6, total)
        self.assertTrue(60e6 <= total['tr_es_en'] <= 160e6, total)

    def test_marian_licence_credited(self):
        credits = ROOT / 'resources' / 'captions' / 'credits' / 'opus-mt-es-en'
        readme = (credits / 'README.chromium').read_text(encoding='utf-8')
        self.assertIn('Helsinki-NLP/opus-mt-es-en', readme)
        self.assertIn('License: Apache-2.0', readme)
        self.assertIn('Apache License', (credits / 'LICENSE').read_text(encoding='utf-8'))

    def test_marian_export_refuses_another_pair(self):
        sys.path.insert(0, str(ROOT / 'utils'))
        import marian_export
        folder = self.tmp / 'fr-en'
        folder.mkdir()
        (folder / 'metadata.json').write_text(json.dumps({'src_alpha2': 'fr', 'tgt_alpha2': 'en'}))
        with self.assertRaises(SystemExit):
            marian_export.check_checkpoint(folder)

    def test_table_matches_files_json(self):
        rows = models.header_rows(self.files)
        self.assertEqual(len(rows.splitlines()), len(self.files))
        for name, f in self.files.items():
            unit, file = name.split('/', 1)
            self.assertIn(f'{{"{unit}", "{file}", {f["size"]}, "{f["sha256"]}"}},', rows)

    def test_committed_files_json_pins_phase1_units(self):
        committed = json.loads((ANDROID / 'captions' / 'files.json').read_text(encoding='utf-8'))
        self.assertLessEqual({'common', 'hi', 'ta', 'en', 'es'}, set(models.units(committed)))
        for name, f in committed.items():
            self.assertRegex(f['sha256'], r'^[0-9a-f]{64}$', name)
            self.assertGreater(f['size'], 0, name)
        # IndicConformer 130M int8, as the spike measured.
        self.assertEqual(committed['hi/encoder.int8.onnx']['size'] // 1_000_000, 137)

    def test_build_sh_writes_the_table(self):
        text = (ANDROID / 'build.sh').read_text(encoding='utf-8')
        self.assertIn('android/captions/models.py" header', text)
        self.assertIn('chrome/browser/tark_captions_android/model_files.inc', text)



def added_lines(patch, path):
    text = (ANDROID / 'patches' / patch).read_text(encoding='utf-8')
    for sec in re.split(r'(?m)^(?=--- )', text):
        if sec.split('\n', 2)[1:2] == [f'+++ b/{path}']:
            return [l[1:] for l in sec.splitlines() if l.startswith('+') and not l.startswith('+++')]
    return []


def grit_id(text):
    import hashlib
    fp = int(hashlib.md5(text.encode('utf-8')).hexdigest()[:16], 16)
    if fp & 0x8000000000000000:
        fp = -((~fp & 0xFFFFFFFFFFFFFFFF) + 1)
    return str(fp & 0x7FFFFFFFFFFFFFFF)


class TestCaptionsUi(unittest.TestCase):
    GRD = 'chrome/browser/ui/android/strings/android_chrome_strings.grd'
    XTB = 'chrome/browser/ui/android/strings/translations/android_chrome_strings_hi.xtb'

    def messages(self):
        lines = added_lines('captions-ui.patch', self.GRD)
        text = '\n'.join(lines)
        return re.findall(r'<message name="(IDS_TARK_[A-Z_]+)"[^>]*>\s*(.*?)\s*</message>', text, re.S)

    def test_every_caption_string_has_hindi(self):
        ui = (ANDROID / 'patches' / 'captions-ui.patch').read_text(encoding='utf-8')
        # Translations already in the xtb (Download now, Try again, ...) are reused.
        xtb_ids = set(re.findall(r'<translation id="(\d+)"', ui))
        for name, en in self.messages():
            fp = re.sub(r'<ph name="([A-Z_]+)">.*?</ph>', lambda m: m.group(1), en)
            reused = name in ('IDS_TARK_CAPTIONS_WAITING_FOR_WIFI', 'IDS_TARK_CAPTIONS_DOWNLOAD_NOW',
                              'IDS_TARK_CAPTIONS_TRY_AGAIN', 'IDS_TARK_CAPTIONS_STYLE_AUTOMATIC',
                              'IDS_TARK_CAPTIONS_TRANSLATE')
            self.assertTrue(reused or grit_id(fp) in xtb_ids, name)

    def test_no_duplicate_xtb_ids(self):
        ids = re.findall(r'<translation id="(\d+)"', '\n'.join(added_lines('captions-ui.patch', self.XTB)))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 19)

    def test_xtb_keeps_no_trailing_newline(self):
        text = (ANDROID / 'patches' / 'captions-ui.patch').read_text(encoding='utf-8')
        for m in re.finditer(r'^ </translationbundle>\n(.*)$', text, re.M):
            self.assertEqual(m.group(1), '\\ No newline at end of file')

    def test_only_download_now_agrees_to_mobile_data(self):
        # "Try again" after a failure must not become consent to mobile data.
        bar = '\n'.join(added_lines(
            'captions-ui.patch',
            'chrome/android/java/src/org/chromium/chrome/browser/tark_captions/'
            'TarkCaptionBarCoordinator.java'))
        self.assertNotIn('requestDownload(mWebContents, /* now= */ true)', bar)
        self.assertRegex(bar, r'[uU]nitState[^;]*==\s*TarkCaptionsBridge\.UNIT_WAITING_FOR_WIFI')

    def test_bar_updates_views_only_when_they_change(self):
        bar = '\n'.join(added_lines(
            'captions-ui.patch',
            'chrome/android/java/src/org/chromium/chrome/browser/tark_captions/'
            'TarkCaptionBarCoordinator.java'))
        self.assertIn('setTextIfChanged', bar)
        self.assertNotRegex(bar, r'm(Final|Draft|Download\w*|LanguageChip)Text?\.setText\(')

    BAR = 'chrome/android/java/res/layout/tark_caption_bar.xml'
    COORDINATOR = ('chrome/android/java/src/org/chromium/chrome/browser/tark_captions/'
                   'TarkCaptionBarCoordinator.java')

    def test_bar_has_translate_chip(self):
        bar = '\n'.join(added_lines('captions-ui.patch', self.BAR))
        self.assertIn('tark_captions_translate', bar)
        self.assertIn('tark_captions_target', bar)
        # The translation sits in the caption box, larger than the original.
        box = bar[bar.index('@+id/tark_captions_box'):bar.index('@+id/tark_captions_download"')]
        self.assertIn('@+id/tark_captions_translation', box)
        final = box[box.index('tark_captions_final'):]
        self.assertIn('TextSmall', final[:final.index('/>')])
        translation = box[box.index('tark_captions_translation'):]
        self.assertIn('TextLarge', translation[:translation.index('/>')])

    def test_translate_strings(self):
        names = dict(self.messages())
        self.assertEqual(names['IDS_TARK_CAPTIONS_TRANSLATE'], 'Translate')
        self.assertTrue(names['IDS_TARK_CAPTIONS_TARGET_CHIP'].startswith('→ <ph name="LANGUAGE">%1$s'))
        self.assertIn('Getting translation ready', names['IDS_TARK_CAPTIONS_GETTING_TRANSLATION_READY'])
        self.assertIn('Translation', names['IDS_TARK_CAPTIONS_TRANSLATION_MODEL'])

    def test_translation_text_set_only_when_changed(self):
        bar = '\n'.join(added_lines('captions-ui.patch', self.COORDINATOR))
        self.assertIn('mTranslationText', bar)
        self.assertNotIn('mTranslationText.setText(', bar)

    def test_settings_lists_translation_models(self):
        settings = '\n'.join(added_lines(
            'captions-ui.patch',
            'chrome/browser/tark_captions_android/android/java/src/org/chromium/chrome/browser/'
            'tark_captions/TarkLiveCaptionsSettings.java'))
        self.assertIn('tark_captions_translation_model', settings)

    def test_connects_row_names_model_downloads(self):
        rows = '\n'.join(added_lines('captions-ui.patch', 'chrome/android/java/res/xml/privacy_preferences.xml'))
        self.assertIn('tark_connects_captions', rows)
        names = dict(self.messages())
        self.assertIn('gettarka.com', names['IDS_TARK_CONNECTS_CAPTIONS'])

    def test_settings_row_in_accessibility(self):
        rows = '\n'.join(added_lines(
            'captions-ui.patch',
            'components/browser_ui/accessibility/android/java/res/xml/accessibility_preferences.xml'))
        self.assertIn('org.chromium.chrome.browser.tark_captions.TarkLiveCaptionsSettings', rows)


if __name__ == '__main__':
    unittest.main()

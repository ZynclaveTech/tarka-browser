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
        for name in ('captions-ort.patch', 'captions-engine.patch', 'captions-downloads.patch'):
            text = (ANDROID / 'patches' / name).read_text(encoding='utf-8')
            self.assertEqual(hunk_count_errors(text), [], name)
        conventions = ROOT / 'patches' / 'tarka' / 'captions' / 'engine-conventions.patch'
        self.assertEqual(hunk_count_errors(conventions.read_text(encoding='utf-8')), [])

    def test_counter_finds_a_wrong_count(self):
        self.assertTrue(hunk_count_errors('@@ -1,1 +1,3 @@\n a\n+b\n'))


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


class TestModels(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        exports = self.tmp / 'exports'
        for unit, folder in models.SPEECH_UNITS.items():
            fake_export(exports / folder, unit, 1024 if unit in ('en', 'es') else 256)
        (self.tmp / 'silero_vad.onnx').write_bytes(b'vad')
        self.files = models.build(exports, self.tmp / 'silero_vad.onnx', self.tmp / 'out')

    def test_units_files_have_engine_json(self):
        self.assertEqual(set(models.units(self.files)), {'common', 'hi', 'ta', 'en', 'es'})
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

    def test_table_matches_files_json(self):
        rows = models.header_rows(self.files)
        self.assertEqual(len(rows.splitlines()), len(self.files))
        for name, f in self.files.items():
            unit, file = name.split('/', 1)
            self.assertIn(f'{{"{unit}", "{file}", {f["size"]}, "{f["sha256"]}"}},', rows)

    def test_committed_files_json_pins_phase1_units(self):
        committed = json.loads((ANDROID / 'captions' / 'files.json').read_text(encoding='utf-8'))
        self.assertEqual(set(models.units(committed)), {'common', 'hi', 'ta', 'en', 'es'})
        for name, f in committed.items():
            self.assertRegex(f['sha256'], r'^[0-9a-f]{64}$', name)
            self.assertGreater(f['size'], 0, name)
        # IndicConformer 130M int8, as the spike measured.
        self.assertEqual(committed['hi/encoder.int8.onnx']['size'] // 1_000_000, 137)

    def test_build_sh_writes_the_table(self):
        text = (ANDROID / 'build.sh').read_text(encoding='utf-8')
        self.assertIn('android/captions/models.py" header', text)
        self.assertIn('chrome/browser/tark_captions_android/model_files.inc', text)


if __name__ == '__main__':
    unittest.main()

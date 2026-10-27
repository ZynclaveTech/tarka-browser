"""Tests for utils/install_xlit.sh, the _install_xlit step of dev.sh and build.sh.

The step runs against a fake tree with tiny stand-in inputs: file:// URLs in
place of Hugging Face, a few-byte checkpoint, a one-word list per script.
"""
import collections
import configparser
import hashlib
import lzma
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_xlit_convert import make_checkpoint, write_dict  # noqa: E402

DEST_THIRD_PARTY = ('xlit-model.bin', 'xlit-words.bin', 'README.chromium', 'LICENSE')
DEST_TEST_DATA = ('xlit-model.bin', 'xlit-words.bin', 'golden.tsv', 'golden-inputs.txt')


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    with open(os.path.join(REPO, path), encoding='utf-8') as f:
        return f.read()


class TestInstallXlit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, 'tree')
        self.inputs = os.path.join(tmp.name, 'inputs')
        for d in (self.root, self.inputs):
            os.makedirs(d)
        # The scripts and the downloader are the real ones.
        for name in ('utils', 'ungoogled-chromium'):
            os.symlink(os.path.join(REPO, name), os.path.join(self.root, name))
        res = os.path.join(self.root, 'resources')
        os.makedirs(os.path.join(res, 'indicxlit'))
        os.makedirs(os.path.join(res, 'xlit', 'words'))
        for name in ('LICENSE', 'README.chromium'):
            self.write(os.path.join(res, 'indicxlit', name), 'stand-in ' + name)
        for name in ('golden.tsv', 'golden-inputs.txt'):
            self.write(os.path.join(res, 'xlit', name), 'stand-in ' + name)
        self.write(os.path.join(res, 'xlit', 'words', 'hi.tsv'), 'नमस्ते\t5\n')
        with lzma.open(os.path.join(res, 'xlit', 'english-common.txt.xz'), 'wt') as f:
            f.write('hello\n')
        os.makedirs(os.path.join(self.root, 'build', 'download_cache'))
        # Tiny stand-ins for the three downloads, same names as the real ini.
        ckpt = os.path.join(self.inputs, 'ckpt')
        make_checkpoint(ckpt, collections.OrderedDict([
            ('decoder.layers.0.fc1.bias', ((3,), [0.5, 1.0, -2.0]))]))
        write_dict(os.path.join(self.inputs, 'en'), ['a', 'b'])
        write_dict(os.path.join(self.inputs, 'hi'), ['क', 'ख', 'ग'])
        real = configparser.ConfigParser(interpolation=None)
        real.read(os.path.join(REPO, 'downloads-xlit.ini'))
        fake = configparser.ConfigParser(interpolation=None)
        for section, local in (('indicxlit_checkpoint', 'ckpt'),
                               ('indicxlit_dict_en', 'en'),
                               ('indicxlit_dict_hi', 'hi')):
            path = os.path.join(self.inputs, local)
            fake[section] = {
                'url': 'file://' + path,
                'download_filename': real[section]['download_filename'],
                'output_path': real[section]['output_path'],
                'sha256': sha256(path)}
        self.ini = os.path.join(self.root, 'downloads-xlit.ini')
        with open(self.ini, 'w') as f:
            fake.write(f)

    @staticmethod
    def write(path, text):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def run_install(self):
        # The variables dev.sh and build.sh set before they call the step.
        script = (
            'set -euo pipefail\n'
            '_root_dir="$TARKA_ROOT"\n'
            '_src_dir="$_root_dir/build/src"\n'
            '_main_repo="$_root_dir/ungoogled-chromium"\n'
            '_download_cache="$_root_dir/build/download_cache"\n'
            '_xlit_ini="$_root_dir/downloads-xlit.ini"\n'
            'source "$_root_dir/utils/install_xlit.sh"\n'
            '_install_xlit\n')
        return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                              env=dict(os.environ, TARKA_ROOT=self.root))

    def dest(self, *parts):
        return os.path.join(self.root, 'build', 'src', *parts)

    def test_four_files_land_in_each_destination(self):
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for name in DEST_THIRD_PARTY:
            self.assertTrue(os.path.isfile(self.dest('third_party', 'indicxlit', name)), name)
        for name in DEST_TEST_DATA:
            self.assertTrue(os.path.isfile(self.dest('components', 'tark_xlit', 'test', 'data', name)), name)
        with open(self.dest('third_party', 'indicxlit', 'xlit-model.bin'), 'rb') as f:
            self.assertEqual(f.read(8), b'TXLM\x01\x00\x00\x00')
        with open(self.dest('third_party', 'indicxlit', 'xlit-words.bin'), 'rb') as f:
            self.assertEqual(f.read(8), b'TXLW\x01\x00\x00\x00')
        self.assertEqual(
            sha256(self.dest('third_party', 'indicxlit', 'xlit-model.bin')),
            sha256(self.dest('components', 'tark_xlit', 'test', 'data', 'xlit-model.bin')))
        # The inputs were fetched into the cache and not unpacked anywhere.
        cached = os.listdir(os.path.join(self.root, 'build', 'download_cache'))
        self.assertEqual(len(cached), 3, cached)

    def test_rerun_is_idempotent(self):
        self.assertEqual(self.run_install().returncode, 0)
        before = sha256(self.dest('third_party', 'indicxlit', 'xlit-model.bin'))
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(sha256(self.dest('third_party', 'indicxlit', 'xlit-model.bin')), before)

    def test_corrupt_download_stops_setup(self):
        self.assertEqual(self.run_install().returncode, 0)
        cache = os.path.join(self.root, 'build', 'download_cache')
        with open(os.path.join(cache, 'indicxlit-e7049fe-dict.en.txt'), 'a') as f:
            f.write('tampered')
        proc = self.run_install()
        self.assertNotEqual(proc.returncode, 0)


class TestWiring(unittest.TestCase):
    def test_both_scripts_source_and_call_the_same_function(self):
        for script in ('dev.sh', 'build.sh'):
            text = read(script)
            self.assertIn('source "$_root_dir/utils/install_xlit.sh"', text, script)
            self.assertEqual(len(re.findall(r'^\s*_install_xlit$', text, re.M)), 1, script)
        # Run after Tark's own downloads are unpacked, before gn.
        for script in ('dev.sh', 'build.sh'):
            text = read(script)
            self.assertLess(text.index('downloads-onnxruntime.ini'), text.index('\n  _install_xlit\n' if script == 'dev.sh' else '\n_install_xlit\n'))

    def test_ini_is_retrieve_only(self):
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(os.path.join(REPO, 'downloads-xlit.ini'))
        self.assertEqual(set(ini.sections()), {'indicxlit_checkpoint', 'indicxlit_dict_en', 'indicxlit_dict_hi'})
        script = read('utils/install_xlit.sh')
        for section in ini.sections():
            self.assertIn('/e7049fe725b11c0a187d42edeb2f56aa1ffee5fd/', ini[section]['url'].replace('%(version)s', ini[section]['version']))
            self.assertIn(ini[section]['download_filename'], script)
            self.assertRegex(ini[section]['sha256'], r'^[0-9a-f]{64}$')
        self.assertNotIn('downloads.py" unpack', script)


if __name__ == '__main__':
    unittest.main()

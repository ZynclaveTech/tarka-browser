"""Tests for utils/publish_caption_models.sh (D4 Phase 4) in --dry-run mode:
it checks the folder against the manifest, then uploads every model file
once, immutable, and reads each back through gettarka.com."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(REPO, 'utils', 'publish_caption_models.sh')
MANIFEST = os.path.join(REPO, 'utils', 'captions_manifest.py')
sys.path.insert(0, HERE)
from test_captions_manifest import make_models  # noqa: E402


def dry_run(models, manifest):
    return subprocess.run(['bash', SCRIPT, '--dry-run', models],
                          env=dict(os.environ, TARK_CAPTIONS_MANIFEST_CC=manifest),
                          capture_output=True, text=True)


class TestPublishCaptionModels(unittest.TestCase):
    def test_uploads_every_file_immutable_then_verifies_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = make_models(os.path.join(tmp, 'models'))
            cc = os.path.join(tmp, 'model_manifest.cc')
            subprocess.run([sys.executable, MANIFEST, os.path.join(tmp, 'models'), cc], check=True)
            run = dry_run(os.path.join(tmp, 'models'), cc)
        self.assertEqual(run.returncode, 0, run.stderr)
        uploads = [l for l in run.stdout.splitlines() if l.startswith('aws s3 cp ')]
        self.assertEqual(len(uploads), len(files))
        for path, (_, sha) in files.items():
            line = next(l for l in uploads if f's3://tark-site-967555169405/models/captions/v1/{path} ' in l)
            self.assertIn('--cache-control public, max-age=31536000, immutable', line)
            self.assertIn(f'--metadata sha256={sha}', line)
            self.assertIn(f'verify https://gettarka.com/models/captions/v1/{path} {sha}', run.stdout)
        self.assertIn('--content-type application/json', next(l for l in uploads if 'vocab.json ' in l))
        self.assertIn('--content-type text/plain', next(l for l in uploads if 'LICENSE.txt ' in l))

    def test_a_changed_file_stops_before_any_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_models(os.path.join(tmp, 'models'))
            cc = os.path.join(tmp, 'model_manifest.cc')
            subprocess.run([sys.executable, MANIFEST, os.path.join(tmp, 'models'), cc], check=True)
            with open(os.path.join(tmp, 'models', 'vocab.json'), 'ab') as f:
                f.write(b'x')
            run = dry_run(os.path.join(tmp, 'models'), cc)
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn('aws s3 cp', run.stdout)


if __name__ == '__main__':
    unittest.main()

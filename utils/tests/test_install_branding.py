"""Tests for utils/install_branding.py."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import install_branding  # noqa: E402


class InstallTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.mark_dir = os.path.join(root, 'mark')
        self.tree = os.path.join(root, 'src')
        os.makedirs(os.path.join(self.mark_dir, 'tree', 'a', 'b'))
        os.makedirs(os.path.join(self.tree, 'a', 'b'))
        with open(os.path.join(self.mark_dir, 'tree', 'a', 'b', 'logo.png'), 'wb') as f:
            f.write(b'tark')
        with open(os.path.join(self.tree, 'a', 'b', 'logo.png'), 'wb') as f:
            f.write(b'chromium')
        with open(os.path.join(self.mark_dir, 'install.txt'), 'w') as f:
            f.write('# comment\npng 16x16 center mid a/b/logo.png\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_over_the_existing_file(self):
        install_branding.install(self.mark_dir, self.tree)
        with open(os.path.join(self.tree, 'a', 'b', 'logo.png'), 'rb') as f:
            self.assertEqual(f.read(), b'tark')

    def test_missing_destination_fails(self):
        os.remove(os.path.join(self.tree, 'a', 'b', 'logo.png'))
        with self.assertRaises(install_branding.MissingDestination):
            install_branding.install(self.mark_dir, self.tree)


if __name__ == '__main__':
    unittest.main()

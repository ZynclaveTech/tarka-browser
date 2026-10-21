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

    def test_another_list_only_when_asked(self):
        # Android's own icons (install-android.txt): the Mac and Windows trees
        # have none of their destinations.
        with open(os.path.join(self.mark_dir, 'tree', 'a', 'b', 'icon.png'), 'wb') as f:
            f.write(b'tark icon')
        with open(os.path.join(self.mark_dir, 'install-android.txt'), 'w') as f:
            f.write('png 48x48 center mid a/b/icon.png\n')
        self.assertEqual(install_branding.install(self.mark_dir, self.tree), 1)
        with open(os.path.join(self.tree, 'a', 'b', 'icon.png'), 'wb') as f:
            f.write(b'chromium icon')
        self.assertEqual(install_branding.install(self.mark_dir, self.tree,
                                                  ('install.txt', 'install-android.txt')), 2)
        with open(os.path.join(self.tree, 'a', 'b', 'icon.png'), 'rb') as f:
            self.assertEqual(f.read(), b'tark icon')

    def test_command_line_takes_the_lists(self):
        import subprocess
        script = os.path.join(os.path.dirname(__file__), '..', 'install_branding.py')
        with open(os.path.join(self.mark_dir, 'install-android.txt'), 'w') as f:
            f.write('png 16x16 center mid a/b/logo.png\n')
        out = subprocess.run([sys.executable, script, self.mark_dir, self.tree, 'install.txt',
                              'install-android.txt'], capture_output=True, text=True, check=True).stdout
        self.assertIn('installed 2 brand files', out)


if __name__ == '__main__':
    unittest.main()

"""android/layers.py: Tark's layer of the Android tree is put back to the
base and applied again, and a file that comes out as the last build had it
keeps that build's time, so ninja rebuilds only what changed."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'android'))
import layers  # noqa: E402


def write(path, text, mtime_ns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def mtime(path):
    return os.lstat(path).st_mtime_ns


OLD = 1_600_000_000 * 10**9  # 2020: the base's files


class Trees:
    """A base and a src made from it as cp -a would: same contents, times
    and modes."""

    def __init__(self, tmp):
        self.base = pathlib.Path(tmp) / 'src-base'
        self.src = pathlib.Path(tmp) / 'src'
        self.record = pathlib.Path(tmp) / 'layers.json'
        for root in (self.base, self.src):
            write(root / 'a.cc', 'int a;\n', OLD)
            write(root / 'c.h', '// c\n', OLD)
            write(root / 'keep' / 'k.cc', 'int k;\n', OLD)
            write(root / 'gone.txt', 'gone\n', OLD)
            (root / 'link').symlink_to('a.cc')
        write(self.src / 'out' / 'Default' / 'obj' / 'a.o', 'object')

    def tark_layer(self, a='int a; // tark\n', new='new\n', delete_gone=True):
        """What patches, substitution and Tark's steps do: rewrite a.cc,
        add a file and a folder, delete one."""
        write(self.src / 'a.cc', a)
        write(self.src / 'tark' / 'new.cc', new)
        if delete_gone and (self.src / 'gone.txt').exists():
            (self.src / 'gone.txt').unlink()

    def build(self):
        """ninja: every object is newer than everything it was built from."""
        time.sleep(0.01)
        write(self.src / 'out' / 'Default' / 'obj' / 'a.o', 'object')
        return mtime(self.src / 'out' / 'Default' / 'obj' / 'a.o')


class TestFootprint(unittest.TestCase):
    def test_lists_only_what_differs_from_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            self.assertEqual(layers.footprint(t.base, t.src), [])
            t.tark_layer()
            os.chmod(t.src / 'c.h', 0o755)
            (t.src / 'link').unlink()
            (t.src / 'link').symlink_to('c.h')
            self.assertEqual(layers.footprint(t.base, t.src), ['a.cc', 'c.h', 'gone.txt', 'link', 'tark'])

    def test_same_contents_with_another_time_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            write(t.src / 'keep' / 'k.cc', 'int k;\n')
            self.assertEqual(layers.footprint(t.base, t.src), ['keep/k.cc'])

    def test_out_is_not_part_of_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            write(t.src / 'out' / 'Default' / 'args.gn', 'x')
            self.assertEqual(layers.footprint(t.base, t.src), [])
            # Only the top-level out/: a source folder named out is source.
            write(t.src / 'keep' / 'out' / 'x.cc', 'x')
            self.assertEqual(layers.footprint(t.base, t.src), ['keep/out'])


class TestReset(unittest.TestCase):
    def test_puts_back_the_base_and_keeps_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            t.tark_layer()
            layers.reset(t.base, t.src, t.record)
            self.assertEqual((t.src / 'a.cc').read_text(), 'int a;\n')
            self.assertEqual((t.src / 'gone.txt').read_text(), 'gone\n')
            self.assertFalse((t.src / 'tark').exists())
            self.assertTrue((t.src / 'out' / 'Default' / 'obj' / 'a.o').exists())
            self.assertEqual(os.readlink(t.src / 'link'), 'a.cc')

    def test_put_back_files_are_newer_than_the_last_build(self):
        # Copied back with the base's time, a file the last layer changed
        # would look older than the objects built from that change, and
        # ninja would keep them. A reset cut short must not leave one so.
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            t.tark_layer()
            built = t.build()
            layers.reset(t.base, t.src, t.record)
            self.assertGreater(mtime(t.src / 'a.cc'), built)
            self.assertGreater(mtime(t.src / 'gone.txt'), built)

    def test_records_the_last_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            t.tark_layer()
            before = mtime(t.src / 'a.cc')
            layers.reset(t.base, t.src, t.record)
            record = json.loads(t.record.read_text())
            self.assertEqual(record['a.cc'], [hashlib.sha256(b'int a; // tark\n').hexdigest(), before])
            self.assertIn('tark/new.cc', record)
            self.assertNotIn('gone.txt', record)
            self.assertNotIn('keep/k.cc', record)


class TestSettle(unittest.TestCase):
    def layer_built_then_reset(self, t):
        t.tark_layer()
        layers.settle(t.base, t.src, t.record)
        first = {p: mtime(t.src / p) for p in ('a.cc', 'tark/new.cc')}
        built = t.build()
        layers.reset(t.base, t.src, t.record)
        return first, built

    def test_unchanged_files_keep_the_last_builds_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            first, built = self.layer_built_then_reset(t)
            t.tark_layer()
            layers.settle(t.base, t.src, t.record)
            self.assertEqual(mtime(t.src / 'a.cc'), first['a.cc'])
            self.assertEqual(mtime(t.src / 'tark' / 'new.cc'), first['tark/new.cc'])
            self.assertLess(mtime(t.src / 'a.cc'), built)

    def test_changed_files_are_newer_than_the_last_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            first, built = self.layer_built_then_reset(t)
            t.tark_layer(a='int a; // tark, changed\n')
            layers.settle(t.base, t.src, t.record)
            self.assertGreater(mtime(t.src / 'a.cc'), built)
            self.assertEqual(mtime(t.src / 'tark' / 'new.cc'), first['tark/new.cc'])

    def test_a_file_the_layer_no_longer_changes_is_newer_than_the_last_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            first, built = self.layer_built_then_reset(t)
            t.tark_layer(a='int a;\n', delete_gone=False)  # a.cc and gone.txt as in the base
            layers.settle(t.base, t.src, t.record)
            self.assertGreater(mtime(t.src / 'a.cc'), built)
            self.assertGreater(mtime(t.src / 'gone.txt'), built)

    def test_unpacked_files_with_old_times_are_newer_than_the_last_build(self):
        # Tark's steps unpack archives, whose files carry the archive's times.
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            first, built = self.layer_built_then_reset(t)
            t.tark_layer(new='newer\n')
            os.utime(t.src / 'tark' / 'new.cc', ns=(OLD + 5, OLD + 5))
            layers.settle(t.base, t.src, t.record)
            self.assertGreater(mtime(t.src / 'tark' / 'new.cc'), built)

    def test_a_failed_layer_keeps_the_last_builds_record(self):
        # A run whose layer fails (a patch does not apply) never settles: its
        # files carry that run's times. The next reset must not record them
        # over the last build's, or every later build recompiles them.
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            first, built = self.layer_built_then_reset(t)
            time.sleep(0.01)
            t.tark_layer()  # applied again, then the run stops: no settle
            layers.reset(t.base, t.src, t.record)
            t.tark_layer()
            layers.settle(t.base, t.src, t.record)
            self.assertEqual(mtime(t.src / 'a.cc'), first['a.cc'])
            self.assertLess(mtime(t.src / 'a.cc'), built)

    def test_a_settled_layer_is_recorded_again(self):
        # After a settled layer, reset records the tree as it is (a changed
        # file's new time included).
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            t.tark_layer()
            layers.settle(t.base, t.src, t.record)
            t.build()
            layers.reset(t.base, t.src, t.record)
            t.tark_layer(a='int a; // tark, changed\n')
            layers.settle(t.base, t.src, t.record)
            second = mtime(t.src / 'a.cc')
            t.build()
            layers.reset(t.base, t.src, t.record)
            t.tark_layer(a='int a; // tark, changed\n')
            layers.settle(t.base, t.src, t.record)
            self.assertEqual(mtime(t.src / 'a.cc'), second)

    def test_first_layer_without_a_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            t.tark_layer()
            os.utime(t.src / 'a.cc', ns=(OLD + 5, OLD + 5))
            layers.settle(t.base, t.src, t.record)
            self.assertGreater(mtime(t.src / 'a.cc'), OLD + 5)


class TestCommandLine(unittest.TestCase):
    def test_reset_and_settle(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Trees(tmp)
            t.tark_layer()
            tool = [sys.executable, str(REPO / 'android' / 'layers.py')]
            args = [str(t.base), str(t.src), str(t.record)]
            reset = subprocess.run(tool + ['reset'] + args, capture_output=True, text=True)
            self.assertEqual(reset.returncode, 0, reset.stderr)
            self.assertIn('put back 3', reset.stdout)
            t.tark_layer()
            settle = subprocess.run(tool + ['settle'] + args, capture_output=True, text=True)
            self.assertEqual(settle.returncode, 0, settle.stderr)
            self.assertIn('2 files as the last build had them, 0 changed', settle.stdout)
            usage = subprocess.run(tool + ['reset'], capture_output=True, text=True)
            self.assertEqual(usage.returncode, 2)


if __name__ == '__main__':
    unittest.main()

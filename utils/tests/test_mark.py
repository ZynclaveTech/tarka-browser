"""Tests for utils/mark.py: the three-dot mark as Chromium icon, SVG and PNG."""
import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import mark  # noqa: E402
import tokens  # noqa: E402

MID = {'amber': '#b78100', 'coral': '#e63e5c', 'indigo': '#6c63ff'}


def decode_png(data):
    """Returns (width, height, rows of (r, g, b, a)) for an 8-bit RGBA PNG."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, width, height = 8, b'', 0, 0
    while pos < len(data):
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b'IHDR':
            width, height, depth, colour = struct.unpack('>IIBB', chunk[:10])
            assert (depth, colour) == (8, 6)
        elif kind == b'IDAT':
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    rows, stride = [], width * 4 + 1
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        assert line[0] == 0, 'filter type 0 only'
        rows.append([tuple(line[1 + x * 4:5 + x * 4]) for x in range(width)])
    return width, height, rows


def rgb(hex_colour):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


class IconTextTest(unittest.TestCase):

    def test_three_coloured_circles_per_canvas(self):
        text = mark.icon_text([24])
        lines = [l for l in text.splitlines() if l and not l.startswith('//')]
        self.assertEqual(sum(l.startswith('CIRCLE,') for l in lines), 3)
        colours = [l for l in lines if l.startswith('PATH_COLOR_ARGB')]
        self.assertEqual(len(colours), 3)
        for hex_colour in MID.values():
            r, g, b = rgb(hex_colour)
            self.assertIn('PATH_COLOR_ARGB, 0xFF, 0x%02X, 0x%02X, 0x%02X,' % (r, g, b), colours)
        self.assertTrue(lines[0].startswith('CANVAS_DIMENSIONS, 24,'))

    def test_one_representation_per_canvas(self):
        text = mark.icon_text([32, 16])
        self.assertEqual(text.count('CANVAS_DIMENSIONS'), 2)
        self.assertEqual(text.count('CIRCLE,'), 6)

    def test_last_token_has_no_trailing_comma(self):
        self.assertFalse(mark.icon_text([15]).rstrip().endswith(','))

    def test_circles_fit_inside_the_canvas(self):
        for line in mark.icon_text([15]).splitlines():
            if line.startswith('CIRCLE,'):
                cx, cy, r = (float(v) for v in line.split(',')[1:4] if v.strip())
                self.assertGreaterEqual(cx - r, 0)
                self.assertLessEqual(cx + r, 15)
                self.assertGreaterEqual(cy - r, 0)
                self.assertLessEqual(cy + r, 15)


class PngTest(unittest.TestCase):

    def test_square_mark_colours_and_transparent_corners(self):
        width, height, rows = decode_png(mark.png(64, 64))
        self.assertEqual((width, height), (64, 64))
        for corner in (rows[0][0], rows[0][-1], rows[-1][0], rows[-1][-1]):
            self.assertEqual(corner[3], 0)
        for name, (cx, cy) in mark.centres(64, 64).items():
            self.assertEqual(rows[int(cy)][int(cx)], rgb(MID[name]) + (255,))

    def test_small_favicon_size(self):
        width, height, _ = decode_png(mark.png(16, 16))
        self.assertEqual((width, height), (16, 16))

    def test_wordmark_canvas_is_left_aligned(self):
        width, height, rows = decode_png(mark.png(97, 22, align='left'))
        self.assertEqual((width, height), (97, 22))
        right_half = [px for row in rows for px in row[width // 2:]]
        self.assertTrue(all(px[3] == 0 for px in right_half))

    def test_white_palette(self):
        _, _, rows = decode_png(mark.png(32, 32, palette='white'))
        opaque = {px[:3] for row in rows for px in row if px[3] == 255}
        self.assertEqual(opaque, {(255, 255, 255)})

    def test_deterministic(self):
        self.assertEqual(mark.png(48, 48), mark.png(48, 48))
        self.assertEqual(mark.icon_text([24]), mark.icon_text([24]))


def decode_ico(data):
    """Returns [(size, image bytes)] for each entry of a Windows .ico."""
    reserved, kind, count = struct.unpack('<HHH', data[:6])
    assert (reserved, kind) == (0, 1)
    entries = []
    for i in range(count):
        width, height, _, _, planes, bits, length, offset = struct.unpack(
            '<BBBBHHII', data[6 + 16 * i:22 + 16 * i])
        assert width == height and (planes, bits) == (1, 32)
        entries.append((width or 256, data[offset:offset + length]))
    return entries


class IcoTest(unittest.TestCase):

    def test_one_entry_per_size(self):
        sizes = [size for size, _ in decode_ico(mark.ico([16, 32, 48, 256]))]
        self.assertEqual(sizes, [16, 32, 48, 256])

    def test_small_sizes_are_32_bit_bitmaps_of_the_mark(self):
        # A bottom-up BGRA bitmap (height doubled for the AND mask), the
        # pixels the PNG of that size has.
        _, image = decode_ico(mark.ico([32]))[0]
        header, width, height, planes, bits = struct.unpack('<IiiHH', image[:16])
        self.assertEqual((header, width, height, planes, bits), (40, 32, 64, 1, 32))
        _, _, rows = decode_png(mark.png(32, 32))
        pixels = image[40:40 + 32 * 32 * 4]
        for y in range(32):
            for x in range(32):
                b, g, r, a = pixels[((31 - y) * 32 + x) * 4:((31 - y) * 32 + x) * 4 + 4]
                self.assertEqual((r, g, b, a), rows[y][x], (x, y))
        self.assertEqual(len(image), 40 + 32 * 32 * 4 + 32 * 4)

    def test_256_is_the_png(self):
        _, image = decode_ico(mark.ico([256]))[0]
        self.assertEqual(image, mark.png(256, 256))

    def test_manifest_kind(self):
        entry = mark.Entry('ico', ('16,256', 'mid'), 'x.ico')
        self.assertEqual(mark.render(entry), mark.ico([16, 256]))


class SvgTest(unittest.TestCase):

    def test_three_circles_in_mid_palette(self):
        text = mark.svg()
        self.assertEqual(text.count('<circle'), 3)
        for hex_colour in MID.values():
            self.assertIn('fill="%s"' % hex_colour, text)
        self.assertIn('viewBox="0 0 44 36"', text)


class PaletteTest(unittest.TestCase):

    def test_mid_palette_holds_three_to_one_on_every_surface(self):
        surfaces = [tokens.DARK['paper'], tokens.DARK['raised'],
                    tokens.LIGHT['paper'], tokens.LIGHT['raised']]
        for name, hex_colour in mark.PALETTES['mid'].items():
            for surface in surfaces:
                ratio = tokens.contrast(hex_colour, surface)
                self.assertGreaterEqual(ratio, 3.0, '%s on %s is %.2f' % (name, surface, ratio))
        self.assertEqual(mark.PALETTES['mid'], MID)


class ManifestTest(unittest.TestCase):

    def test_generated_files_match_the_committed_ones(self):
        here = os.path.dirname(__file__)
        mark_dir = os.path.join(here, '..', '..', 'resources', 'branding', 'mark')
        entries = mark.read_manifest(os.path.join(mark_dir, 'install.txt'))
        self.assertTrue(entries)
        for entry in entries:
            with open(os.path.join(mark_dir, 'tree', entry.dest), 'rb') as f:
                self.assertEqual(f.read(), mark.render(entry), entry.dest)


if __name__ == '__main__':
    unittest.main()

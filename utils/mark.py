#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tark's three-dot mark as a Chromium vector icon, an SVG, PNGs and Windows .ico files (spec 6.3).

The mark comes from the Shodhya site's masthead (resources/branding/app-icon.svg):
three circles of radius 7 in a 44x36 box, amber top, coral bottom-left, indigo
bottom-right. Native icons cannot change colour with the appearance, so they
use the mid palette, which holds 3:1 on paper and raised in both modes.

    python3 utils/mark.py --out resources/branding/mark

writes every file listed in resources/branding/mark/install.txt under
resources/branding/mark/tree/, at the path it replaces in the Chromium tree.
utils/install_branding.py copies them into the tree at setup.
"""

import argparse
import collections
import os
import struct
import zlib

PALETTES = {
    'mid': {'amber': '#b78100', 'coral': '#e63e5c', 'indigo': '#6c63ff'},
    'white': {'amber': '#ffffff', 'coral': '#ffffff', 'indigo': '#ffffff'},
    'black': {'amber': '#000000', 'coral': '#000000', 'indigo': '#000000'},
}

# (name, cx, cy) in the 44x36 box; every circle has radius 7. The circles
# span x 2..42 and y 2..34, a 40x32 block.
CIRCLES = (('amber', 22, 9), ('coral', 9, 27), ('indigo', 35, 27))
RADIUS = 7
_LEFT, _TOP, _WIDTH, _HEIGHT = 2, 2, 40, 32
_SAMPLES = 4  # per axis, for anti-aliasing

HEADER = ('// Copyright 2026 The Tark Authors\n'
          '// Use of this source code is governed by a BSD-style license that can be\n'
          '// found in the LICENSE file.\n'
          '// Tark: the three-dot mark (utils/mark.py), replacing Chromium\'s logo.\n')

Entry = collections.namedtuple('Entry', 'kind spec dest')


def _fit(width, height, align='center'):
    """Scale and offset placing the mark in a width x height box.

    The mark keeps a margin of 1/16 of the shorter side. align='left' puts it
    at the left edge (for canvases that held a logo beside a wordmark).
    """
    pad = min(width, height) / 16
    scale = min((width - 2 * pad) / _WIDTH, (height - 2 * pad) / _HEIGHT)
    left = pad if align == 'left' else (width - _WIDTH * scale) / 2
    top = (height - _HEIGHT * scale) / 2
    return scale, left - _LEFT * scale, top - _TOP * scale


def centres(width, height, align='center'):
    """Each circle's centre, in pixels, in a width x height box."""
    scale, dx, dy = _fit(width, height, align)
    return {name: (dx + cx * scale, dy + cy * scale) for name, cx, cy in CIRCLES}


def _num(value):
    text = ('%.2f' % value).rstrip('0').rstrip('.')
    return text if text not in ('', '-0') else '0'


def _argb(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 'PATH_COLOR_ARGB, 0xFF, 0x%02X, 0x%02X, 0x%02X,' % (r, g, b)


def icon_text(canvases, palette='mid'):
    """A Chromium .icon file: one representation per canvas size."""
    colours = PALETTES[palette]
    lines = []
    for canvas in canvases:
        scale, dx, dy = _fit(canvas, canvas)
        lines.append('CANVAS_DIMENSIONS, %d,' % canvas)
        for index, (name, cx, cy) in enumerate(CIRCLES):
            if index:
                lines.append('NEW_PATH,')
            lines.append(_argb(colours[name]))
            lines.append('CIRCLE, %s, %s, %s,' % (_num(dx + cx * scale), _num(dy + cy * scale),
                                                  _num(RADIUS * scale)))
    lines[-1] = lines[-1].rstrip(',')
    return HEADER + '\n' + '\n'.join(lines) + '\n'


def svg(palette='mid'):
    colours = PALETTES[palette]
    circles = ''.join('<circle cx="%d" cy="%d" r="%d" fill="%s"/>' % (cx, cy, RADIUS, colours[name])
                      for name, cx, cy in CIRCLES)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 36" role="img" '
            'aria-label="Tark">%s</svg>\n' % circles)


def _chunk(kind, data):
    return (struct.pack('>I', len(data)) + kind + data +
            struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))


def _pixels(width, height, align='center', palette='mid'):
    """Rows of (r, g, b, a): the mark, anti-aliased, on transparency."""
    colours = PALETTES[palette]
    scale, dx, dy = _fit(width, height, align)
    radius = RADIUS * scale
    circles = [(dx + cx * scale, dy + cy * scale, radius * radius,
                tuple(int(colours[name][i:i + 2], 16) for i in (1, 3, 5)))
               for name, cx, cy in CIRCLES]
    offsets = [(i + 0.5) / _SAMPLES for i in range(_SAMPLES)]
    total = _SAMPLES * _SAMPLES
    # A pixel whose centre is further than half its diagonal from the edge
    # is all inside or all outside: every sample agrees, so skip sampling.
    inner, outer = max(radius - 0.75, 0) ** 2, (radius + 0.75) ** 2
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            pixel = (0, 0, 0, 0)
            for ccx, ccy, r2, colour in circles:
                d2 = (x + 0.5 - ccx) ** 2 + (y + 0.5 - ccy) ** 2
                if d2 >= outer:
                    continue
                if d2 <= inner:
                    pixel = colour + (255,)
                    break
                hits = sum(1 for oy in offsets for ox in offsets
                           if (x + ox - ccx) ** 2 + (y + oy - ccy) ** 2 <= r2)
                if hits:
                    pixel = colour + ((hits * 255 + total // 2) // total,)
                    break
            row.append(pixel)
        rows.append(row)
    return rows


def png(width, height, align='center', palette='mid'):
    """An RGBA PNG of the mark on a transparent background."""
    raw = bytearray()
    for row in _pixels(width, height, align, palette):
        raw.append(0)
        for pixel in row:
            raw.extend(pixel)
    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', header) +
            _chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + _chunk(b'IEND', b''))


def _dib(size, palette):
    """A 32-bit bottom-up BGRA bitmap for an .ico entry: the header gives
    twice the height (image plus AND mask); the mask is all zero, since the
    alpha channel carries the shape."""
    header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    body = bytearray()
    for row in reversed(_pixels(size, size, palette=palette)):
        for r, g, b, a in row:
            body.extend((b, g, r, a))
    mask = bytes(((size + 31) // 32) * 4 * size)
    return header + bytes(body) + mask


def ico(sizes, palette='mid'):
    """A Windows .ico of the mark: 32-bit bitmaps below 256 px and a PNG at
    256, as Chromium's own icons are made."""
    images = [png(size, size, palette=palette) if size >= 256 else _dib(size, palette)
              for size in sizes]
    offset = 6 + 16 * len(sizes)
    out = struct.pack('<HHH', 0, 1, len(sizes))
    for size, image in zip(sizes, images):
        side = 0 if size >= 256 else size
        out += struct.pack('<BBBBHHII', side, side, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return out + b''.join(images)


def read_manifest(path):
    """Entries of install.txt: 'icon 32,16 <dest>', 'png 97x22 left mid <dest>',
    'svg mid <dest>', 'ico 16,32,256 mid <dest>'. Blank lines and # comments are skipped."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            entries.append(Entry(parts[0], tuple(parts[1:-1]), parts[-1]))
    return entries


def render(entry):
    """The bytes for one manifest entry."""
    if entry.kind == 'icon':
        return icon_text([int(c) for c in entry.spec[0].split(',')]).encode()
    if entry.kind == 'png':
        size, align, palette = entry.spec
        width, height = (int(v) for v in size.split('x'))
        return png(width, height, align, palette)
    if entry.kind == 'svg':
        return svg(entry.spec[0]).encode()
    if entry.kind == 'ico':
        sizes, palette = entry.spec
        return ico([int(v) for v in sizes.split(',')], palette)
    raise ValueError('unknown kind %r in %s' % (entry.kind, entry.dest))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', required=True, help='resources/branding/mark')
    args = parser.parse_args()
    for entry in read_manifest(os.path.join(args.out, 'install.txt')):
        path = os.path.join(args.out, 'tree', entry.dest)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(render(entry))


if __name__ == '__main__':
    main()

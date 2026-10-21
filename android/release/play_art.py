#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""The Play listing's artwork from Tark's mark (A5).

    play_art.py OUTDIR

icon-512.png (the store icon; Play rounds its corners, so the mark keeps to
the middle 70%) and feature-1024x500.png (the banner), both the mark on
Tark's paper colour, 8-bit RGB with no transparency, as Play asks.
"""

import pathlib
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'utils'))
import mark  # noqa: E402

PAPER = (0xf6, 0xf1, 0xe7)  # utils/tokens.py, light "paper"


def _rgb_png(width, height, mark_side):
    """The mark, mark_side pixels square, centred on paper."""
    marks = mark._pixels(mark_side, mark_side)
    left, top = (width - mark_side) // 2, (height - mark_side) // 2
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            r, g, b = PAPER
            my, mx = y - top, x - left
            if 0 <= my < mark_side and 0 <= mx < mark_side:
                cr, cg, cb, a = marks[my][mx]
                r = (cr * a + r * (255 - a) + 127) // 255
                g = (cg * a + g * (255 - a) + 127) // 255
                b = (cb * a + b * (255 - a) + 127) // 255
            raw.extend((r, g, b))
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + mark._chunk(b'IHDR', header) +
            mark._chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + mark._chunk(b'IEND', b''))


def write(outdir):
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'icon-512.png').write_bytes(_rgb_png(512, 512, 358))
    (outdir / 'feature-1024x500.png').write_bytes(_rgb_png(1024, 500, 300))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    write(sys.argv[1])

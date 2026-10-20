#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Open every Settings screen of Tark for Android (the top level and the
Privacy and security screens) and report any that crashes.

usage: walk_settings.py [--serial SERIAL] [--allow-device] [--dividers]
Defaults to the emulator (emulator-5554); a real phone only with
--allow-device. Exits 1 if any screen crashed or could not be found.

--dividers (A3): also checks that every screen with a list of two or more
rows draws a hairline between rows somewhere, from a screenshot; prints
"divider ok", "divider MISSING" or "divider n/a" per screen, and exits 1 on
any missing.
"""
import argparse
import re
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PACKAGE = 'com.gettarka.tarka'
SETTINGS = PACKAGE + '/org.chromium.chrome.browser.settings.SettingsActivity'
PRIVACY = 'Privacy and security'


class Device:
    def __init__(self, serial):
        self.adb = ['adb', '-s', serial]

    def run(self, *args):
        return subprocess.run(self.adb + list(args), capture_output=True, text=True).stdout

    def shell(self, *args):
        return self.run('shell', *args)

    def rows(self):
        """(title, x, y) of the preference titles on screen."""
        self.shell('uiautomator', 'dump', '/sdcard/ui.xml')
        xml = self.shell('cat', '/sdcard/ui.xml')
        found = []
        for m in re.finditer(r'text="([^"]+)" resource-id="android:id/title"[^>]*'
                             r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
            x1, y1, x2, y2 = map(int, m.groups()[1:])
            found.append((m.group(1), (x1 + x2) // 2, (y1 + y2) // 2))
        return found

    def scroll(self):
        self.shell('input', 'swipe', '540', '1900', '540', '700', '300')
        time.sleep(1.5)

    def open_settings(self):
        # A fresh start each time: an open Settings task keeps its back stack
        # and scroll position, and rows above it are never found. Some rows
        # (Notifications) open Android's own settings app, which would stay
        # in front: stop it too.
        self.shell('am', 'force-stop', PACKAGE)
        self.shell('am', 'force-stop', 'com.android.settings')
        self.shell('am', 'start', '-n', SETTINGS)
        time.sleep(4)

    def crashes(self):
        log = self.run('logcat', '-d')
        return [l for l in log.splitlines() if 'Fatal signal' in l or 'FATAL EXCEPTION' in l]

    def alive(self):
        return self.shell('pidof', PACKAGE).strip() != ''


def parse_screencap(data):
    """(width, height, RGBA bytes) of `adb exec-out screencap` output, whose
    header is 12 bytes, or 16 from Android 10 (a colour space)."""
    width, height = struct.unpack('<II', data[:8])
    header = len(data) - width * height * 4
    if header not in (12, 16):
        raise ValueError(f'not a raw screencap of {width}x{height}')
    return width, height, data[header:]


def _pixel(img, x, y):
    width, _, px = img
    i = (y * width + x) * 4
    return px[i:i + 3]


def _close(a, b, tolerance):
    return all(abs(p - q) <= tolerance for p, q in zip(a, b))


def has_hairline(img, y_from, y_to, x_from, x_to):
    """Whether one colour, unlike the background just above, runs across
    [x_from, x_to) at some y in [y_from, y_to]."""
    _, height, _ = img
    background = _pixel(img, (x_from + x_to) // 2, max(0, y_from - 6))
    xs = range(x_from, x_to, max(1, (x_to - x_from) // 40))
    for y in range(max(0, y_from), min(height, y_to + 1)):
        colours = [_pixel(img, x, y) for x in xs]
        same = sum(1 for c in colours if _close(c, colours[0], 6))
        if same >= 0.9 * len(colours) and not _close(colours[0], background, 8):
            return True
    return False


def list_items(xml):
    """The bounds (x1, y1, x2, y2) of the settings list's rows, top to bottom:
    the children of the screen's RecyclerView."""
    bounds = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
    for node in ET.fromstring(xml).iter('node'):
        if node.get('class', '').endswith('RecyclerView'):
            return [tuple(map(int, bounds.match(child.get('bounds')).groups()))
                    for child in node.findall('node')]
    return []


def screen_has_dividers(img, items):
    """Whether a hairline runs across the middle of any boundary between two
    adjacent rows (category headers legitimately have none)."""
    for a, b in zip(items, items[1:]):
        if abs(b[1] - a[3]) > 2:
            continue
        inset = (a[2] - a[0]) // 5
        if has_hairline(img, a[3] - 3, a[3] + 2, a[0] + inset, a[2] - inset):
            return True
    return False


def check_dividers(dev):
    """'ok', 'MISSING' or 'n/a' (fewer than two rows) for the screen shown."""
    dev.shell('uiautomator', 'dump', '/sdcard/ui.xml')
    items = list_items(dev.shell('cat', '/sdcard/ui.xml'))
    if len(items) < 2:
        return 'n/a'
    data = subprocess.run(dev.adb + ['exec-out', 'screencap'], capture_output=True).stdout
    return 'ok' if screen_has_dividers(parse_screencap(data), items) else 'MISSING'


def collect(dev, pages=4):
    titles = []
    for _ in range(pages):
        for title, _, _ in dev.rows():
            if title not in titles:
                titles.append(title)
        dev.scroll()
    return titles


def tap(dev, title):
    for _ in range(6):
        spot = next(((x, y) for t, x, y in dev.rows() if t == title), None)
        if spot:
            dev.shell('input', 'tap', str(spot[0]), str(spot[1]))
            time.sleep(3)
            return True
        dev.scroll()
    return False


def visit(dev, path, on_screen=None):
    """Opens Settings, taps each title in path; returns 'ok', 'missing' or
    'crash'. on_screen(dev) runs on the screen reached."""
    dev.open_settings()
    for title in path:
        if not tap(dev, title):
            return 'missing'
    if on_screen:
        on_screen(dev)
    bad = dev.crashes() or not dev.alive()
    dev.run('logcat', '-c')
    if not dev.alive():
        dev.shell('monkey', '-p', PACKAGE, '-c', 'android.intent.category.LAUNCHER', '1')
        time.sleep(8)
    return 'crash' if bad else 'ok'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('--allow-device', action='store_true')
    parser.add_argument('--dividers', action='store_true')
    args = parser.parse_args(argv)
    if not args.serial.startswith('emulator-') and not args.allow_device:
        print(f'{args.serial} is not an emulator; pass --allow-device to walk a phone', file=sys.stderr)
        return 2
    dev = Device(args.serial)
    dev.run('logcat', '-c')
    dev.open_settings()
    top = collect(dev)
    dev.open_settings()
    tap(dev, PRIVACY)
    privacy = [t for t in collect(dev) if t not in top]
    failed = 0
    for path in [[]] + [[t] for t in top] + [[PRIVACY, t] for t in privacy]:
        divider = []
        if not path and not args.dividers:
            continue
        result = visit(dev, path, (lambda d: divider.append(check_dividers(d))) if args.dividers else None)
        failed += result != 'ok'
        print(f'{result:8} ' + (' > '.join(path) or 'Settings'))
        if divider:
            failed += divider[0] == 'MISSING'
            print(f'divider {divider[0]} ' + (' > '.join(path) or 'Settings'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

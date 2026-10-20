#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Open every Settings screen of Tark for Android (the top level and the
Privacy and security screens) and report any that crashes.

usage: walk_settings.py [--serial SERIAL] [--allow-device]
Defaults to the emulator (emulator-5554); a real phone only with
--allow-device. Exits 1 if any screen crashed or could not be found.
"""
import argparse
import re
import subprocess
import sys
import time

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


def visit(dev, path):
    """Opens Settings, taps each title in path; returns 'ok', 'missing' or 'crash'."""
    dev.open_settings()
    for title in path:
        if not tap(dev, title):
            return 'missing'
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
    for path in [[t] for t in top] + [[PRIVACY, t] for t in privacy]:
        result = visit(dev, path)
        failed += result != 'ok'
        print(f'{result:8} ' + ' > '.join(path))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

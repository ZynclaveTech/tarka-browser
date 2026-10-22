#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""End-to-end checks of the Indian-language rows on the emulator (A3).

    run.py FILES_DIR [--serial emulator-5554] [CASES...]
        cases: offer decline wifi now rows keyword tamper languages

FILES_DIR is a build's third_party/indicxlit/android/ (android/xlit/files.py
build): this Mac serves its files under their sha256 names, as gettarka.com
does, through adb reverse (port 8001), and the browser is pointed at it with
--tark-xlit-base-url (read from Chrome's command-line file, which needs the
emulator's root). Each case starts from a cleared app. Prints "ok CASE" or
"FAIL CASE: why"; exits 1 if any fails. Emulator only.
"""

import argparse
import hashlib
import http.server
import json
import pathlib
import re
import socketserver
import subprocess
import sys
import threading
import time

PACKAGE = 'com.gettarka.tarka'
PORT = 8001
NAMASTE = 'नमस्ते'
HINDI = 'हिन्दी'
OFFER = f'Type in {HINDI}?'

REQUESTS = []          # paths the browser asked for, in order
ACCEPT = {'via': 'offer'}  # or 'settings': Settings > Languages' switch
SERVER = {'tamper': False, 'files': {}}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        REQUESTS.append(self.path)
        data = SERVER['files'].get(self.path.lstrip('/'))
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        if SERVER['tamper'] and len(data) > 100:
            data = data[:100] + bytes([data[100] ^ 1]) + data[101:]
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def load_files(files_dir):
    table = json.loads((files_dir / 'files.json').read_text())
    for name, entry in table.items():
        data = (files_dir / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256'], name
        SERVER['files'][entry['sha256'] + '.bin'] = data
    return {entry['sha256'] + '.bin': name for name, entry in table.items()}


class Device:
    def __init__(self, serial):
        self.adb = ['adb', '-s', serial]

    def run(self, *args):
        return subprocess.run(self.adb + list(args), capture_output=True, text=True).stdout

    def shell(self, *args):
        return self.run('shell', *args)

    def fresh(self, flags=()):
        """A cleared app pointed at this Mac's server, with Wi-Fi on."""
        self.run('root')
        self.run('wait-for-device')
        self.run('reverse', f'tcp:{PORT}', f'tcp:{PORT}')
        self.shell('svc', 'wifi', 'enable')
        self.shell('svc', 'data', 'enable')
        self.shell('pm', 'clear', PACKAGE)
        line = ' '.join(['_', f'--tark-xlit-base-url=http://127.0.0.1:{PORT}/'] + list(flags))
        self.shell(f"echo '{line}' > /data/local/tmp/chrome-command-line")
        REQUESTS.clear()
        self.start()

    def start(self):
        # Chrome writes Local State a few seconds after a change.
        time.sleep(12)
        self.shell('am', 'force-stop', PACKAGE)
        self.run('logcat', '-c')
        self.shell('am', 'start', '-n', f'{PACKAGE}/com.google.android.apps.chrome.Main')
        time.sleep(6)
        # A fresh profile asks about notifications first: Tark's own sheet,
        # then Android's.
        if 'notification_permission_rationale' in self.screen():
            tap_text(self, 'No thanks', tries=2)
            tap_text(self, 'Don’t allow', tries=2)

    def teardown(self):
        self.shell('rm', '-f', '/data/local/tmp/chrome-command-line')
        self.shell('svc', 'wifi', 'enable')
        self.shell('svc', 'data', 'enable')
        self.run('reverse', '--remove', f'tcp:{PORT}')

    def screen(self):
        # uiautomator dumps only an idle screen ("could not get idle state"
        # while a page plays media) and then leaves the previous ui.xml in
        # place: remove it first, so a failed dump reads as nothing rather
        # than as an old screen.
        for _ in range(3):
            self.shell('rm', '-f', '/sdcard/ui.xml')
            self.shell('uiautomator', 'dump', '/sdcard/ui.xml')
            xml = self.shell('cat', '/sdcard/ui.xml')
            if '<hierarchy' in xml:
                return xml
            time.sleep(1)
        return ''

    def logged(self, text, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if text in self.run('logcat', '-d', '-s', 'chromium:*'):
                return True
            time.sleep(2)
        return False

    def files(self):
        out = self.shell('find', f'/data/user/0/{PACKAGE}', '-name', 'xlit-*')
        return sorted(pathlib.PurePosixPath(l.strip()).name for l in out.splitlines() if l.strip())


def tap_text(dev, text, tries=5, contains=False):
    for _ in range(tries):
        xml = dev.screen()
        pattern = (r'text="[^"]*' + re.escape(text) + r'[^"]*"' if contains
                   else r'text="' + re.escape(text) + r'"')
        m = re.search(pattern + r'[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            dev.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
            time.sleep(1.5)
            return True
        time.sleep(1)
    return False


def type_in_address_bar(dev, text):
    """Focuses the address bar and types `text`; returns the suggestions
    screen's XML."""
    m = None
    for _ in range(5):
        xml = dev.screen()
        # Tark's notifications sheet can come up a few seconds after start.
        if 'notification_permission_rationale' in xml:
            tap_text(dev, 'No thanks', tries=1)
            tap_text(dev, 'Don’t allow', tries=2)
            xml = dev.screen()
        m = re.search(r'resource-id="[^"]*(?:url_bar|search_box_text)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
        if m:
            break
        time.sleep(1)
    if not m:
        raise RuntimeError('no address bar')
    x1, y1, x2, y2 = map(int, m.groups())
    last = text.split(' ')[-1]
    for _ in range(3):
        dev.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(1)
        # Select all, then delete: whatever was typed before goes.
        dev.shell('input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
        dev.shell('input', 'keyevent', 'KEYCODE_DEL')
        for word in text.split(' '):
            if word:
                dev.shell('input', 'text', word)
            dev.shell('input', 'keyevent', 'KEYCODE_SPACE')
        dev.shell('input', 'keyevent', 'KEYCODE_DEL')
        time.sleep(2.5)
        # A key can arrive late or be lost (once the trailing space was, and
        # the delete took the last letter): the rows are read only once the
        # address bar holds the whole last word.
        xml = dev.screen()
        typed = address_bar_text(xml)
        if typed is None or typed.endswith(last):
            return xml
    return xml


def address_bar_text(xml):
    m = re.search(r'text="([^"]*)" resource-id="[^"]*(?:url_bar|search_box_text)"', xml)
    return m.group(1) if m else None


def rows(xml):
    """(first line, label) of each suggestion row."""
    out = []
    for m in re.finditer(r'text="([^"]*)" resource-id="[^"]*:id/line_1"', xml):
        rest = xml[m.end():m.end() + 1500]
        label = re.search(r'text="([^"]*)" resource-id="[^"]*:id/tark_xlit_label"', rest)
        out.append((m.group(1), label.group(1) if label else ''))
    return out


def accept_in_settings(dev):
    """Turns on Settings > Languages > Indian-language suggestions (on Wi-Fi)."""
    dev.shell('am', 'start', '-n', f'{PACKAGE}/org.chromium.chrome.browser.settings.SettingsActivity')
    time.sleep(3)
    for _ in range(4):
        if tap_text(dev, 'Languages', tries=1):
            break
        dev.shell('input', 'swipe', '540', '1800', '540', '700', '300')
    for _ in range(4):
        if tap_text(dev, 'Indian-language suggestions', tries=1):
            return ''
        dev.shell('input', 'swipe', '540', '1800', '540', '700', '300')
    return 'no Indian-language suggestions switch'


def accept(dev, button):
    if ACCEPT['via'] == 'settings' and button != 'No thanks':
        why = accept_in_settings(dev)
        # Back to the browser without closing the app.
        dev.shell('am', 'start', '-n', f'{PACKAGE}/com.google.android.apps.chrome.Main')
        time.sleep(2)
        return why
    xml = type_in_address_bar(dev, 'namaste')
    if not any(line == OFFER for line, _ in rows(xml)):
        return f'no offer row: {rows(xml)}'
    if not tap_text(dev, OFFER):
        return 'could not tap the offer'
    if not tap_text(dev, button):
        return f'no "{button}" button'
    return ''


def case_offer(dev):
    dev.fresh()
    xml = type_in_address_bar(dev, 'namaste')
    found = rows(xml)
    if not any(line == OFFER for line, _ in found):
        return f'no "{OFFER}" row: {found}'
    if any(line == NAMASTE for line, _ in found):
        return 'a row before the download'
    if REQUESTS:
        return f'typing fetched {REQUESTS}'
    return ''


def case_decline(dev):
    dev.fresh()
    why = accept(dev, 'No thanks')
    if why:
        return why
    dev.start()
    found = rows(type_in_address_bar(dev, 'namaste'))
    if any(line == OFFER for line, _ in found):
        return 'the offer came back after "No thanks"'
    return 'fetched after "No thanks"' if REQUESTS else ''


def case_now(dev):
    dev.fresh()
    dev.shell('svc', 'wifi', 'disable')
    time.sleep(3)
    why = accept(dev, 'Download now')
    if why:
        return why
    if not dev.logged('tark xlit: ready', 180):
        return f'not ready on mobile data after "Download now"; requests {REQUESTS}'
    return ''


def case_wifi(dev):
    dev.fresh()
    dev.shell('svc', 'wifi', 'disable')
    time.sleep(3)
    why = accept(dev, 'Download on Wi-Fi')
    if why:
        return why
    time.sleep(15)
    if REQUESTS:
        return f'downloaded on mobile data: {REQUESTS}'
    dev.shell('svc', 'wifi', 'enable')
    if not dev.logged('tark xlit: ready', 180):
        return 'not ready after Wi-Fi came back'
    return ''


def case_rows(dev):
    dev.fresh()
    why = accept(dev, 'Download on Wi-Fi')
    if why:
        return why
    if not dev.logged('tark xlit: ready', 180):
        return 'not ready'
    dev.start()
    xml = type_in_address_bar(dev, 'namaste')
    found = rows(xml)
    if (NAMASTE, HINDI) not in found:
        return f'no "{NAMASTE}" row labelled "{HINDI}": {found}'
    if not re.search(r'content-desc="[^"]*' + re.escape(NAMASTE) + r'[^"]*' + re.escape(HINDI), xml):
        return 'the label is not read out'
    # Typing on quickly: the rows are for the whole word, never "namas".
    xml = type_in_address_bar(dev, 'namas')
    dev.shell('input', 'text', 'te')
    time.sleep(2.5)
    devanagari = [line for line, _ in rows(dev.screen()) if re.search('[ऀ-ॿ]', line)]
    if devanagari != [NAMASTE]:
        return f'rows after fast typing: {devanagari}'
    return ''


def case_keyword(dev):
    dev.fresh()
    why = accept(dev, 'Download on Wi-Fi')
    if why or not dev.logged('tark xlit: ready', 180):
        return why or 'not ready'
    dev.start()
    found = rows(type_in_address_bar(dev, '@wiki namaste'))
    if not any(line == NAMASTE for line, _ in found):
        return f'no row under @wiki: {found}'
    if not tap_text(dev, NAMASTE):
        return 'could not choose the row'
    time.sleep(3)
    if 'hi.wikipedia.org' not in dev.screen():
        return 'the @wiki row did not go to Hindi Wikipedia'
    found = rows(type_in_address_bar(dev, '@bookmarks namaste'))
    if any(re.search('[ऀ-ॿ]', line) for line, _ in found):
        return f'rows under @bookmarks: {found}'
    return ''


def case_tamper(dev):
    dev.fresh()
    SERVER['tamper'] = True
    try:
        why = accept(dev, 'Download now')
        if why:
            return why
        time.sleep(90)
        if dev.logged('tark xlit: ready', 1):
            return 'a wrong file was accepted'
        if 'xlit-model.bin' in dev.files() and 'xlit-words-hi.bin' in dev.files():
            return 'a wrong file was kept'
        if any(line == NAMASTE for line, _ in rows(type_in_address_bar(dev, 'namaste'))):
            return 'rows from a wrong file'
        return ''
    finally:
        SERVER['tamper'] = False


def case_languages(dev):
    dev.fresh()
    why = accept(dev, 'Download on Wi-Fi')
    if why or not dev.logged('tark xlit: ready', 180):
        return why or 'not ready'
    # Tamil added to the languages (the profile's accept languages), then a
    # restart: its list downloads; Hindi's stays.
    dev.shell('am', 'force-stop', PACKAGE)
    prefs = f'/data/user/0/{PACKAGE}/app_chrome/Default/Preferences'
    data = json.loads(dev.shell('cat', prefs) or '{}')
    # Android rebuilds accept_languages from selected_languages: set both.
    data.setdefault('intl', {}).update(accept_languages='ta,en-US,en', selected_languages='ta,en-US,en')
    dev.shell(f"cat > {prefs} <<'JSON'\n{json.dumps(data)}\nJSON")
    dev.start()
    end = time.time() + 120
    while time.time() < end and 'xlit-words-ta.bin' not in dev.files():
        time.sleep(3)
    files = dev.files()
    if 'xlit-words-ta.bin' not in files or 'xlit-words-hi.bin' not in files:
        return f'files after adding Tamil: {files}'
    return ''


CASES = {name[5:]: fn for name, fn in globals().items() if name.startswith('case_')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('files_dir', type=pathlib.Path)
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('--accept', choices=['offer', 'settings'], default='offer',
                        help='how a case says yes: the offer row, or the Settings switch')
    parser.add_argument('cases', nargs='*', default=list(CASES))
    args = parser.parse_args(argv)
    if not args.serial.startswith('emulator-'):
        print('emulator only', file=sys.stderr)
        return 2
    ACCEPT['via'] = args.accept
    load_files(args.files_dir)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dev = Device(args.serial)
    failed = 0
    try:
        for name in args.cases:
            try:
                why = CASES[name](dev)
            except Exception as e:  # noqa: BLE001 — a case that breaks is a failure
                why = f'{type(e).__name__}: {e}'
                # What the screen showed, for the report.
                shot = subprocess.run(dev.adb + ['exec-out', 'screencap', '-p'], capture_output=True).stdout
                pathlib.Path(f'/tmp/xlit-e2e-{name}.png').write_bytes(shot)
            failed += bool(why)
            print(f'FAIL {name}: {why}' if why else f'ok {name}', flush=True)
    finally:
        dev.teardown()
        server.shutdown()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

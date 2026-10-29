#!/usr/bin/env python3
"""End-to-end check of desktop page translation (Linux, Mac).

    translate_e2e.py APP MODELS_DIR [--screenshot PNG]

Launches APP (on Linux the tarball's folder) on a fresh profile that always
translates Hindi into English, with the translation models from MODELS_DIR
(linux/fetch_translate_models.sh) in Tark's captions models folder, opens a
local Hindi page and checks, through DevTools:
  page_translated  The page's Hindi paragraphs turn into English, on the
                   computer (no translate server is reachable: none is set).
  js_text          A paragraph the page adds 3 s later is translated too.
  link_kept        The link inside a translated sentence is still a link.
With --screenshot, the whole screen (the translate bar under the toolbar
is browser UI, not page) is saved after the checks (ImageMagick's import).
Prints "ok …" / "FAIL …"; exits 1 if any check fails.
"""

import argparse
import http.server
import os
import pathlib
import re
import socketserver
import sys
import tempfile
import threading
import time
import urllib.request
import json
import subprocess

import adblock_e2e as e2e

PORT = 8767

PAGE = """<!doctype html><html lang="hi"><meta charset="utf-8"><title>समाचार</title>
<body><h1 id="h">आज की मुख्य खबरें</h1>
<p id="p1">भारत एक विशाल देश है। यहाँ बहुत सी भाषाएँ बोली जाती हैं।</p>
<p id="p2">आज मौसम बहुत अच्छा है और लोग बाज़ार जा रहे हैं।</p>
<p id="p3">पूरी <a id="a" href="#r">रिपोर्ट</a> यहाँ पढ़ें।</p>
<div id="feed"></div>
<script>setTimeout(() => { const p = document.createElement('p'); p.id = 'late';
  p.textContent = 'नई खबर: किसानों के लिए नई योजना शुरू हुई है।';
  document.querySelector('#feed').appendChild(p); }, 3000);</script>
</body></html>"""

# Always translate Hindi into English, offering on.
PREFS = {'translate': {'enabled': True}, 'translate_allowlists': {'hi': 'en'},
         'intl': {'accept_languages': 'en-US,en'}}

DEVANAGARI = re.compile('[ऀ-ॿ]')
LATIN_WORD = re.compile('[A-Za-z]{3,}')


def english(text):
    return bool(text) and not DEVANAGARI.search(text) and bool(LATIN_WORD.search(text))


def serve():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = socketserver.TCPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def page_ws(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        with urllib.request.urlopen(f'http://127.0.0.1:{e2e.DEVTOOLS_PORT}/json', timeout=5) as r:
            tab = next((t for t in json.load(r) if t.get('url', '').startswith(url)), None)
        if tab:
            return tab['webSocketDebuggerUrl']
        time.sleep(1)
    return None


def wait_text(ws, element_id, timeout):
    end = time.time() + timeout
    text = None
    while time.time() < end:
        text = e2e.evaluate(ws, f"(e => e ? e.textContent : null)(document.getElementById('{element_id}'))")
        if english(text):
            return True, text
        time.sleep(1)
    return False, text


def report(ok, name, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f': {detail}' if detail else ''))
    return 0 if ok else 1


def models_home(models):
    """An XDG config home whose Tark (and Chromium-named) user data folders
    hold the models where Tark looks for them: <user data>/Captions/models."""
    home = pathlib.Path(tempfile.mkdtemp(prefix='tark-translate-e2e-'))
    for name in ('tark', 'Tark', 'chromium'):
        captions = home / name / 'Captions'
        captions.mkdir(parents=True, exist_ok=True)  # tark = Tark on a Mac's disk
        if not (captions / 'models').exists():
            (captions / 'models').symlink_to(pathlib.Path(models).resolve())
    return home


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('app')
    ap.add_argument('models')
    ap.add_argument('--screenshot')
    args = ap.parse_args(argv)
    os.environ['XDG_CONFIG_HOME'] = str(models_home(args.models))
    server = serve()
    browser = e2e.Browser(args.app, prefs=PREFS)
    failed = 0
    try:
        if not browser.wait_ready():
            return report(False, 'started', 'Tark never started')
        url = f'http://127.0.0.1:{PORT}/'
        browser.open(url)
        ws = page_ws(url)
        if not ws:
            return report(False, 'page_translated', 'the page never opened')
        # The first sentences load the model (up to a minute on a cold disk).
        ok1, t1 = wait_text(ws, 'p1', 120)
        ok2, t2 = wait_text(ws, 'p2', 30)
        failed += report(ok1 and ok2, 'page_translated', f'{t1!r} / {t2!r}')
        ok, late = wait_text(ws, 'late', 20)
        failed += report(ok, 'js_text', repr(late))
        ok3, t3 = wait_text(ws, 'p3', 20)
        has_link = e2e.evaluate(ws, "!!document.querySelector('#p3 a#a')")
        failed += report(ok3 and has_link, 'link_kept', f'{t3!r}, link={has_link}')
        if args.screenshot:
            subprocess.run(['import', '-window', 'root', args.screenshot], check=False)
    finally:
        browser.close()
        server.shutdown()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

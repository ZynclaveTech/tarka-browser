#!/usr/bin/env python3
# Copyright 2026 The Tark Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Check Tark's own pages against the Paper page pattern (M3d).

    python3 utils/page_audit.py PORT [PAGE ...]

PORT is the --remote-debugging-port of a running dev build. Each page in
PAGES (or the ones named) is opened in a background tab; FACTS_JS reads the
facts below from it, through open shadow roots; problems() compares them
with the pattern in docs/superpowers/specs/2026-10-18-tark-own-pages-design.md.
Prints PAGE<TAB>problem lines; exit status 1 if there are any.

Facts: dark, label, label_transform, label_color, sentence, sentence_lines,
row_shadows, sidebar_selected_border ("2px rgb(...)" or None), actions (the
accessible names of the first row's [data-tark-action] elements), danger_row
({"text", "buttons"} for a [data-tark-row][data-danger] row, or None).
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brand_audit import _Socket, _json  # noqa: E402

PAGES = {
    'downloads': 'chrome://downloads/',
    'extensions': 'chrome://extensions/',
    'history': 'chrome://history/',
    'bookmarks': 'chrome://bookmarks/',
    'passwords': 'chrome://password-manager/passwords',
    'version': 'chrome://version/',
    'urls': 'chrome://chrome-urls/',
}

# Spec §6 palette: (light, dark).
INDIGO = ('rgb(67, 56, 202)', 'rgb(143, 136, 255)')
CORAL = ('rgb(230, 62, 92)', 'rgb(255, 107, 133)')

SENTENCES = {
    'downloads': r'^([1-9]\d* files? today, saved to your .+ folder|Saved to your .+ folder)$',
    'extensions': r'^\d+ extensions? on\.',
    'history': r'^Kept on this Mac only\. \d+ pages? today\.$',
    'bookmarks': r'^\d+ bookmarks? in \d+ folders?, kept on this Mac\.$',
    'passwords': r'^\d+ passwords? saved on this Mac, locked with your Mac login\.$',
    'version': r'^Tark [\d.]+, built on Chromium for this Mac\.$',
}


def problems(page, facts):
    """What is wrong with `facts` read from `page`, as short sentences."""
    found = []
    dark = 1 if facts.get('dark') else 0
    if facts.get('label_transform') != 'uppercase':
        found.append('header label is not uppercase')
    if facts.get('label_color') != INDIGO[dark]:
        found.append('header label is %s, not indigo %s' % (facts.get('label_color'), INDIGO[dark]))
    sentence = facts.get('sentence')
    if not sentence:
        found.append('no header sentence')
    elif page in SENTENCES and not re.search(SENTENCES[page], sentence):
        found.append('sentence %r does not match %s' % (sentence, SENTENCES[page]))
    if sentence and facts.get('sentence_lines', 1) != 1:
        found.append('sentence takes %s lines' % facts.get('sentence_lines'))
    if facts.get('header_overflow'):
        found.append('the header is wider than the window (search pushed out)')
    if facts.get('row_shadows'):
        found.append('%d elements with a box-shadow' % facts['row_shadows'])
    if page == 'version' and facts.get('rows', 0) < 3:
        found.append('version page has %s label/value rows' % facts.get('rows', 0))
    danger = facts.get('danger_row')
    if danger is not None and (not danger.get('text') or not danger.get('buttons')):
        found.append('a dangerous download lost its warning or its actions')
    border = facts.get('sidebar_selected_border')
    if border is not None and border != '2px ' + CORAL[dark]:
        found.append('selected sidebar row has %r, not a 2px coral line' % border)
    return found


FACTS_JS = r"""(() => {
  const all = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const visible = (el) => el && el.getClientRects().length > 0;
  const toolbar = all.find((e) => e.tagName === 'CR-TOOLBAR' && visible(e));
  const scope = toolbar ? toolbar.shadowRoot : document;
  const plain = (selector) => all.find((e) => e.matches && e.matches(selector));
  const label = toolbar ? scope.querySelector('h1')
                        : plain('.tark-page-header h1');
  const sentenceEl = toolbar ? scope.querySelector('#pageSentence')
                             : plain('#pageSentence');
  const sentence = sentenceEl && visible(sentenceEl) ?
      sentenceEl.textContent.trim() || null : null;
  let lines = 0;
  if (sentence) {
    const style = getComputedStyle(sentenceEl);
    const lineHeight = parseFloat(style.lineHeight) || 1.2 * parseFloat(style.fontSize);
    lines = Math.round(sentenceEl.getBoundingClientRect().height / lineHeight);
  }
  const inToolbar = (el) => toolbar && (toolbar.contains(el) ||
      toolbar.shadowRoot.contains(el));
  // Rows and their parts only: toasts, menus, dialogs and the scroll-edge
  // shadow are page furniture, not rows.
  const furniture = (e) => e.matches && e.matches(
      'cr-toast, cr-toast *, cr-action-menu, dialog, .cr-scrollable-top-shadow');
  const shadows = all.filter((e) => !inToolbar(e) && !furniture(e) &&
      visible(e) && getComputedStyle(e).boxShadow !== 'none').length;
  const selected = all.find((e) => visible(e) && e.matches &&
      e.matches('cr-menu-selector .selected, cr-menu-selector [selected], ' +
                '.cr-nav-menu-item.selected, a.cr-nav-menu-item[aria-current="page"], ' +
                '[data-tark-nav][aria-current="page"]'));
  const border = selected ? (() => {
    const s = getComputedStyle(selected);
    return s.borderLeftWidth + ' ' + s.borderLeftColor;
  })() : null;
  const name = (el) => (el.getAttribute('aria-label') || el.textContent || '').trim();
  const rows = all.filter((e) => e.hasAttribute && e.hasAttribute('data-tark-row') && visible(e));
  const firstRow = rows.find((r) => !r.hasAttribute('data-danger'));
  const actions = firstRow ? [...firstRow.querySelectorAll('[data-tark-action]')]
      .concat(firstRow.shadowRoot ?
          [...firstRow.shadowRoot.querySelectorAll('[data-tark-action]')] : [])
      .map(name) : [];
  const danger = rows.find((r) => r.hasAttribute('data-danger'));
  return JSON.stringify({
    dark: matchMedia('(prefers-color-scheme: dark)').matches,
    label: label ? label.textContent.trim() : null,
    label_transform: label ? getComputedStyle(label).textTransform : null,
    label_color: label ? getComputedStyle(label).color : null,
    sentence: sentence,
    sentence_lines: lines,
    row_shadows: shadows,
    sidebar_selected_border: border,
    header_overflow: toolbar ? toolbar.scrollWidth > toolbar.clientWidth + 1 :
                               false,
    actions: actions,
    rows: rows.length,
    danger_row: danger ? {text: danger.textContent.trim().slice(0, 200),
        buttons: [...danger.querySelectorAll('[data-tark-action]')].map(name)} : null,
  });
})()"""


def page_facts(port, url, wait=3.0):
    browser = _Socket(_json(port, '/json/version')['webSocketDebuggerUrl'])
    target = browser.call('Target.createTarget', {'url': url, 'background': True})['targetId']
    time.sleep(wait)
    page = next(t for t in _json(port, '/json') if t['id'] == target)
    tab = _Socket(page['webSocketDebuggerUrl'])
    result = tab.call('Runtime.evaluate', {'expression': FACTS_JS, 'returnByValue': True})
    tab.close()
    browser.call('Target.closeTarget', {'targetId': target})
    browser.close()
    return json.loads(result.get('result', {}).get('value') or '{}')


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: page_audit.py PORT [PAGE ...]')
    port, names = sys.argv[1], sys.argv[2:] or list(PAGES)
    total = 0
    for name in names:
        for problem in problems(name, page_facts(port, PAGES[name])):
            print(f'{name}\t{problem}')
            total += 1
    print(f'{total} problem(s)', file=sys.stderr)
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()

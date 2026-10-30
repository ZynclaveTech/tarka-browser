// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Tark's stand-in for element.js: google.translate.TranslateService, which
// Chromium's translate.js (cr.googleTranslate) drives. Nothing is fetched.
// The isolated world has no Mojo, so text leaves through a queue that
// TranslateAgent (renderer C++) drains:
//   tarkTranslate.takeBatch()        -> {id: number, texts: string[]} | null
//   tarkTranslate.onResult(id, results)  results: (string|null)[]
// A null result keeps the original. translatePage's progress counts answered
// batches and finishes when the page's queue is drained; text the page adds
// or changes later is still translated, without reporting again.
// The page is walked in slices (CHUNK_NODES items or CHUNK_MS, then a
// setTimeout) so a long page never holds the main thread; visible text goes
// ahead of the rest from the first slice on.

var tarkTranslate = (function() {
  'use strict';
  const B = typeof tarkBatcher !== 'undefined' ? tarkBatcher :
                                                 require('./batcher.js');
  const CHUNK_NODES = 500;
  const CHUNK_MS = 16;
  const MAX_CHARS = 1000;
  const MAX_ITEMS = 16;
  // A text longer than this stays as it is and is never sent (a whole .txt
  // file, a huge <pre>-like block): the browser bounds a batch at 64 KiB.
  const MAX_ITEM_CHARS = 4000;

  function create(win) {
    const doc = win.document;
    let batcher = null;
    let active = false;
    let generation = 0;
    let collecting = false;
    let dirty = false;  // a scroll since the queue was ordered
    // Unsent items: visible ones first, then the rest; each read from head.
    let front = [], frontHead = 0, back = [], backHead = 0;
    let queuedCount = 0, queuedChars = 0;
    let latest = new Map();  // Text -> its newest queued item
    const inflight = new Map();
    let nextId = 1;
    let answered = 0;
    let reported = false;
    let onProgress = null;
    let sourceLang = '';
    const stats = {chunks: 0, examined: 0};

    const viewport = () => ({top: 0, bottom: win.innerHeight || 0});
    const onScroll = () => { dirty = true; };
    const now = () => (win.performance ? win.performance.now() : Date.now());

    function push(item, isVisible) {
      if (item.text.length > MAX_ITEM_CHARS) return;  // left original
      latest.set(item.node, item);
      (isVisible ? front : back).push(item);
      queuedCount++;
      queuedChars += item.text.length;
    }

    function enqueue(items) {
      const vp = viewport();
      for (const item of items) push(item, B.visible(item.node, vp));
    }

    function live(item) {
      return latest.get(item.node) === item && item.node.isConnected &&
             item.node.nodeValue === item.original;
    }

    // Only the not-yet-sent items are re-ordered after a scroll.
    function reorder() {
      const rest = front.slice(frontHead).concat(back.slice(backHead));
      front = []; back = []; frontHead = 0; backHead = 0;
      const vp = viewport();
      for (const item of rest) {
        if (live(item)) {
          (B.visible(item.node, vp) ? front : back).push(item);
        } else {
          queuedCount--;
          queuedChars -= item.text.length;
        }
      }
      dirty = false;
    }

    function finishIfDrained() {
      if (reported || collecting || queuedCount || inflight.size) return false;
      reported = true;
      if (onProgress) onProgress(100, true, 0);
      return true;
    }

    function collectSlices(gen, it) {
      const vp = viewport();
      const start = now();
      let n = 0;
      stats.chunks++;
      for (;;) {
        const step = it.next();
        if (step.done) {
          collecting = false;
          finishIfDrained();
          return;
        }
        // The observer may have translated this node already.
        if (!batcher.owned(step.value.node)) {
          push(step.value, B.visible(step.value.node, vp));
        }
        if (++n >= CHUNK_NODES || now() - start >= CHUNK_MS) break;
      }
      win.setTimeout(() => {
        if (gen === generation && active) collectSlices(gen, it);
      }, 0);
    }

    function translatePage(src, tgt, progress) {
      if (active) restore();
      active = true;
      reported = false;
      answered = 0;
      onProgress = progress;
      sourceLang = src;
      batcher = B.create();
      const root = doc.body || doc.documentElement;
      batcher.observe(root, enqueue);
      win.addEventListener('scroll', onScroll, {passive: true});
      collecting = true;
      collectSlices(++generation, batcher.walk(root));
    }

    function takeBatch() {
      if (!active) return null;
      if (dirty) reorder();
      const texts = [], items = [];
      let chars = 0;
      for (;;) {
        let item;
        if (frontHead < front.length) item = front[frontHead];
        else if (backHead < back.length) item = back[backHead];
        else break;
        stats.examined++;
        if (live(item)) {
          if (items.length && (items.length >= MAX_ITEMS ||
                               chars + item.text.length > MAX_CHARS)) {
            break;
          }
          items.push(item);
          texts.push(item.text);
          chars += item.text.length;
          latest.delete(item.node);
        }
        if (frontHead < front.length) frontHead++;
        else backHead++;
        queuedCount--;
        queuedChars -= item.text.length;
      }
      if (frontHead === front.length) { front = []; frontHead = 0; }
      if (backHead === back.length) { back = []; backHead = 0; }
      if (!items.length) {
        finishIfDrained();
        return null;
      }
      const id = nextId++;
      inflight.set(id, items);
      return {id: id, texts: texts};
    }

    function onResult(id, results) {
      const batch = inflight.get(id);
      if (!active || !batch) return;
      inflight.delete(id);
      batcher.apply(batch, results);
      answered++;
      if (reported || finishIfDrained()) return;
      const left = inflight.size + B.estimate(queuedCount, queuedChars);
      if (onProgress) {
        onProgress(Math.floor(100 * answered / (answered + Math.max(left, 1))),
                   false, 0);
      }
    }

    function restore() {
      active = false;
      collecting = false;
      generation++;
      win.removeEventListener('scroll', onScroll);
      if (batcher) batcher.revert();
      front = []; back = []; frontHead = 0; backHead = 0;
      queuedCount = 0; queuedChars = 0;
      latest = new Map();
      inflight.clear();
    }

    function getDetectedLanguage() {
      if (sourceLang && sourceLang !== 'auto') return sourceLang;
      const lang = (doc.documentElement.getAttribute('lang') || '').trim();
      return lang ? lang.split(/[-_]/)[0].toLowerCase() : 'und';
    }

    return {
      service: {
        isAvailable: () => true,
        translatePage,
        restore,
        getDetectedLanguage,
      },
      takeBatch,
      onResult,
      stats,
      isCollecting: () => collecting,
    };
  }

  return {create};
})();

if (typeof module === 'object' && module.exports) {
  module.exports = tarkTranslate;
} else {
  // The translate isolated world: one translator for the frame.
  (function() {
    const t = tarkTranslate.create(window);
    tarkTranslate.takeBatch = t.takeBatch;
    tarkTranslate.onResult = t.onResult;
    var g = (window.google = window.google || {});
    g.translate = g.translate || {};
    g.translate.TranslateService = function(opts) { return t.service; };
    cr.googleTranslate.onTranslateElementLoad();
  })();
}

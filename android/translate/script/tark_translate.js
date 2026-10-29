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

var tarkTranslate = (function() {
  'use strict';
  const B = typeof tarkBatcher !== 'undefined' ? tarkBatcher :
                                                 require('./batcher.js');

  function create(win) {
    const doc = win.document;
    let batcher = null;
    let active = false;
    let queue = [];
    let dirty = false;  // a scroll since the queue was ordered
    const inflight = new Map();
    let nextId = 1;
    let answered = 0;
    let reported = false;
    let onProgress = null;
    let sourceLang = '';

    const viewport = () => ({top: 0, bottom: win.innerHeight || 0});
    const onScroll = () => { dirty = true; };

    function enqueue(items) {
      const nodes = new Set(items.map(i => i.node));
      queue = queue.filter(i => !nodes.has(i.node)).concat(items);
      dirty = true;
    }

    function finishIfDrained() {
      if (reported || queue.length || inflight.size) return false;
      reported = true;
      if (onProgress) onProgress(100, true, 0);
      return true;
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
      queue = batcher.collect(root, viewport());
      dirty = false;
      batcher.observe(root, enqueue);
      win.addEventListener('scroll', onScroll, {passive: true});
      finishIfDrained();
    }

    function takeBatch() {
      if (!active) return null;
      // Drop items the page changed or removed since they were queued.
      queue = queue.filter(i => i.node.isConnected &&
                                i.node.nodeValue === i.original);
      if (dirty) {
        queue = B.order(queue, viewport());
        dirty = false;
      }
      if (!queue.length) {
        finishIfDrained();
        return null;
      }
      const batch = B.batches(queue)[0];
      queue = queue.slice(batch.length);
      const id = nextId++;
      inflight.set(id, batch);
      return {id: id, texts: batch.map(i => i.text)};
    }

    function onResult(id, results) {
      const batch = inflight.get(id);
      if (!active || !batch) return;
      inflight.delete(id);
      batcher.apply(batch, results);
      answered++;
      if (reported || finishIfDrained()) return;
      const left = inflight.size + B.batches(queue).length;
      if (onProgress) {
        onProgress(Math.floor(100 * answered / (answered + left)), false, 0);
      }
    }

    function restore() {
      active = false;
      win.removeEventListener('scroll', onScroll);
      if (batcher) batcher.revert();
      queue = [];
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

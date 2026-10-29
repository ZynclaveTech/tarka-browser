// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Tark page translation: finds the page's text, cuts it into batches, writes
// translations back and puts the originals back. Runs in the translate
// isolated world (bundled ahead of tark_translate.js) and under node's tests.
// Each text node is sent as is (its leading and trailing whitespace kept
// aside); a sentence split across inline elements goes as separate pieces.

var tarkBatcher = (function() {
  'use strict';

  const SKIP_TAGS = new Set([
    'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'CODE', 'PRE', 'KBD', 'SAMP',
    'VAR', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'SVG', 'MATH', 'IFRAME',
    'OBJECT',
  ]);

  function skipsElement(el) {
    if (SKIP_TAGS.has(el.tagName.toUpperCase())) return true;
    if (el.getAttribute('translate') === 'no') return true;
    if (el.classList && el.classList.contains('notranslate')) return true;
    const editable = el.getAttribute('contenteditable');
    if (editable !== null && editable !== 'false') return true;
    return false;
  }

  function insideSkipped(node) {
    for (let el = node.nodeType === 1 ? node : node.parentElement; el;
         el = el.parentElement) {
      if (skipsElement(el)) return true;
    }
    return false;
  }

  function visible(node, viewport) {
    const el = node.parentElement;
    if (!el || !viewport) return false;
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return false;
    return r.bottom > viewport.top && r.top < viewport.bottom;
  }

  function itemFor(node) {
    const value = node.nodeValue;
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(value);
    if (!m[2]) return null;
    return {node: node, text: m[2], lead: m[1], trail: m[3], original: value};
  }

  // Visible items first, then the rest, each in document order.
  function order(items, viewport) {
    const first = [], rest = [];
    for (const item of items) {
      (visible(item.node, viewport) ? first : rest).push(item);
    }
    return first.concat(rest);
  }

  function batches(items, maxChars = 1000, maxItems = 16) {
    const out = [];
    let cur = [], chars = 0;
    for (const item of items) {
      if (cur.length &&
          (cur.length >= maxItems || chars + item.text.length > maxChars)) {
        out.push(cur);
        cur = [];
        chars = 0;
      }
      cur.push(item);
      chars += item.text.length;
    }
    if (cur.length) out.push(cur);
    return out;
  }

  function create() {
    const originals = new Map();  // Text -> the page's own text
    const written = new Map();    // Text -> what Tark last wrote there
    let observer = null;

    function collect(root, viewport) {
      if (!root || (root.nodeType !== 9 && insideSkipped(root))) return [];
      const items = [];
      if (root.nodeType === 3) {
        const item = itemFor(root);
        if (item) items.push(item);
        return order(items, viewport);
      }
      const doc = root.ownerDocument || root;
      const NF = doc.defaultView.NodeFilter;
      const walker = doc.createTreeWalker(
          root, NF.SHOW_ELEMENT | NF.SHOW_TEXT, {
            acceptNode(n) {
              if (n.nodeType === 1) {
                return skipsElement(n) ? NF.FILTER_REJECT : NF.FILTER_SKIP;
              }
              return NF.FILTER_ACCEPT;
            },
          });
      let n;
      while ((n = walker.nextNode())) {
        const item = itemFor(n);
        if (item) items.push(item);
      }
      return order(items, viewport);
    }

    // results[i] is item i's translation; null (or anything not a string)
    // keeps the original. A node the page changed since it was collected is
    // left alone: the observer queues its new text.
    function apply(items, results) {
      items.forEach((item, i) => {
        const r = results ? results[i] : null;
        if (typeof r !== 'string') return;
        if (item.node.nodeValue !== item.original) return;
        if (!originals.has(item.node)) originals.set(item.node, item.original);
        const value = item.lead + r + item.trail;
        written.set(item.node, value);
        item.node.nodeValue = value;
      });
    }

    function revert() {
      disconnect();
      for (const [node, value] of originals) {
        if (written.get(node) === node.nodeValue) node.nodeValue = value;
      }
      originals.clear();
      written.clear();
    }

    // onItems(items) gets the text the page added or changed. Tark's own
    // writes are not reported, so a page that rewrites its text can't loop.
    function observe(root, onItems) {
      disconnect();
      const MO = (root.ownerDocument || root).defaultView.MutationObserver;
      observer = new MO(records => {
        const items = [];
        const seen = new Set();
        const add = list => {
          for (const it of list) {
            if (!seen.has(it.node)) {
              seen.add(it.node);
              items.push(it);
            }
          }
        };
        for (const rec of records) {
          if (rec.type === 'characterData') {
            const node = rec.target;
            if (written.get(node) === node.nodeValue) continue;
            written.delete(node);
            if (originals.has(node)) originals.delete(node);
            if (!node.isConnected || insideSkipped(node)) continue;
            add(collect(node));
          } else {
            for (const added of rec.addedNodes) {
              if (!added.isConnected) continue;
              if (added.nodeType === 3 && written.get(added) === added.nodeValue) {
                continue;
              }
              if (added.nodeType === 3 && insideSkipped(added)) continue;
              if (added.nodeType === 1 || added.nodeType === 3) {
                add(collect(added));
              }
            }
          }
        }
        if (items.length) onItems(items);
      });
      observer.observe(root, {characterData: true, childList: true, subtree: true});
    }

    function disconnect() {
      if (observer) {
        observer.disconnect();
        observer = null;
      }
    }

    return {collect, batches, apply, revert, observe, disconnect, order};
  }

  return {create, batches, order};
})();

if (typeof module === 'object' && module.exports) {
  module.exports = tarkBatcher;
}

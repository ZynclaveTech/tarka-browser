// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Tark page translation: finds the page's text, cuts it into batches, writes
// translations back and puts the originals back. Runs in the translate
// isolated world (bundled ahead of tark_translate.js) and under node's tests.
// Each text node is sent as is (its leading and trailing whitespace kept
// aside); a sentence split across inline elements goes as separate pieces.
// Open shadow roots are walked and watched too.

var tarkBatcher = (function() {
  'use strict';

  const SKIP_TAGS = new Set([
    'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'CODE', 'PRE', 'KBD', 'SAMP',
    'VAR', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'SVG', 'MATH', 'IFRAME',
    'OBJECT',
  ]);
  // A node the page keeps rewriting is translated again at most this often.
  const MAX_RETRANSLATIONS = 3;

  // Never translated, whatever is inside.
  function hardSkip(el) {
    if (SKIP_TAGS.has(el.tagName.toUpperCase())) return true;
    const editable = el.getAttribute('contenteditable');
    return editable !== null && editable.toLowerCase() !== 'false';
  }

  // 'no', 'yes' or null: the element's own translate choice.
  function translateChoice(el) {
    const t = (el.getAttribute('translate') || '').trim().toLowerCase();
    if (t === 'no') return 'no';
    if (t === 'yes' || t === '') {
      if (el.hasAttribute('translate')) return 'yes';
    }
    if (el.classList && el.classList.contains('notranslate')) return 'no';
    return null;
  }

  function parentOf(node) {
    const p = node.parentNode;
    if (p && p.nodeType === 11 && p.host) return p.host;  // shadow root
    return p && p.nodeType === 1 ? p : null;
  }

  function designMode(node) {
    const doc = node.ownerDocument || node;
    return (doc.designMode || '').toLowerCase() === 'on';
  }

  function insideSkipped(node) {
    if (designMode(node)) return true;
    let decided = false;
    for (let el = node.nodeType === 1 ? node : parentOf(node); el;
         el = parentOf(el)) {
      if (hardSkip(el)) return true;
      if (!decided) {
        const c = translateChoice(el);
        if (c === 'no') return true;
        if (c === 'yes') decided = true;
      }
    }
    return false;
  }

  function visible(node, viewport) {
    const el = parentOf(node);
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

  // How many batches `items` makes, without making them.
  function estimate(count, chars, maxChars = 1000, maxItems = 16) {
    if (!count) return 0;
    return Math.max(Math.ceil(count / maxItems), Math.ceil(chars / maxChars));
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
    const cache = new Map();      // source text -> its translation
    const rewrites = new WeakMap();  // Text or parent -> model re-translations
    const cacheWrites = new WeakMap();  // Text or parent -> cache rewrites
    let observer = null;

    // Yields the text items under root in document order (open shadow
    // roots after their host's light children).
    function* walk(root) {
      if (!root || designMode(root)) return;
      if (root.nodeType === 3) {
        if (!insideSkipped(root)) {
          const item = itemFor(root);
          if (item) yield item;
        }
        return;
      }
      if (root.nodeType === 1 && insideSkipped(root)) return;
      // [node, translate=no inherited]
      const stack = [[root, false]];
      while (stack.length) {
        const [node, no] = stack.pop();
        if (node.nodeType === 3) {
          if (!no) {
            const item = itemFor(node);
            if (item) yield item;
          }
          continue;
        }
        let off = no;
        if (node.nodeType === 1) {
          if (node !== root && hardSkip(node)) continue;
          const c = translateChoice(node);
          if (c) off = c === 'no';
          if (node.shadowRoot) {
            watch(node.shadowRoot);
            stack.push([node.shadowRoot, off]);
          }
        }
        const kids = node.childNodes;
        for (let i = kids.length - 1; i >= 0; i--) {
          const k = kids[i];
          if (k.nodeType === 1 || k.nodeType === 3) stack.push([k, off]);
        }
      }
    }

    function collect(root, viewport) {
      return order([...walk(root)], viewport);
    }

    function remember(item, r) {
      if (!originals.has(item.node)) originals.set(item.node, item.original);
      const value = item.lead + r + item.trail;
      written.set(item.node, value);
      item.node.nodeValue = value;
    }

    // results[i] is item i's translation; null (or anything not a string)
    // keeps the original. A node the page changed since it was collected is
    // left alone: the observer queues its new text.
    function apply(items, results) {
      items.forEach((item, i) => {
        const r = results ? results[i] : null;
        if (typeof r !== 'string') return;
        cache.set(item.text, r);
        if (item.node.nodeValue !== item.original) return;
        remember(item, r);
      });
    }

    function revert() {
      disconnect();
      for (const [node, value] of originals) {
        if (written.get(node) === node.nodeValue) node.nodeValue = value;
      }
      originals.clear();
      written.clear();
      cache.clear();
    }

    // Text the page added or changed: written from the cache when Tark has
    // translated it before (no model call), otherwise handed to onItems.
    // Tark's own writes are not reported, and a node (or, for text nodes the
    // page swaps in, their parent) is re-translated at most
    // MAX_RETRANSLATIONS times, then left as the page wrote it.
    // Model calls and cache rewrites are capped separately: a page that
    // keeps putting its original back stops after MAX_RETRANSLATIONS cache
    // writes without using up its model re-translations, and vice versa.
    function changed(items, key, onItems) {
      if (!items.length) return;
      const hits = [], fresh = [];
      for (const item of items) {
        (cache.has(item.text) ? hits : fresh).push(item);
      }
      if (hits.length) {
        const n = cacheWrites.get(key) || 0;
        if (n < MAX_RETRANSLATIONS) {
          cacheWrites.set(key, n + 1);
          for (const item of hits) remember(item, cache.get(item.text));
        }
      }
      if (fresh.length) {
        const n = rewrites.get(key) || 0;
        if (n < MAX_RETRANSLATIONS) {
          rewrites.set(key, n + 1);
          onItems(fresh);
        }
      }
    }

    // True when the node shows what Tark wrote there.
    function owned(node) {
      return written.has(node) && written.get(node) === node.nodeValue;
    }

    function observe(root, onItems) {
      disconnect();
      const MO = (root.ownerDocument || root).defaultView.MutationObserver;
      observer = new MO(records => {
        // One look per node: several records for a node read its value now.
        const seen = new Set();
        for (const rec of records) {
          if (rec.type === 'characterData') {
            const node = rec.target;
            if (seen.has(node)) continue;
            seen.add(node);
            if (written.get(node) === node.nodeValue) continue;
            written.delete(node);
            originals.delete(node);
            if (!node.isConnected) continue;
            changed([...walk(node)], node, onItems);
          } else {
            for (const added of rec.addedNodes) {
              if (!added.isConnected || seen.has(added)) continue;
              seen.add(added);
              if (added.nodeType === 3) {
                if (written.get(added) === added.nodeValue) continue;
                changed([...walk(added)], parentOf(added) || added, onItems);
              } else if (added.nodeType === 1) {
                changed([...walk(added)], added, onItems);
              }
            }
          }
        }
      });
      watch(root);
    }

    function watch(root) {
      if (observer) {
        observer.observe(root, {characterData: true, childList: true, subtree: true});
      }
    }

    function disconnect() {
      if (observer) {
        observer.disconnect();
        observer = null;
      }
    }

    return {walk, owned, collect, apply, revert, observe, disconnect};
  }

  return {create, batches, order, estimate, visible, MAX_RETRANSLATIONS};
})();

if (typeof module === 'object' && module.exports) {
  module.exports = tarkBatcher;
}

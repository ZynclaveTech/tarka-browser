// node --test android/translate/script/test  (jsdom from
// android/translate/script/package.json: npm install there first)
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {JSDOM} = require('jsdom');
const B = require('../batcher.js');
const T = require('../tark_translate.js');

const tick = () => new Promise(r => setTimeout(r, 0));

function dom(body) {
  const d = new JSDOM(`<!doctype html><html lang="hi"><body>${body}</body></html>`,
                      {pretendToBeVisual: true});
  return d.window;
}

// jsdom has no layout: an element with data-top is placed there.
function place(win) {
  win.Element.prototype.getBoundingClientRect = function() {
    const top = this.dataset && this.dataset.top;
    if (top === undefined) return {top: 0, bottom: 0, width: 0, height: 0};
    const t = Number(top);
    return {top: t, bottom: t + 20, width: 100, height: 20};
  };
}

const texts = items => items.map(i => i.text);

test('skipsScriptStyleCodePreInputsContenteditable', () => {
  const win = dom(`<p>one</p><script>x</script><style>y</style><code>c</code>
    <pre>p</pre><textarea>t</textarea><select><option>o</option></select>
    <div contenteditable="true">e<b>f</b></div><div contenteditable="false">two</div>
    <noscript>n</noscript>`);
  assert.deepEqual(texts(B.create().collect(win.document.body)), ['one', 'two']);
});

test('respectsTranslateNoAndNotranslate', () => {
  const win = dom(`<p translate="no">a<b>b</b></p><p class="x notranslate">c</p>
    <p translate="yes">d</p><span>e</span>`);
  assert.deepEqual(texts(B.create().collect(win.document.body)), ['d', 'e']);
});

test('visibleFirstThenDocumentOrder', () => {
  const win = dom(`<p data-top="-500">a</p><p data-top="900">b</p>
    <p data-top="100">c</p><p>d</p><p data-top="300">e</p>`);
  place(win);
  const items = B.create().collect(win.document.body, {top: 0, bottom: 800});
  assert.deepEqual(texts(items), ['c', 'e', 'a', 'b', 'd']);
});

test('batchLimits', () => {
  const items = Array.from({length: 40}, (_, i) => ({text: 'x'.repeat(i < 20 ? 10 : 300)}));
  const out = B.batches(items);
  for (const b of out) {
    assert.ok(b.length <= 16);
    assert.ok(b.reduce((n, i) => n + i.text.length, 0) <= 1000);
  }
  assert.equal(out.flat().length, 40);
  assert.equal(out[0].length, 16);
  // One text over the limit goes alone.
  assert.deepEqual(B.batches([{text: 'a'}, {text: 'y'.repeat(1500)}, {text: 'b'}])
                       .map(b => b.length), [1, 1, 1]);
});

test('nullResultKeepsOriginal', () => {
  const win = dom('<p> one </p><p>two</p><p>three</p>');
  const b = B.create();
  const items = b.collect(win.document.body);
  b.apply(items, ['ek', null, undefined]);
  const ps = [...win.document.querySelectorAll('p')].map(p => p.textContent);
  assert.deepEqual(ps, [' ek ', 'two', 'three']);
});

test('revertRestoresExactText', () => {
  const html = '<p>  नमस्ते\n दुनिया  </p><div> a <i>b</i>\tc </div>';
  const win = dom(html);
  const b = B.create();
  const before = win.document.body.innerHTML;
  const items = b.collect(win.document.body);
  b.apply(items, items.map(i => 'T(' + i.text + ')'));
  assert.notEqual(win.document.body.innerHTML, before);
  assert.match(win.document.querySelector('p').textContent, /^ {2}T\(/);
  b.revert();
  assert.equal(win.document.body.innerHTML, before);
});

// The queue TranslateAgent drains.
function translator(body) {
  const win = dom(body);
  const t = T.create(win);
  const progress = [];
  t.service.translatePage('hi', 'en', (p, finished, error) => progress.push([p, finished, error]));
  return {win, t, progress};
}

function drain(t, f = s => s.toUpperCase()) {
  let batch, n = 0;
  while ((batch = t.takeBatch())) {
    t.onResult(batch.id, batch.texts.map(f));
    n++;
  }
  return n;
}

test('ownWritesNotResent', async () => {
  const {win, t, progress} = translator('<p>one</p><p>two</p>');
  assert.equal(drain(t), 1);
  assert.equal(win.document.body.textContent, 'ONETWO');
  await tick();  // the MutationObserver sees Tark's writes
  assert.equal(t.takeBatch(), null);
  assert.deepEqual(progress.at(-1), [100, true, 0]);
});

test('pageChangedTextIsResent', async () => {
  const {win, t, progress} = translator('<p>one</p><p>two</p>');
  drain(t);
  const [p1] = win.document.querySelectorAll('p');
  p1.firstChild.nodeValue = 'changed';
  const added = win.document.createElement('p');
  added.textContent = 'new';
  win.document.body.appendChild(added);
  await tick();
  const batch = t.takeBatch();
  assert.deepEqual(batch.texts, ['changed', 'new']);
  t.onResult(batch.id, ['CHANGED', 'NEW']);
  await tick();
  assert.equal(t.takeBatch(), null);  // and our writes there aren't resent
  assert.equal(win.document.body.textContent, 'CHANGEDTWONEW');
  assert.equal(progress.filter(p => p[1]).length, 1, 'finished once');
  t.service.restore();
  assert.equal(win.document.body.textContent, 'changedtwonew');
});

test('scrollReordersQueue', () => {
  const win = dom('<p data-top="0">a</p><p data-top="1000">b</p><p data-top="2000">c</p>');
  place(win);
  win.innerHeight = 800;
  const t = T.create(win);
  t.service.translatePage('hi', 'en', () => {});
  // Page scrolled so c is on screen.
  win.Element.prototype.getBoundingClientRect = function() {
    const top = Number(this.dataset.top) - 1900;
    return {top, bottom: top + 20, width: 100, height: 20};
  };
  win.dispatchEvent(new win.Event('scroll'));
  assert.deepEqual(t.takeBatch().texts, ['c', 'a', 'b']);
});

test('progressCountsAnsweredBatchesAndNullKeepsOriginal', () => {
  const body = Array.from({length: 40}, (_, i) => `<p>s${i}</p>`).join('');
  const {win, t, progress} = translator(body);
  const a = t.takeBatch(), b = t.takeBatch(), c = t.takeBatch();
  assert.equal(t.takeBatch(), null);
  t.onResult(b.id, b.texts.map(() => null));
  assert.deepEqual(progress.at(-1), [33, false, 0]);
  t.onResult(a.id, a.texts.map(s => 'T' + s));
  t.onResult(999, ['ignored']);
  t.onResult(c.id, c.texts.map(s => 'T' + s));
  assert.deepEqual(progress.at(-1), [100, true, 0]);
  const ps = [...win.document.querySelectorAll('p')].map(p => p.textContent);
  assert.equal(ps[0], 'Ts0');
  assert.equal(ps[16], 's16');
  assert.equal(t.service.getDetectedLanguage(), 'hi');
});

test('longItemNotSent', () => {
  const long = 'क'.repeat(4001);
  const {win, t, progress} = translator(`<p>${long}</p><p>short</p>`);
  const b = t.takeBatch();
  assert.deepEqual(b.texts, ['short']);
  assert.equal(t.takeBatch(), null);
  t.onResult(b.id, ['SHORT']);
  assert.deepEqual(progress.at(-1), [100, true, 0]);
  assert.equal(win.document.querySelector('p').textContent, long);
});

test('emptyPageFinishesAtOnce', () => {
  const {t, progress} = translator('<script>x</script>');
  assert.deepEqual(progress, [[100, true, 0]]);
  assert.equal(t.takeBatch(), null);
});

test('restoreDropsLateResults', () => {
  const {win, t} = translator('<p>one</p>');
  const batch = t.takeBatch();
  t.service.restore();
  t.onResult(batch.id, ['ONE']);
  assert.equal(win.document.body.textContent, 'one');
  assert.equal(t.takeBatch(), null);
});

// Fix round 1.

test('pageRestoresOriginalUsesCacheNoNewBatch', async () => {
  const {win, t} = translator('<p>one</p><div id="r"><span>two</span></div>');
  drain(t);
  const [p] = win.document.querySelectorAll('p');
  p.firstChild.nodeValue = 'one';  // a re-render puts its own text back
  const r = win.document.getElementById('r');
  r.innerHTML = '<span>two</span>';  // or swaps the node for a new one
  await tick();
  assert.equal(t.takeBatch(), null, 'no model call for known text');
  assert.equal(p.textContent, 'ONE');
  assert.equal(r.textContent, 'TWO');
});

test('pageFlappingTextIsCapped', async () => {
  const {win, t} = translator('<p>one</p><p>moving</p>');
  drain(t);
  const [p1, p2] = win.document.querySelectorAll('p');
  // A page that always puts its own text back.
  let resets = 0;
  new win.MutationObserver(() => {
    if (p1.textContent !== 'one') { resets++; p1.firstChild.nodeValue = 'one'; }
  }).observe(p1, {characterData: true, subtree: true});
  p1.firstChild.nodeValue = 'one';
  // And text that changes to new words every time.
  let sent = 0;
  for (let i = 0; i < 10; i++) {
    p2.firstChild.nodeValue = 'word' + i;
    await tick();
    sent += drain(t);
  }
  for (let i = 0; i < 10; i++) await tick();
  assert.ok(resets <= 3, `page reset ${resets} times`);
  assert.equal(p1.textContent, 'one', 'left as the page wrote it');
  assert.equal(sent, 3);
  assert.equal(p2.textContent, 'word9');
  assert.equal(t.takeBatch(), null);
});

test('largePageNoLongTask', async () => {
  const n = 20000;
  const win = dom(Array.from({length: n}, (_, i) => `<p>s${i}</p>`).join(''));
  const t = T.create(win);
  const progress = [];
  const start = performance.now();
  t.service.translatePage('hi', 'en', (...a) => progress.push(a));
  assert.ok(performance.now() - start < 200, 'first slice is short');
  assert.ok(t.isCollecting(), 'the walk yields');
  const first = t.takeBatch();  // the first slice's text goes out at once
  assert.equal(first.texts[0], 's0');
  t.onResult(first.id, first.texts);
  while (t.isCollecting()) await tick();
  assert.ok(t.stats.chunks >= n / 500, `${t.stats.chunks} slices`);
  const before = t.stats.examined;
  let batch, batchesTaken = 0, sent = first.texts.length;
  while ((batch = t.takeBatch())) {
    t.onResult(batch.id, batch.texts.map(() => null));
    batchesTaken++;
    sent += batch.texts.length;
  }
  assert.equal(sent, n);
  // O(batch): every item looked at once, plus one look per batch boundary.
  assert.ok(t.stats.examined - before <= n + batchesTaken + 1);
  assert.deepEqual(progress.at(-1), [100, true, 0]);
});

test('translateAttributeCaseYesAndDesignMode', () => {
  const win = dom(`<div TRANSLATE="NO">a<span translate="yes">b</span></div>
    <div class="notranslate">c<p translate="">d</p></div><p>e</p>`);
  assert.deepEqual(texts(B.create().collect(win.document.body)), ['b', 'd', 'e']);
  win.document.designMode = 'on';
  assert.deepEqual(texts(B.create().collect(win.document.body)), []);
});

test('openShadowRootsWalkedAndObserved', async () => {
  const {win, t} = (() => {
    const win = dom('<p>light</p><div id="h"></div>');
    const sr = win.document.getElementById('h').attachShadow({mode: 'open'});
    sr.innerHTML = '<span>shadow</span>';
    const t = T.create(win);
    t.service.translatePage('hi', 'en', () => {});
    return {win, t};
  })();
  const batch = t.takeBatch();
  assert.deepEqual(batch.texts, ['light', 'shadow']);
  t.onResult(batch.id, ['LIGHT', 'SHADOW']);
  const sr = win.document.getElementById('h').shadowRoot;
  assert.equal(sr.textContent, 'SHADOW');
  const s = win.document.createElement('b');
  s.textContent = 'later';
  sr.appendChild(s);
  await tick();
  assert.deepEqual(t.takeBatch().texts, ['later']);
});

// Fix round 2.

test('scrollWithDeadItemsStillFinishes', async () => {
  const {win, t, progress} = translator('<p>a</p><p>b</p><p>c</p>');
  win.document.querySelector('p').remove();  // a queued item dies
  await tick();
  win.dispatchEvent(new win.Event('scroll'));
  const batch = t.takeBatch();
  assert.deepEqual(batch.texts, ['b', 'c']);
  t.onResult(batch.id, ['B', 'C']);
  assert.deepEqual(progress.at(-1), [100, true, 0]);
});

test('walkDoesNotRequeueObserverTranslatedText', async () => {
  const n = 3000;
  const win = dom(Array.from({length: n}, (_, i) => `<p>s${i}</p>`).join(''));
  const t = T.create(win);
  t.service.translatePage('hi', 'en', () => {});
  const first = t.takeBatch();
  t.onResult(first.id, first.texts.map(s => s.toUpperCase()));  // caches s0..
  // Before the walk reaches it, the page sets the last node to known text.
  assert.ok(t.isCollecting());
  const p = win.document.body.lastElementChild;
  p.firstChild.nodeValue = 's0';
  await Promise.resolve();  // the observer runs, the walk has not moved on
  assert.equal(p.textContent, 'S0');  // from the cache
  while (t.isCollecting()) await tick();
  let batch, texts = [];
  while ((batch = t.takeBatch())) {
    texts.push(...batch.texts);
    t.onResult(batch.id, batch.texts);
  }
  assert.equal(texts.filter(s => /^s0$/i.test(s)).length, 0);
  assert.equal(texts.length, n - first.texts.length - 1);
});

test('cacheHitsDoNotUseTheModelCap', async () => {
  const {win, t} = translator('<p>one</p>');
  drain(t);
  const node = win.document.querySelector('p').firstChild;
  for (let i = 0; i < 3; i++) {  // the page puts its original back 3 times
    node.nodeValue = 'one';
    await tick();
  }
  assert.equal(node.nodeValue, 'ONE');
  node.nodeValue = 'two';  // new text still gets a model call
  await tick();
  assert.deepEqual(t.takeBatch().texts, ['two']);
});

test('movedTranslatedNodesNotResent', async () => {
  // A page that moves already-translated paragraphs (a carousel, a re-render
  // that re-inserts the same nodes) must not send Tark's English back to the
  // model as if it were the page's Hindi.
  const {win, t} = translator('<div id="a"><p>one</p><p>two</p></div><div id="b"></div>');
  drain(t);
  assert.equal(win.document.body.textContent, 'ONETWO');
  const [p1, p2] = win.document.querySelectorAll('p');
  win.document.getElementById('b').appendChild(p1);  // moved: an added element
  win.document.getElementById('b').appendChild(p2.firstChild);  // a moved text node
  await tick();
  assert.equal(t.takeBatch(), null);
  assert.equal(win.document.body.textContent, 'ONETWO');
  t.service.restore();
});

test('deferredBatchResentAtFrontAtMostTwice', async () => {
  // The browser let the batch go (tab hidden, app in the background, the
  // deadline): its texts go back at the front, at most twice, then stay.
  const {win, t, progress} = translator('<p>one</p><p>two</p>');
  for (let round = 0; round < 2; round++) {
    const batch = t.takeBatch();
    assert.deepEqual(batch.texts, ['one', 'two']);
    t.onResult(batch.id, null);
    assert.equal(progress.filter(p => p[1]).length, 0, 'not finished while resending');
  }
  const last = t.takeBatch();
  assert.deepEqual(last.texts, ['one', 'two']);
  t.onResult(last.id, null);  // the third deferral: left original
  assert.equal(t.takeBatch(), null);
  assert.equal(win.document.body.textContent, 'onetwo');
  assert.equal(progress.filter(p => p[1]).length, 1, 'finished once');
  t.service.restore();
});

test('failedSentencesAreFinalNotResent', () => {
  const {win, t} = translator('<p>one</p><p>two</p>');
  const batch = t.takeBatch();
  t.onResult(batch.id, [null, 'TWO']);  // the model failed "one": it stays
  assert.equal(t.takeBatch(), null);
  assert.equal(win.document.body.textContent, 'oneTWO');
  t.service.restore();
});

test('deferredTextChangedByThePageIsNotResent', async () => {
  const {win, t} = translator('<p>one</p><p>two</p>');
  const batch = t.takeBatch();
  win.document.querySelector('p').firstChild.nodeValue = 'changed';
  await tick();  // the observer queues "changed" itself
  t.onResult(batch.id, null);
  const again = t.takeBatch();
  assert.deepEqual(again.texts.sort(), ['changed', 'two']);
  t.service.restore();
});

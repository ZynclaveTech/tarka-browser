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

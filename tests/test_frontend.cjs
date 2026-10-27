// Exercise the actual inline application script with deterministic browser seams.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const oldUrl = 'https://cdn.imweb.me/thumbnail/20261023/old.png';
const newUrl = 'https://cdn.imweb.me/thumbnail/20261026/new.png';
const cards = {
  updatedAt: 'reviewed earlier', sourceImages: [oldUrl],
  days: { '2026-10-27': [{ period: 'lunch', kind: 'A', name: 'Verified rice', price: 5500 }] }
};
const official = {
  weekStart: '2026-10-26', sourceImage: oldUrl, sha256: 'a'.repeat(64),
  fullImage: './data/official-menu.png', imageDate: '2026-10-23',
  dayImages: Array.from({length: 5}, (_, day) => `./data/official-day-${day}.png`)
};
const pending = {
  status: 'review_required', weekStart: '2026-10-26', sourceImage: newUrl,
  sha256: 'b'.repeat(64)
};

async function render(overrides = {}) {
  const elements = Object.fromEntries(['meal-list', 'selected-date', 'meal-count', 'updated-at', 'day-tabs', 'review-notice'].map(id => [id, {
    innerHTML: '', textContent: '', hidden: id === 'review-notice',
    addEventListener() {}, querySelectorAll() { return []; }
  }]));
  const responses = { 'menu.json': cards, 'official-menu.json': official, 'pending-menu.json': pending, ...overrides };
  const requested = [];
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : ['2026-10-27T03:00:00Z'])); }
    static now() { return Date.parse('2026-10-27T03:00:00Z'); }
  }
  const sandbox = {
    Intl, Date: FixedDate, URL, navigator: {}, location: {protocol: 'https:'},
    document: {
      querySelector(selector) { return elements[selector.slice(1)]; },
      querySelectorAll() { return []; }
    },
    fetch: async function(url) {
      const file = url.split('/').pop();
      requested.push(file);
      const value = responses[file];
      if (value instanceof Error) throw value;
      return {ok: value !== null, status: value === null ? 404 : 200, json: async () => value};
    }
  };
  vm.runInNewContext(source, sandbox, {filename: 'index.html'});
  await new Promise(resolve => setImmediate(resolve));
  return { elements, requested };
}

test('same URL with a mismatched recorded SHA uses official fallback, never stale cards', async () => {
  const { elements } = await render({ 'menu.json': { ...cards, sourceSha256: 'c'.repeat(64) } });
  assert.match(elements['meal-list'].innerHTML, /official-image/);
  assert.doesNotMatch(elements['meal-list'].innerHTML, /Verified rice/);
  assert.equal(elements['review-notice'].hidden, true);
});

for (const [name, value] of [
  ['404', null], ['network failure', new Error('offline')], ['undefined JSON', undefined],
  ['stale week', {...pending, weekStart: '2026-10-19'}],
  ['future week', {...pending, weekStart: '2026-11-02'}],
  ['not review required', {...pending, status: 'published'}],
  ['identical official identity', {...pending, sourceImage: oldUrl, sha256: official.sha256}]
]) {
  test(`optional pending ${name} does not break verified cards or show false warnings`, async () => {
    const { elements } = await render({'pending-menu.json': value});
    assert.match(elements['meal-list'].innerHTML, /Verified rice/);
    assert.equal(elements['review-notice'].hidden, true);
  });
}

test('same-URL pending image with changed digest shows the review notice', async () => {
  const { elements } = await render({'pending-menu.json': {...pending, sourceImage: oldUrl}});
  assert.match(elements['meal-list'].innerHTML, /Verified rice/);
  assert.equal(elements['review-notice'].hidden, false);
});

test('pending image link escapes all HTML attribute metacharacters', async () => {
  const malicious = `${newUrl}?x=" onmouseover="alert(1)&y=<tag>`;
  const { elements } = await render({'pending-menu.json': {...pending, sourceImage: malicious}});
  const notice = elements['review-notice'].innerHTML;
  assert.match(notice, /&quot;/);
  assert.match(notice, /&amp;/);
  assert.match(notice, /&lt;tag&gt;/);
  assert.doesNotMatch(notice, /href="[^"]*" onmouseover=/);
});

for (const unsafe of ['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'not a URL']) {
  test(`pending source cannot activate unsafe link ${unsafe.split(':')[0]}`, async () => {
    const { elements } = await render({'pending-menu.json': {...pending, sourceImage: unsafe}});
    assert.equal(elements['review-notice'].hidden, false);
    assert.doesNotMatch(elements['review-notice'].innerHTML, /href=/);
  });
}

test('matching optional SHA still displays verified cards', async () => {
  const { elements } = await render({'menu.json': {...cards, sourceSha256: official.sha256}});
  assert.match(elements['meal-list'].innerHTML, /Verified rice/);
});

test('null optional SHA is not silently treated as absent', async () => {
  const { elements } = await render({'menu.json': {...cards, sourceSha256: null}});
  assert.match(elements['meal-list'].innerHTML, /official-image/);
});

test('URL consistency guard remains required even when SHA matches', async () => {
  const { elements } = await render({'menu.json': {...cards, sourceImages: [newUrl], sourceSha256: official.sha256}});
  assert.match(elements['meal-list'].innerHTML, /official-image/);
  assert.equal(elements['review-notice'].hidden, true);
});

for (const [name, value] of [['missing', null], ['stale', {...cards, days: {'2026-10-19': cards.days['2026-10-27']}}]]) {
  test(`${name} cards still use official images rather than pending cards`, async () => {
    const { elements } = await render({'menu.json': value});
    assert.match(elements['meal-list'].innerHTML, /official-image/);
    assert.equal(elements['review-notice'].hidden, true);
  });
}

test('pending metadata failure cannot mask the existing all-sources failure message', async () => {
  const { elements } = await render({'menu.json': null, 'official-menu.json': null, 'pending-menu.json': new Error('offline')});
  assert.match(elements['meal-list'].innerHTML, /class="error"/);
});

test('pending image keeps verified cards but prominently labels them as older review', async () => {
  const { elements, requested } = await render();
  assert.ok(requested.includes('pending-menu.json'), 'optional pending metadata must be fetched');
  assert.match(elements['meal-list'].innerHTML, /Verified rice/);
  assert.equal(elements['review-notice'].hidden, false);
  assert.match(elements['review-notice'].innerHTML, /공식 식단표가 변경/);
  assert.match(elements['review-notice'].innerHTML, /이전에 검증/);
  assert.ok(elements['review-notice'].innerHTML.includes(`href="${newUrl}"`));
  assert.ok(html.indexOf('id="review-notice"') < html.indexOf('id="meal-list"'), 'notice must precede cards');
});

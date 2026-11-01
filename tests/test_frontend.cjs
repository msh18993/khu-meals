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

const sunday = '2026-11-01T03:00:00Z';
const nextWeekDates = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06'];
const nextWeekOfficial = {
  ...official, weekStart: nextWeekDates[0], sourceImage: newUrl,
  sha256: 'b'.repeat(64), imageDate: '2026-10-30'
};
const nextWeekCards = {
  updatedAt: 'reviewed Sunday', sourceImages: [newUrl], sourceSha256: nextWeekOfficial.sha256,
  days: Object.fromEntries(nextWeekDates.map(date => [date, [
    { period: 'lunch', kind: 'A', name: `Reviewed meal ${date}`, price: 5500 }
  ]]))
};
const sundayResponses = {
  'menu.json': nextWeekCards, 'official-menu.json': nextWeekOfficial, 'pending-menu.json': null
};

async function render(overrides = {}, now = '2026-10-27T03:00:00Z') {
  const elements = Object.fromEntries(['meal-list', 'selected-date', 'meal-count', 'updated-at', 'day-tabs', 'review-notice'].map(id => [id, {
    innerHTML: '', textContent: '', hidden: id === 'review-notice', listeners: {},
    addEventListener(type, listener) { this.listeners[type] = listener; },
    querySelectorAll() { return []; }
  }]));
  const responses = { 'menu.json': cards, 'official-menu.json': official, 'pending-menu.json': pending, ...overrides };
  const requested = [];
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return Date.parse(now); }
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
  const clickTab = dataset => elements['day-tabs'].listeners.click({
    target: { closest: () => ({ dataset }) }
  });
  return { elements, requested, clickTab };
}

test('Sunday previews all five reviewed next-week weekdays with their actual dates, never today', async () => {
  const { elements, clickTab } = await render(sundayResponses, sunday);
  assert.match(elements['meal-list'].innerHTML, /Reviewed meal 2026-11-02/);
  assert.deepEqual(
    [...elements['day-tabs'].innerHTML.matchAll(/data-date="([^"]+)"/g)].map(match => match[1]),
    nextWeekDates
  );
  assert.doesNotMatch(elements['day-tabs'].innerHTML, /오늘/);
  for (const date of nextWeekDates) {
    clickTab({ date });
    assert.ok(elements['meal-list'].innerHTML.includes(`Reviewed meal ${date}`));
    assert.match(elements['selected-date'].textContent, /11월/);
    assert.equal(elements['meal-count'].textContent, '1개 메뉴');
  }
  assert.equal(elements['review-notice'].hidden, true);
});

for (const date of nextWeekDates) {
  for (const missing of [true, false]) {
    test(`Sunday refuses preview when ${date} is ${missing ? 'missing' : 'empty'}`, async () => {
      const days = { ...nextWeekCards.days };
      if (missing) delete days[date];
      else days[date] = [];
      const { elements } = await render({
        ...sundayResponses, 'menu.json': { ...nextWeekCards, days }
      }, sunday);
      assert.match(elements['meal-list'].innerHTML, /official-image/);
      assert.doesNotMatch(elements['meal-list'].innerHTML, /Reviewed meal/);
      assert.doesNotMatch(elements['day-tabs'].innerHTML, /data-date=/);
      assert.equal(elements['review-notice'].hidden, true);
    });
  }
}

test('Sunday preview exposes only next Monday-Friday even if the payload also contains stale cards', async () => {
  const { elements, clickTab } = await render({
    ...sundayResponses,
    'menu.json': { ...nextWeekCards, days: { ...cards.days, ...nextWeekCards.days } }
  }, sunday);
  assert.match(elements['meal-list'].innerHTML, /Reviewed meal 2026-11-02/);
  assert.doesNotMatch(elements['meal-list'].innerHTML, /Verified rice/);
  assert.deepEqual(
    [...elements['day-tabs'].innerHTML.matchAll(/data-date="([^"]+)"/g)].map(match => match[1]),
    nextWeekDates
  );
  clickTab({ date: '2026-10-27' });
  assert.doesNotMatch(elements['meal-list'].innerHTML, /Verified rice/);
});

for (const [name, value] of [['missing', null], ['stale', cards]]) {
  test(`Sunday with ${name} cards uses next-week official images with explicit actual dates`, async () => {
    const { elements, clickTab } = await render({ ...sundayResponses, 'menu.json': value }, sunday);
    assert.match(elements['meal-list'].innerHTML, /official-image/);
    assert.doesNotMatch(elements['meal-list'].innerHTML, /Reviewed meal|Verified rice/);
    assert.doesNotMatch(elements['day-tabs'].innerHTML, /오늘/);
    for (const [day, date] of nextWeekDates.entries()) {
      clickTab({ day: String(day) });
      const expectedDate = new Intl.DateTimeFormat('ko-KR', {
        timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'short'
      }).format(new Date(`${date}T12:00:00+09:00`));
      assert.equal(elements['selected-date'].textContent, `${expectedDate} 공식 식단표`);
      assert.ok(elements['meal-list'].innerHTML.includes(`official-day-${day}.png?v=${nextWeekOfficial.sha256.slice(0, 12)}`));
    }
    assert.equal(elements['review-notice'].hidden, true);
  });
}

const { sourceSha256: ignoredSha, ...nextWeekCardsWithoutSha } = nextWeekCards;
for (const [name, value] of [
  ['different source URL despite matching SHA', { ...nextWeekCards, sourceImages: [oldUrl] }],
  ['different SHA at the same source URL', { ...nextWeekCards, sourceSha256: official.sha256 }],
  ['absent recorded SHA', nextWeekCardsWithoutSha],
  ['null recorded SHA', { ...nextWeekCards, sourceSha256: null }],
  ['last-week dates despite matching source identity', { ...nextWeekCards, days: cards.days }],
  ['only an actual Sunday card', { ...nextWeekCards, days: { '2026-11-01': cards.days['2026-10-27'] } }]
]) {
  test(`Sunday refuses ${name} and uses legitimate next-week official fallback`, async () => {
    const { elements } = await render({ ...sundayResponses, 'menu.json': value }, sunday);
    assert.match(elements['meal-list'].innerHTML, /official-image/);
    assert.match(elements['selected-date'].textContent, /11월 2일/);
    assert.doesNotMatch(elements['meal-list'].innerHTML, /Reviewed meal|Verified rice/);
    assert.equal(elements['review-notice'].hidden, true);
  });
}

for (const [name, value] of [
  ['last-week metadata', official],
  ['later future-week metadata', { ...nextWeekOfficial, weekStart: '2026-11-09' }],
  ['incomplete next-week image bundle', { ...nextWeekOfficial, dayImages: nextWeekOfficial.dayImages.slice(0, 4) }]
]) {
  test(`Sunday no-card fallback rejects ${name}`, async () => {
    const { elements } = await render({ ...sundayResponses, 'menu.json': null, 'official-menu.json': value }, sunday);
    assert.match(elements['meal-list'].innerHTML, /class="empty"/);
    assert.doesNotMatch(elements['meal-list'].innerHTML, /official-image|Reviewed meal|Verified rice/);
    assert.equal(elements['meal-count'].textContent, '');
    assert.equal(elements['review-notice'].hidden, true);
  });
}

for (const [name, value] of [['missing', null], ['last-week', official], ['later future-week', { ...nextWeekOfficial, weekStart: '2026-11-09' }]]) {
  test(`Sunday requires exact incoming-week official identity, not ${name} metadata`, async () => {
    const { elements } = await render({ ...sundayResponses, 'official-menu.json': value }, sunday);
    assert.doesNotMatch(elements['meal-list'].innerHTML, /Reviewed meal|Verified rice|official-image/);
    assert.equal(elements['review-notice'].hidden, true);
  });
}

test('Sunday does not resurrect last-week cards even when last-week official identity matches', async () => {
  const { elements } = await render({ 'menu.json': { ...cards, sourceSha256: official.sha256 } }, sunday);
  assert.match(elements['meal-list'].innerHTML, /class="empty"/);
  assert.doesNotMatch(elements['meal-list'].innerHTML, /Verified rice|official-image/);
  assert.equal(elements['review-notice'].hidden, true);
});

for (const [name, value, visible] of [
  ['changed next-week source', { ...pending, weekStart: nextWeekDates[0], sourceImage: oldUrl }, true],
  ['changed next-week SHA at the same URL', { ...pending, weekStart: nextWeekDates[0], sha256: official.sha256 }, true],
  ['identical next-week identity', { ...pending, weekStart: nextWeekDates[0] }, false],
  ['last-week pending change', pending, false]
]) {
  test(`Sunday pending notice handles ${name}`, async () => {
    const { elements } = await render({ ...sundayResponses, 'pending-menu.json': value }, sunday);
    assert.match(elements['meal-list'].innerHTML, /Reviewed meal 2026-11-02/);
    assert.equal(elements['review-notice'].hidden, !visible);
    if (visible) assert.match(elements['review-notice'].innerHTML, /이전에 검증/);
  });
}

for (const date of nextWeekDates) {
  test(`regular weekday ${date} still selects and labels only its actual today`, async () => {
    const { elements } = await render(sundayResponses, `${date}T03:00:00Z`);
    assert.ok(elements['meal-list'].innerHTML.includes(`Reviewed meal ${date}`));
    assert.ok(elements['day-tabs'].innerHTML.includes(`data-date="${date}" aria-selected="true">오늘`));
    assert.equal([...elements['day-tabs'].innerHTML.matchAll(/>오늘</g)].length, 1);
    assert.equal(elements['review-notice'].hidden, true);
  });
}

test('regular weekday can still use verified today cards if official metadata is unavailable', async () => {
  const { elements } = await render({ 'official-menu.json': null });
  assert.match(elements['meal-list'].innerHTML, /Verified rice/);
  assert.match(elements['day-tabs'].innerHTML, /data-date="2026-10-27" aria-selected="true">오늘/);
  assert.equal(elements['review-notice'].hidden, true);
});

test('regular weekday no-card fallback keeps its actual weekday and date', async () => {
  const { elements } = await render({ 'menu.json': null });
  assert.match(elements['meal-list'].innerHTML, /official-day-1\.png/);
  assert.match(elements['selected-date'].textContent, /10월 27일/);
});

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

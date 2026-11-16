// Integration tests for public/index.html against the fixed snapshot in tests/fixtures.
// Run: cd tests && npm ci && npm test
const test = require('node:test');
const assert = require('node:assert/strict');
const { openPage } = require('./harness');

async function withPage(query, fn, opts) {
  const page = await openPage(query, opts);
  try {
    await fn(page);
    assert.deepEqual(page.errors, [], 'page threw script errors');
  } finally {
    page.close();
  }
}

test('deep link: burglaries, all time, Menlo Oaks 3mi shows every matching item', () =>
  withPage('?filter=burglary&days=all&geo=1', async page => {
    assert.deepEqual(page.counts(), { incidents: 3, cases: 3 });
    assert.equal(page.visible(), 6);
    for (const m of ['2026-09', '2026-10', '2026-11']) assert.ok(page.fetched.includes(`data/${m}.json`), `fetched ${m}`);
  }));

test('deep link: the chart counts the same items the map shows', () =>
  withPage('?filter=burglary&days=all&geo=1', async page => {
    assert.equal(page.chartTotal(), page.visible());
    const heatTotal = Number(page.$('#chart-heatmap tfoot td:last-child').textContent);
    assert.equal(heatTotal, page.visible());
  }));

test('deep link without geo includes the burglary outside Menlo Oaks', () =>
  withPage('?filter=burglary&days=all', async page => {
    assert.equal(page.visible(), 7);
  }));

test('deep link copied with "&amp;" still applies every filter', () =>
  withPage('?filter=burglary&amp;days=all&amp;geo=1', async page => {
    assert.equal(page.visible(), 6);
    assert.equal(page.$('#inc-label').textContent, 'Incidents (all)');
  }));

test('a saved "All" range is restored when the link has no days', () =>
  withPage('', async page => {
    assert.equal(page.$('#inc-label').textContent, 'Incidents (all)');
    assert.equal(page.visible(), 12);
  }, { storage: { cf_settings: JSON.stringify({ filter: 'all', days: 0, geo: false }) } }));

test('default view: last 7 days, loads only the current month, no arrests yet', () =>
  withPage('', async page => {
    assert.deepEqual(page.counts(), { incidents: 4, cases: 1 });
    assert.deepEqual(page.fetched.filter(f => f.startsWith('data/')), ['data/2026-11.json']);
    assert.ok(!page.fetched.includes('arrests.json'));
  }));

test('longer ranges load older months on demand', () =>
  withPage('', async page => {
    await page.click('.time-btn[data-days="31"]');
    assert.ok(page.fetched.includes('data/2026-10.json'));
    assert.ok(!page.fetched.includes('data/2026-09.json'));
    await page.click('.time-btn[data-days="0"]');
    assert.ok(page.fetched.includes('data/2026-09.json'));
    assert.equal(page.visible(), 12);
    assert.equal(page.chartTotal(), 12);
  }));

test('feed shows real local times, newest first', () =>
  withPage('', async page => {
    const times = page.feedTimes();
    assert.equal(times.length, 5);
    assert.match(times[0], /^Nov 15 1:05\sPM/);   // Menlo Park, 13:05 local
    assert.match(times[1], /^Nov 15 11:30\sAM/);  // Palo Alto, 19:30 UTC
    assert.match(times[2], /^Nov 15 9:00\sAM/);
    assert.match(times[3], /^Nov 14 9:45\sPM/);
    assert.match(times[4], /^Nov 13/);            // case: report date only
    assert.ok(!times.some(t => /12:00\sAM/.test(t)), 'no placeholder midnight times');
  }));

test('text from the feeds is shown as text, not markup', () =>
  withPage('', async page => {
    assert.equal(page.$$('#feed-list img, #feed-list b').length, 0);
    assert.equal(page.window.__xss, undefined);
    assert.ok(page.$('#feed-list').textContent.includes('<img src=x'));
  }));

test('arrests load when the panel opens, and names are escaped', () =>
  withPage('', async page => {
    await page.click('#arrests-btn');
    assert.ok(page.fetched.includes('arrests.json'));
    assert.equal(page.$$('#arrests-tbody i').length, 0);
    assert.ok(page.$('#arrests-tbody').textContent.includes('Doe, <i>Jane</i>'));
  }));

test('map can zoom to street level so nearby incidents separate', () =>
  withPage('', async page => {
    assert.ok(page.js('map').getMaxZoom() >= 18, `max zoom is ${page.js('map').getMaxZoom()}`);
  }));

test('header shows agencies and freshness from the data', () =>
  withPage('', async page => {
    assert.equal(page.$('#agency-count').textContent, '5');
    assert.match(page.$('#last-updated').textContent, /Last updated: .* \(1h 0m ago\)$/);
  }));

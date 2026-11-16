// Loads public/index.html in jsdom the way a browser would, with:
//  - Leaflet and MarkerCluster from node_modules (same versions as the CDN tags),
//  - a stand-in for Chart.js that records what the page asked it to draw,
//  - fetch() answered from tests/fixtures, and a log of every file requested,
//  - "now" pinned to 2026-11-16 12:00 PST so date ranges are stable.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '..');
const FIXTURES = path.join(__dirname, 'fixtures');
const NM = path.join(__dirname, 'node_modules');
const NOW = Date.parse('2026-11-16T12:00:00-08:00');

function inlineScript(file) {
  const code = fs.readFileSync(path.join(NM, file), 'utf8').replace(/<\/script>/g, '<\\/script>');
  return `<script>${code}</script>`;
}

function pageHtml() {
  let html = fs.readFileSync(path.join(ROOT, 'public', 'index.html'), 'utf8');
  const swaps = [
    [/<script src="[^"]*\/leaflet@[^"]*"><\/script>/, inlineScript('leaflet/dist/leaflet-src.js')],
    [/<script src="[^"]*leaflet\.markercluster[^"]*"><\/script>/, inlineScript('leaflet.markercluster/dist/leaflet.markercluster-src.js')],
    [/<script src="[^"]*chart\.js[^"]*"><\/script>/,
      '<script>window.Chart = class { constructor(ctx, cfg) { this.data = cfg.data; this.options = cfg.options; window.__charts.push(this); } update() {} destroy() {} };</script>'],
  ];
  for (const [re, replacement] of swaps) {
    if (!re.test(html)) throw new Error(`index.html no longer has a script tag matching ${re}`);
    html = html.replace(re, () => replacement);
  }
  return html.replace(/<link rel="stylesheet"[^>]*>/g, '');
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function openPage(query = '', { storage } = {}) {
  const fetched = [];
  const errors = [];
  const dom = new JSDOM(pageHtml(), {
    url: 'https://crime.rayhe.net/' + query,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.__charts = [];
      const RealDate = window.Date;
      class FixedDate extends RealDate {
        constructor(...args) { if (args.length) super(...args); else super(NOW); }
        static now() { return NOW; }
      }
      window.Date = FixedDate;
      if (storage) for (const [k, v] of Object.entries(storage)) window.localStorage.setItem(k, v);
      window.matchMedia = q => ({ matches: /1200/.test(q), addEventListener() {}, removeEventListener() {} });
      window.HTMLCanvasElement.prototype.getContext = () => ({});
      window.SVGSVGElement.prototype.createSVGRect = () => ({});
      window.HTMLElement.prototype.scrollIntoView = function () {};
      Object.defineProperty(window.HTMLElement.prototype, 'clientWidth', { get() { return 1000; } });
      Object.defineProperty(window.HTMLElement.prototype, 'clientHeight', { get() { return 700; } });
      window.addEventListener('error', e => errors.push(e.message));
      window.fetch = async (url) => {
        const rel = new URL(url, 'https://crime.rayhe.net/').pathname.replace(/^\//, '');
        fetched.push(rel);
        const file = path.join(FIXTURES, rel);
        if (!file.startsWith(FIXTURES) || !fs.existsSync(file)) {
          return { ok: false, status: 404, json: async () => { throw new Error('404 ' + rel); } };
        }
        const body = fs.readFileSync(file, 'utf8');
        return { ok: true, status: 200, json: async () => JSON.parse(body) };
      };
    },
  });
  const { window } = dom;
  const page = {
    window,
    fetched,
    errors,
    $: sel => window.document.querySelector(sel),
    $$: sel => [...window.document.querySelectorAll(sel)],
    js: expr => window.eval(expr),
    async settle() {
      // wait until data has rendered and no month files are still loading
      for (let i = 0; i < 100; i++) {
        const pill = page.$('#map-loading');
        const busy = pill ? !pill.hidden : false;
        if (page.$('#inc-count').textContent !== '—' && !busy) break;
        await sleep(20);
      }
      await sleep(50);
    },
    async click(sel) {
      page.$(sel).click();
      await sleep(20);
      await page.settle();
    },
    counts() {
      const num = id => Number(page.$(id).textContent.replace(/,/g, ''));
      return { incidents: num('#inc-count'), cases: num('#case-count') };
    },
    visible() { return page.js('visibleSet').size; },
    chartTotal() {
      const chart = window.__charts[0];
      return chart.data.datasets.reduce((sum, ds) => sum + ds.data.reduce((a, b) => a + b, 0), 0);
    },
    feedTimes() { return page.$$('.feed-item .feed-time').map(e => e.textContent.replace(/\s+/g, ' ').trim()); },
    close() { window.close(); },
  };
  await page.settle();
  return page;
}

module.exports = { openPage };

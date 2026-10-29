// Audit-only behavioral probes: execute current production ESM with a small DOM/IPC test double.
// These assertions describe observed defects, NOT desired regression-test expectations.
// Run: node --experimental-vm-modules .scratch/bug-audit-20260928/frontend-probes.mjs
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const web = path.join(root, 'tlbb-explorer/app/web');
class Element {
  constructor() { this.children = []; this.events = {}; this.dataset = {}; this.style = {}; this.hidden = false; this.checked = false; this.value = ''; this.className = ''; this._html = ''; this.textContent = ''; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v; this.children = []; }
  classList = { add: (...c) => c.forEach(x => this.classList.toggle(x, true)), remove: (...c) => c.forEach(x => this.classList.toggle(x, false)), toggle: (c, on) => { const s = new Set(this.className.split(' ').filter(Boolean)); if (on ?? !s.has(c)) s.add(c); else s.delete(c); this.className = [...s].join(' '); } };
  addEventListener(n, f) { (this.events[n] ??= []).push(f); }
  appendChild(n) { this.children.push(n); return n; }
  append(...n) { this.children.push(...n); }
  querySelectorAll(s) { return s === '.tab' ? this.children : []; }
  querySelector() { return new Element(); }
  insertAdjacentHTML(_, html) { this._html += html; }
  scrollTo() {}
  closest() { return new Element(); }
}
async function sandbox(entry, mock = {}, expose = {}) {
  const elements = new Map();
  const el = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const panes = ['preview', 'resource', 'relations', 'missing', 'files', 'origin'].map(pane => Object.assign(new Element(), { dataset: { pane } }));
  el('dTabs').children = panes.map(p => Object.assign(new Element(), { dataset: { tab: p.dataset.pane } }));
  const context = vm.createContext({ console, window: {}, document: { getElementById: el, createElement: () => new Element(), querySelectorAll: s => s.includes('tabpane') ? panes : [], addEventListener() {} }, localStorage: { getItem: () => null, setItem() {} }, setTimeout: () => 0, clearTimeout() {}, IntersectionObserver: class { observe() {} disconnect() {} }, Date });
  const mods = new Map();
  const key = p => path.resolve(p);
  async function get(p) {
    p = key(p);
    if (mods.has(p)) return mods.get(p);
    const rel = path.relative(web, p).replaceAll('\\', '/');
    let m;
    if (mock[rel]) {
      const values = mock[rel];
      m = new vm.SyntheticModule(Object.keys(values), function () { for (const [k, v] of Object.entries(values)) this.setExport(k, v); }, { context, identifier: p });
    } else {
      m = new vm.SourceTextModule(fs.readFileSync(p, 'utf8') + (expose[rel] || ''), { context, identifier: p });
    }
    mods.set(p, m);
    await m.link((s, ref) => get(path.resolve(path.dirname(ref.identifier), s)));
    return m;
  }
  const m = await get(path.join(web, entry));
  await m.evaluate();
  return { module: m.namespace, el, panes, modules: mods, get: name => mods.get(key(path.join(web, name))).namespace };
}
const noop = () => {};
const meshMock = { showMeshes: noop, hideMeshes: noop, applyTexture: () => true };

// Execute real detail.js, panels.js, detailState.js and ui.js; only IPC and WebGL are replaced.
const fixtureSource = fs.readFileSync(path.join(root, 'tlbb-explorer/app/tests/detailState.test.js'), 'utf8');
const fixtures = vm.runInNewContext(fixtureSource.slice(fixtureSource.indexOf('const CARD_A'), fixtureSource.indexOf('function dirtyFields')) + '\n({DETAIL_A, INSPECT_A})');
let failDetail = false;
const detail = await sandbox('detail.js', { 'mesh.js': meshMock, 'api.js': {
  cardDetail: async () => { if (failDetail) throw new Error('AUDIT: B read failed'); return fixtures.DETAIL_A; },
  assetInspect: async () => fixtures.INSPECT_A,
} });
await detail.module.showDetail(245);
detail.get('panels.js').showTabPane('files');
const previous = Object.fromEntries(['fileList', 'rawJson', 'ringBox'].map(id => [id, detail.el(id).innerHTML || detail.el(id).textContent]));
failDetail = true;
await detail.module.showDetail(999);
for (const id of Object.keys(previous)) assert.equal(detail.el(id).innerHTML || detail.el(id).textContent, previous[id]);
assert.ok(previous.fileList.includes('a.mesh'));
assert.equal(detail.panes.find(p => p.dataset.pane === 'files').hidden, false);
console.log('CONFIRMED detail: failed asset B still displays A fileList/rawJson/ringBox; files tab stays visible');

let selectedCalls = [];
let page = { items: [], queryWords: [], ready: true, total: 0 };
const list = await sandbox('list.js', { 'detail.js': { showDetail: gid => selectedCalls.push(gid) }, 'api.js': { listGroups: async () => page } }, { 'list.js': '\nexport { loadMore };' });
const st = list.get('state.js').state;
st.stats = { kinds: [{ value: 'mesh', label: 'Mesh', count: 2 }], scenarios: [], grades: [], totalGroups: 2, imageCandidates: 0, unnamed: 0 };
list.module.paintRail();
list.el('kinds').children[1].onclick();
await Promise.resolve();
assert.equal(st.kind, 'mesh');
assert.ok(list.el('kinds').children[0].className.includes('on'));
assert.equal(list.el('kinds').children[1].className, 'chip');
console.log('CONFIRMED filters: kind=mesh is applied while All remains highlighted; Mesh is not highlighted');
st.ready = true;
page = { items: [{ gid: 1, named: true, name: 'A', grade: 'A' }], queryWords: [], ready: true, total: 2 };
await list.module.refresh();
page = { items: [{ gid: 2, named: true, name: 'B', grade: 'A' }], queryWords: [], ready: true, total: 2 };
await list.module.loadMore();
st.selected = 1;
list.module.moveSelect(1);
assert.deepEqual(selectedCalls, []);
assert.ok(list.el('rows').innerHTML.includes('data-gid="2"'));
console.log('CONFIRMED pagination: appended row B exists but ArrowDown from A cannot select it');

let reading;
let statsCalls = 0;
const deferred = {};
const api = { hasShell: true, onReading: fn => { reading = fn; }, startWarm: async () => {}, preview: hash => new Promise(resolve => { deferred[hash] = resolve; }) };
const app = await sandbox('app.js', {
  'api.js': api,
  'list.js': { refresh: noop, refreshStats: async () => { statsCalls++; }, resetFilters: noop, toggleUnnamed: noop, moveSelect: noop },
  'health.js': { openHealth: noop, closeHealth: noop }, 'map.js': { openMap: noop, closeMap: noop },
  'detail.js': { clearDetail: noop, showDetail: noop }, 'browse.js': { initBrowse: noop, showTab: noop },
  'exportProgress.js': { initExportProgress: noop }, 'relations.js': { initRelations: noop, openRelations: noop, closeRelations: noop },
}, { 'app.js': '\nexport { openLightbox, closeLightbox };' });
assert.equal(app.get('state.js').state.view, 'browse');
assert.equal(statsCalls, 0);
await reading({ payload: { ready: false } });
assert.equal(statsCalls, 1);
console.log('CONFIRMED lazy warm wiring: reading event calls refreshStats even in untouched browse view');
app.module.openLightbox('thumbA', 'A', 'A');
app.module.closeLightbox();
app.module.openLightbox('thumbB', 'B', 'B');
deferred.B({ url: 'fullB' }); await Promise.resolve();
deferred.A({ url: 'fullA' }); await Promise.resolve();
assert.equal(app.el('lightboxImg').src, 'fullA');
assert.equal(app.el('lightboxCap').textContent, 'B');
console.log('CONFIRMED lightbox race: late image A overwrites B while caption remains B');

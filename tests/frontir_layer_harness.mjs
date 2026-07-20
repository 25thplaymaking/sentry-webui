/* Behavioural harness for the Frontir layer (static/frontir.js).
 *
 *   node tests/frontir_layer_harness.mjs        # exits non-zero on failure
 *
 * Zero dependencies by design: it implements just enough real DOM (nodes,
 * classList, dataset, a small selector matcher, synchronous MutationObserver
 * delivery) to EXECUTE frontir.js and assert what it actually does. The
 * repo's pytest suite checks source presence; this checks behaviour.
 *
 * Covers the two surfaces most likely to break on an upstream merge:
 *   - the Projects section, which re-labels a .project-bar that
 *     renderSessionList() rebuilds from scratch on every render;
 *   - the speaker mute, which wraps window.autoReadLastAssistant — a
 *     function boot.js swaps out on voice activate and RESTORES on
 *     deactivate, dropping our wrapper unless it is re-asserted.
 */
import fs from 'node:fs';

let fails = 0, passes = 0;
const ok = (c, m) => { if (c) { passes++; } else { fails++; console.log('  FAIL ' + m); } };

/* ── tiny DOM ─────────────────────────────────────────────────────────── */
const observers = [];
function notify(target, type, attr) {
  for (const o of observers) {
    if (!o.targets.some(t => t === target || (o.opts.subtree && contains(t, target)))) continue;
    if (type === 'attributes') {
      if (!o.opts.attributes) continue;
      if (o.opts.attributeFilter && !o.opts.attributeFilter.includes(attr)) continue;
    }
    if (type === 'childList' && !o.opts.childList) continue;
    o.queue.push({ type });
  }
}
function contains(a, b) { for (let n = b; n; n = n.parent) if (n === a) return true; return false; }
function flush() { for (let i = 0; i < 40; i++) { let did = false; for (const o of observers) { if (o.queue.length) { const q = o.queue.splice(0); o.cb(q, o); did = true; } } if (!did) return; } throw new Error('observer loop did not settle — infinite re-trigger'); }

class ClassList {
  constructor(n) { this.n = n; }
  get s() { return (this.n._class || '').split(/\s+/).filter(Boolean); }
  set s(v) { const nv = v.join(' '); if (nv !== this.n._class) { this.n._class = nv; notify(this.n, 'attributes', 'class'); } }
  add(...c) { const s = this.s; for (const x of c) if (!s.includes(x)) s.push(x); this.s = s; }
  remove(...c) { this.s = this.s.filter(x => !c.includes(x)); }
  contains(c) { return this.s.includes(c); }
  toggle(c, f) { const has = this.contains(c); const want = f === undefined ? !has : !!f; if (want) this.add(c); else this.remove(c); return want; }
}

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null;
    this.attrs = {}; this.dataset = {}; this._class = ''; this._text = '';
    this.classList = new ClassList(this); this.style = {}; this.listeners = {};
    this.hidden = false; this.disabled = false; this.offsetParent = {};
  }
  get className() { return this._class; }
  set className(v) { this._class = v || ''; notify(this, 'attributes', 'class'); }
  get id() { return this.attrs.id || ''; }
  set id(v) { this.attrs.id = String(v); }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  set textContent(v) { this.children = []; this._text = v == null ? '' : String(v); }
  set innerHTML(v) { this.children = []; this._text = ''; this._html = v; const m = /^<(\w+)/.exec(v); if (m) { const c = new El(m[1]); c.parent = this; this.children.push(c); } }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { if (c.parent) c.parent.removeChild(c); c.parent = this; this.children.push(c); notify(this, 'childList'); return c; }
  insertBefore(c, ref) { if (c.parent) c.parent.removeChild(c); c.parent = this; const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) this.children.push(c); else this.children.splice(i, 0, c); notify(this, 'childList'); return c; }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) { this.children.splice(i, 1); c.parent = null; notify(this, 'childList'); } return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'class') this.className = v; notify(this, 'attributes', k); }
  getAttribute(k) { return k === 'class' ? this._class : (k in this.attrs ? this.attrs[k] : null); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, ev) { for (const f of this.listeners[t] || []) f(ev || { target: this, currentTarget: this, preventDefault() {} }); }
  click() { this.dispatch('click'); }
  focus() {}
  get all() { const out = []; const w = n => { for (const c of n.children) { out.push(c); w(c); } }; w(this); return out; }
  querySelectorAll(sel) { return this.all.filter(n => matches(n, sel, this)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) { for (let n = this; n; n = n.parent) if (matchSimple(n, sel)) return n; return null; }
}

/* selector support: "tag", "#id", ".cls", "[a]", '[a="v"]', ":not([disabled])",
   and descendant combinators — everything frontir.js actually uses. */
function matchSimple(n, sel) {
  const parts = sel.match(/(\[[^\]]*\]|:not\([^)]*\)|[.#]?[\w-]+)/g) || [];
  for (const p of parts) {
    if (p.startsWith(':not(')) { if (matchSimple(n, p.slice(5, -1))) return false; }
    else if (p.startsWith('#')) { if (n.attrs.id !== p.slice(1)) return false; }
    else if (p.startsWith('.')) { if (!n.classList.contains(p.slice(1))) return false; }
    else if (p.startsWith('[')) {
      const m = /^\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]$/.exec(p); if (!m) return false;
      const key = m[1]; let val;
      if (key.startsWith('data-')) val = n.dataset[key.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())];
      else if (key === 'disabled') val = n.disabled ? '' : undefined;
      else val = n.attrs[key];
      if (val === undefined || val === null) return false;
      if (m[2] !== undefined && String(val) !== m[2]) return false;
    } else if (n.tagName !== p.toUpperCase()) return false;
  }
  return true;
}
function matches(n, sel, root) {
  const chain = sel.trim().split(/\s+(?![^[]*\])/);
  if (!matchSimple(n, chain[chain.length - 1])) return false;
  let i = chain.length - 2, cur = n.parent;
  while (i >= 0) { let found = false; for (let p = cur; p && p !== root.parent; p = p.parent) if (matchSimple(p, chain[i])) { found = true; cur = p.parent; break; } if (!found) return false; i--; }
  return true;
}

const doc = new El('document');
doc.documentElement = new El('html'); doc.body = new El('body');
doc.documentElement.dataset.skin = 'frontir';
doc.appendChild(doc.documentElement); doc.documentElement.appendChild(doc.body);
doc.createElement = t => new El(t);
doc.getElementById = id => doc.querySelectorAll('#' + id)[0] || null;
doc.readyState = 'complete';
doc.addEventListener = El.prototype.addEventListener.bind(doc);
doc.activeElement = null;

const store = {};
global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } };
global.MutationObserver = class { constructor(cb) { this.cb = cb; this.targets = []; this.queue = []; this.opts = {}; observers.push(this); } observe(t, o) { this.targets.push(t); this.opts = { ...this.opts, ...o }; } disconnect() {} };
global.document = doc;
global.window = { document: doc, localStorage: global.localStorage, addEventListener() {}, innerWidth: 1280, innerHeight: 900, matchMedia: () => ({ matches: true }) };
global.getComputedStyle = () => ({ position: 'static' });
global.setInterval = () => 0; global.clearInterval = () => {};

/* ── page scaffold: the bits frontir.js reaches for ──────────────────── */
const sidebar = new El('aside'); sidebar.className = 'sidebar';
const panelView = new El('div'); panelView.className = 'panel-view';
sidebar.appendChild(panelView);
const sessionList = new El('div'); sessionList.className = 'session-list'; sessionList.setAttribute('id', 'sessionList');
panelView.appendChild(sessionList);
doc.body.appendChild(sidebar);

/* the Settings → Text-to-speech checkbox */
const ttsCb = new El('input'); ttsCb.setAttribute('id', 'settingsTtsEnabled'); ttsCb.checked = false;
doc.body.appendChild(ttsCb);

/* the real speech entry point: messages.js calls window.autoReadLastAssistant
   on stream completion; boot.js swaps in its own override while a voice
   session is live and restores the original on deactivate. */
let spoke = 0;
const origAutoRead = () => { spoke++; };
global.window.autoReadLastAssistant = origAutoRead;
let stopped = 0;
global.window.stopTTS = () => { stopped++; };
global.window.registerHermesSkin = () => true;
global.window.switchPanel = () => {};
let voiceOn = false;
global.window._voiceModeActive = () => voiceOn;
/* ui.js's TTS text scrubber. boot.js's _speakResponse() resolves it through
   the scope chain, so it is the one seam that can gate a live voice session
   (see the note above guardStripForTTS). Stock behaviour is a passthrough. */
global.window._stripForTTS = (t) => t;

/* the two nodes the voice observer watches */
const voiceBtn = new El('button'); voiceBtn.setAttribute('id', 'btnVoiceMode');
const voiceInd = new El('div'); voiceInd.setAttribute('id', 'voiceModeIndicator');
doc.body.appendChild(voiceBtn); doc.body.appendChild(voiceInd);

/* build a .project-bar the way sessions.js does */
function renderProjectBar() {
  sessionList.children = [];
  const bar = new El('div'); bar.className = 'project-bar';
  for (const name of ['All', 'Unassigned', 'Ops']) { const c = new El('span'); c.className = 'project-chip'; c.textContent = name; bar.appendChild(c); }
  const add = new El('button'); add.className = 'project-create-btn'; add.textContent = '+'; bar.appendChild(add);
  sessionList.appendChild(bar);
  return bar;
}
renderProjectBar();

/* ── run frontir.js ───────────────────────────────────────────────────── */
const src = fs.readFileSync(new URL('../static/frontir.js', import.meta.url), 'utf8');
new Function('window', 'document', 'localStorage', 'MutationObserver', 'getComputedStyle', 'setInterval', 'clearInterval', src)(
  global.window, doc, global.localStorage, global.MutationObserver, global.getComputedStyle, global.setInterval, global.clearInterval);
flush();

console.log('\n── Projects section ──');
let bar = sessionList.querySelector('.project-bar');
ok(bar.dataset.frontirProjects === '1', 'bar marked');
ok(bar.getAttribute('role') === 'group', 'role=group');
ok(bar.getAttribute('aria-label') === 'Projects', 'aria-label=Projects');
const head = bar.children[0];
ok(head.tagName === 'H3' && head.className === 'frontir-projects-head', 'heading is first child');
ok(head.textContent === 'Projects', 'heading text');
ok(head.getAttribute('aria-hidden') === 'true', 'heading aria-hidden (group already names it)');
ok(bar.querySelectorAll('.project-chip').length === 3, 'all 3 upstream chips survive untouched');
ok(bar.querySelector('.project-create-btn') !== null, 'upstream create button survives');
const before = bar.children.length;
// idempotence: a second enrich pass must not double the heading
notify(sessionList, 'childList'); flush();
ok(bar.children.length === before, 'enrich is idempotent on re-fire');
// re-render (what renderSessionList does) must re-label the NEW bar
bar = renderProjectBar(); flush();
ok(bar.dataset.frontirProjects === '1' && bar.children[0].className === 'frontir-projects-head',
   're-rendered bar is re-labelled');
ok(bar.querySelectorAll('.frontir-projects-head').length === 1, 'exactly one heading after re-render');

console.log('\n-- Speaker mute --');
const nav = doc.getElementById('frontirNav');
ok(nav !== null, 'sidebar nav injected');
ok(global.window.autoReadLastAssistant.__frontirMute === true, 'speech entry point wrapped at init');

nav.querySelectorAll('.frontir-nav-item')[1].click();      // "Voice" -> opens console
flush();
const spk = doc.querySelectorAll('.frontir-dock-btn').find(b => {
  const l = b.querySelector('.frontir-dock-label');
  return l && (l.textContent === 'Speaker' || l.textContent === 'Muted');
});
ok(spk != null, 'speaker button present');
ok(spk.getAttribute('aria-label') === 'Mute speaker', 'accessible name is the action');
ok(spk.getAttribute('aria-pressed') === 'false', 'starts unmuted (no stored preference)');
ok(spk.querySelector('.frontir-dock-label').textContent === 'Speaker', 'starts labelled Speaker');

global.window.autoReadLastAssistant();
ok(spoke === 1, 'unmuted reply speaks');

spk.click(); flush();
ok(store['frontir-muted'] === '1', 'click persists the mute');
ok(stopped === 1, 'muting stops what is currently playing');
ok(spk.getAttribute('aria-pressed') === 'true', 'aria-pressed true when muted');
ok(spk.classList.contains('is-muted'), 'is-muted class drives the CSS override');
ok(spk.querySelector('.frontir-dock-label').textContent === 'Muted', 'visible label flips');
ok(!doc.body.classList.contains('tts-enabled'), 'does NOT touch the tts-enabled body class');
ok(store['hermes-tts-enabled'] === undefined, 'does NOT write the read-aloud-button preference');

global.window.autoReadLastAssistant();
ok(spoke === 1, 'muted reply stays silent');

// A live voice session is still let through at THIS entry point on purpose:
// blocking here skips boot.js's _speakResponse(), the only thing that returns
// the turn loop to listening, stranding the session in "thinking".
voiceOn = true;
global.window.autoReadLastAssistant();
ok(spoke === 2, 'voice session is not blocked at the autoRead entry point');

// It is gated one level deeper instead. _speakResponse() is closure-local and
// unwrappable, but it runs its text through the global _stripForTTS() and, on
// an empty result, returns the loop to listening rather than speaking
// (boot.js:1714). Model that bail exactly.
let listening = 0;
const speakResponse = () => {
  const clean = global.window._stripForTTS('a reply');
  if (!clean) { listening++; return; }           // boot.js:1714
  spoke++;
};
const beforeMuted = spoke;
speakResponse();
ok(spoke === beforeMuted, 'muted voice session speaks nothing');
ok(listening === 1, 'and the turn loop returns to listening, not stranded');

store['frontir-muted'] = '0';
speakResponse();
ok(spoke === beforeMuted + 1, 'unmuted voice session speaks');
ok(listening === 1, 'and takes no spurious listening transition');

// the gate is scoped to live sessions: the read-aloud button's text must be
// scrubbed normally when no session is running, muted or not
store['frontir-muted'] = '1';
voiceOn = false;
ok(global.window._stripForTTS('hello') === 'hello', 'strip untouched outside a voice session');

spk.click(); flush();
ok(store['frontir-muted'] === '0', 'second click unmutes');
ok(stopped === 1, 'unmuting does NOT call stopTTS');
ok(spk.querySelector('.frontir-dock-label').textContent === 'Speaker', 'label back to Speaker');
const beforeUnmuted = spoke;
global.window.autoReadLastAssistant();
ok(spoke === beforeUnmuted + 1, 'unmuted speaks again');

// boot.js restores the ORIGINAL function on voice deactivate, dropping our
// wrapper with it. The voice observer must re-assert it.
global.window.autoReadLastAssistant = origAutoRead;
ok(global.window.autoReadLastAssistant.__frontirMute === undefined, 'wrapper dropped by boot.js restore');
doc.getElementById('btnVoiceMode').classList.add('active');   // fire the voice observer
flush();
ok(global.window.autoReadLastAssistant.__frontirMute === true, 'wrapper re-asserted after boot.js restore');
store['frontir-muted'] = '1';
const n = spoke;
global.window.autoReadLastAssistant();
ok(spoke === n, 'mute still enforced after the restore/re-wrap cycle');

console.log(`\n${passes} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);

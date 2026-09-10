/* Frontir workspace additions. No framework, provider credentials, or local storage.
 * All personal memory passes through the existing WebUI/Gateway auth boundary.
 */
(function () {
  'use strict';
  if (window.SentryWorkspace) return;
  const doc = document;
  const API = '/api/sentry/profile-memory';
  const lifetime = new AbortController();
  const requests = new Set();
  const byId = id => doc.getElementById(id);
  const active = () => doc.body?.dataset.sentryProduct === 'true' &&
    doc.documentElement.dataset.skin === 'frontir';
  const node = (tag, cls, text) => {
    const result = doc.createElement(tag);
    if (cls) result.className = cls;
    if (text !== undefined) result.textContent = text;
    return result;
  };
  const listen = (target, type, fn) => target.addEventListener(type, fn, {signal: lifetime.signal});
  const button = (text, fn, cls = '') => {
    const result = node('button', cls, text);
    result.type = 'button';
    result.addEventListener('click', fn);
    return result;
  };
  const chars = value => Array.from(value).length;
  const validName = name => name.length > 0 && name.length <= 64 && !/[^A-Za-z0-9_.-]/.test(name);
  const timestamp = value => {
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? 'Unknown update time' : date.toLocaleString();
  };
  let epoch = 0, memory = null, palette = null, confirmation = null, opener = null;
  let state = null, controls = null;

  async function request(path, options = {}) {
    const controller = new AbortController();
    requests.add(controller);
    const timer = setTimeout(() => controller.abort(), 20000);
    const headers = {'Accept': 'application/json', 'X-Sentry-Workspace': '1'};
    if (options.method && options.method !== 'GET') {
      const csrf = typeof window.getCsrfToken === 'function' ? window.getCsrfToken() : window.CSRF_TOKEN;
      if (csrf) headers['X-CSRF-Token'] = csrf;
    }
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    try {
      const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store',
        ...options, headers: {...headers, ...options.headers}, signal: controller.signal});
      const data = response.status === 204 ? null : await response.json().catch(() => null);
      if (!response.ok) {
        const message = typeof data?.error === 'string' ? data.error :
          typeof data?.detail === 'string' ? data.detail : `Request failed (HTTP ${response.status}).`;
        const error = new Error(message);
        error.status = response.status;
        throw error;
      }
      if (response.status !== 204 && data === null) throw new Error('The server returned an invalid response.');
      return data;
    } finally {
      clearTimeout(timer);
      requests.delete(controller);
    }
  }

  function abortRequests() {
    for (const controller of requests) controller.abort();
    requests.clear();
  }

  function status(message, error = false) {
    if (!controls) return;
    controls.status.textContent = message;
    controls.status.dataset.state = error ? 'error' : 'ready';
  }

  function dirty() {
    return Boolean(state?.selected &&
      (controls.content.value !== state.original ||
       (state.creating && controls.name.value !== state.selected)));
  }

  function updateButtons() {
    if (!state || !controls) return;
    const selected = Boolean(state.selected);
    const busy = state.busy || !state.profile;
    controls.save.disabled = busy || !selected || !validName(controls.name.value) ||
      chars(controls.content.value) > 200000 || (!state.creating && !dirty());
    controls.save.textContent = state.busy === 'save' ? 'Saving…' : 'Save changes';
    controls.remove.disabled = busy || !selected || state.creating;
    controls.create.disabled = Boolean(busy);
    controls.refresh.disabled = Boolean(state.busy);
    controls.name.disabled = Boolean(busy || !selected || !state.creating);
    controls.content.disabled = Boolean(busy || !selected);
    controls.count.textContent = `${chars(controls.content.value).toLocaleString()} / 200,000 characters`;
    memory.setAttribute('aria-busy', state.busy ? 'true' : 'false');
  }

  function confirmChange(title, message, label) {
    if (confirmation) return Promise.resolve(false);
    return new Promise(resolve => {
      const dialog = node('dialog', 'sw-dialog sw-confirm');
      confirmation = dialog;
      dialog.setAttribute('aria-labelledby', 'swConfirmTitle');
      const heading = node('h2', '', title); heading.id = 'swConfirmTitle';
      const copy = node('p', 'sw-note', message);
      const actions = node('div', 'sw-confirm-actions');
      let settled = false;
      const finish = result => {
        if (settled) return;
        settled = true; dialog.close(); dialog.remove(); confirmation = null; resolve(result);
      };
      const cancel = button('Keep editing', () => finish(false)); cancel.autofocus = true;
      actions.append(cancel, button(label, () => finish(true), 'sw-danger'));
      dialog.append(heading, copy, actions);
      dialog.addEventListener('cancel', event => {event.preventDefault(); finish(false);});
      dialog.addEventListener('close', () => finish(false), {once: true});
      doc.body.append(dialog); dialog.showModal();
    });
  }

  async function mayDiscard() {
    if (state?.busy && state.busy !== 'load') return false;
    if (!dirty()) return true;
    return confirmChange('Discard unsaved changes?', 'Your draft is only held in this open editor. It has not been saved to Sentry.', 'Discard changes');
  }

  function renderList() {
    if (!controls || !state) return;
    const search = controls.search.value.trim().toLocaleLowerCase();
    const visible = state.rows.filter(row => row.section.toLocaleLowerCase().includes(search) ||
      row.content.toLocaleLowerCase().includes(search));
    controls.list.replaceChildren();
    if (!visible.length) controls.list.append(node('p', 'sw-muted', state.rows.length ? 'No matching sections.' : 'No saved personal notes.'));
    for (const row of visible) {
      const item = button('', () => select(row.section));
      item.setAttribute('aria-pressed', String(state.selected === row.section && !state.creating));
      item.append(node('span', '', row.section), node('span', 'sw-muted', `${chars(row.content).toLocaleString()} characters`));
      controls.list.append(item);
    }
  }

  function setSelection(name, creating = false) {
    const row = state.rows.find(item => item.section === name);
    state.selected = name; state.creating = creating;
    state.original = creating ? '' : (row?.content || '');
    state.version = creating ? null : row?.updated_at;
    controls.name.value = name || '';
    controls.content.value = state.original;
    controls.updated.textContent = creating ? 'Not saved' : row ? `Updated ${timestamp(row.updated_at)}` : 'Select a section to edit';
    status(''); renderList(); updateButtons();
  }

  async function select(name) {
    const ticket = epoch;
    if (!await mayDiscard() || ticket !== epoch || !state) return;
    setSelection(name); controls.content.focus();
  }

  function clearForIdentity(message) {
    abortRequests(); epoch++;
    if (!state) return;
    state.rows = []; state.profile = null; state.busy = null;
    setSelection(null); controls.identity.textContent = 'Sign-in context changed';
    status(message, true);
  }

  function handleError(error, fallback) {
    if (error.status === 401 || error.status === 403 || /^Profile changed\./.test(error.message)) {
      clearForIdentity('Your sign-in context changed. Close Memory, sign in again if needed, then reopen it.');
      return;
    }
    const message = error.name === 'AbortError'
      ? 'The request was interrupted. A write may have reached the server; reload to verify before retrying.'
      : error.message || fallback;
    status(message, true);
  }

  async function load() {
    const ticket = ++epoch;
    abortRequests(); state.busy = 'load'; updateButtons(); status('Loading personal memory…');
    try {
      const data = await request(API);
      if (ticket !== epoch || !state) return;
      if (!data || !Array.isArray(data.sections) || typeof data.profile_id !== 'string' ||
          data.sections.some(row => !row || typeof row.section !== 'string' ||
            typeof row.content !== 'string' || typeof row.updated_at !== 'string')) {
        throw new Error('The memory workspace contract is unavailable. Install the paired Gateway update.');
      }
      // Never merge a previously loaded profile's rows into another identity.
      const previous = state.profile === data.profile_id ? state.selected : null;
      state.profile = data.profile_id; state.rows = data.sections;
      controls.identity.textContent = `Personal notes · profile ${data.profile_id.slice(0,8)}`;
      setSelection(state.rows.some(row => row.section === previous) ? previous : (state.rows[0]?.section || null));
      status(state.rows.length ? `${state.rows.length} saved section${state.rows.length === 1 ? '' : 's'}.` : 'Create your first personal memory section.');
    } catch (error) {
      if (ticket === epoch) handleError(error, 'Memory could not be loaded.');
    } finally {
      if (ticket === epoch && state) {state.busy = null; updateButtons();}
    }
  }

  async function save() {
    if (controls.save.disabled) return;
    const ticket = epoch;
    const name = controls.name.value;
    const content = controls.content.value;
    state.busy = 'save'; updateButtons(); status('Saving…');
    try {
      const row = await request(`${API}/${encodeURIComponent(name)}`, {method: 'PUT', body: JSON.stringify({
        content, expected_updated_at: state.version, expected_profile_id: state.profile,
      })});
      if (ticket !== epoch || !state) return;
      if (!row || row.section !== name || typeof row.content !== 'string' || typeof row.updated_at !== 'string') {
        throw new Error('Save returned an invalid receipt. Reload to verify the server copy.');
      }
      state.rows = state.rows.filter(item => item.section !== name).concat(row).sort((a,b) => a.section.localeCompare(b.section));
      setSelection(name); status('Saved to your personal Gateway memory.');
    } catch (error) {
      if (ticket === epoch) handleError(error, 'Save failed. Your draft remains in the editor.');
    } finally {
      if (ticket === epoch && state) {state.busy = null; updateButtons();}
    }
  }

  async function remove() {
    if (controls.remove.disabled) return;
    const ticket = epoch;
    const name = state.selected;
    if (!await confirmChange('Delete this memory section?', `Delete “${name}” from personal memory? Existing conversation copies and Hermes agent memory are not deleted.`, 'Delete section')) return;
    if (ticket !== epoch || !state) return;
    state.busy = 'delete'; updateButtons(); status('Deleting…');
    const query = new URLSearchParams({expected_updated_at: state.version, expected_profile_id: state.profile});
    try {
      await request(`${API}/${encodeURIComponent(name)}?${query}`, {method: 'DELETE'});
      if (ticket !== epoch || !state) return;
      state.rows = state.rows.filter(row => row.section !== name);
      setSelection(state.rows[0]?.section || null); status('Section deleted from personal memory.');
    } catch (error) {
      if (ticket === epoch) handleError(error, 'Delete failed. The section has not been removed from this view.');
    } finally {
      if (ticket === epoch && state) {state.busy = null; updateButtons();}
    }
  }

  async function create() {
    const ticket = epoch;
    if (!await mayDiscard() || ticket !== epoch || !state) return;
    let name = 'notes', index = 2;
    while (state.rows.some(row => row.section === name)) name = `notes-${index++}`;
    setSelection(name, true); controls.name.focus(); controls.name.select();
  }

  function disposeMemory() {
    epoch++; abortRequests();
    if (confirmation) confirmation.close();
    if (memory) {memory.close(); memory.remove(); memory = null;}
    state = null; controls = null;
    if (opener?.isConnected) opener.focus();
  }

  async function closeMemory() {
    const ticket = epoch;
    if (!await mayDiscard() || ticket !== epoch) return;
    disposeMemory();
  }

  function openMemory() {
    if (!active()) return;
    if (memory?.open) {controls.search.focus(); return;}
    closePalette(); opener = doc.activeElement;
    state = {rows: [], profile: null, selected: null, creating: false, original: '', version: null, busy: null};
    memory = node('dialog', 'sw-dialog'); memory.id = 'sentryMemoryWorkspace';
    memory.setAttribute('aria-labelledby', 'swMemoryTitle');
    const header = node('header', 'sw-header'), heading = node('div', 'sw-heading');
    const title = node('h2', '', 'Memory'); title.id = 'swMemoryTitle';
    const identity = node('div', 'sw-muted', 'Personal Gateway notes');
    heading.append(title, identity); header.append(heading, button('Close', closeMemory));
    const grid = node('div', 'sw-grid'), sidebar = node('aside', 'sw-sidebar');
    const search = node('input', 'sw-search'); search.type = 'search'; search.placeholder = 'Search memory'; search.setAttribute('aria-label', 'Search memory');
    const add = button('New section', create);
    const list = node('nav', 'sw-list'); list.setAttribute('aria-label', 'Personal memory sections');
    sidebar.append(search, add, list);
    const editor = node('section', 'sw-editor'); editor.setAttribute('aria-label', 'Memory editor');
    const label = node('label', '', 'Section'); label.htmlFor = 'swSectionName';
    const name = node('input', 'sw-name'); name.id = 'swSectionName'; name.maxLength = 64; name.autocomplete = 'off';
    const contentLabel = node('label', '', 'Saved context'); contentLabel.htmlFor = 'swMemoryContent';
    const content = node('textarea', 'sw-content'); content.id = 'swMemoryContent'; content.spellcheck = false;
    content.placeholder = 'Stable preferences, project conventions, and useful context. Do not store credentials here.';
    const meta = node('div', 'sw-meta'), updated = node('span', 'sw-muted'), count = node('span', 'sw-muted'); meta.append(updated, count);
    const note = node('p', 'sw-note', 'Personal notes are reference material for private Gateway chat, with a bounded context budget. Hermes agent memory and its approval queue are separate. Deleting a note does not erase copies already in conversations.');
    editor.append(label, name, contentLabel, content, meta, note); grid.append(sidebar, editor);
    const footer = node('footer', 'sw-footer');
    const feedback = node('div', 'sw-status'); feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
    const refresh = button('Reload', async () => {const ticket = epoch; if (await mayDiscard() && ticket === epoch) await load();});
    const del = button('Delete', remove, 'sw-danger'), submit = button('Save changes', save, 'sw-primary');
    footer.append(feedback, refresh, del, submit); memory.append(header, grid, footer); doc.body.append(memory);
    controls = {identity, search, create: add, list, name, content, updated, count, status: feedback, refresh, remove: del, save: submit};
    search.addEventListener('input', renderList);
    for (const input of [name, content]) input.addEventListener('input', () => {updateButtons(); status(dirty() ? 'Unsaved changes' : '');});
    memory.addEventListener('cancel', event => {event.preventDefault(); void closeMemory();});
    memory.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {event.preventDefault(); void save();}
    });
    memory.showModal(); void load();
  }

  function availableCommands() {
    const commands = [{title: 'Personal memory', detail: 'Edit saved context', run: openMemory}];
    if (byId('btnNewChat')) commands.push({title: 'New task', detail: 'Start a conversation', run: () => {
      if (typeof window.switchPanel === 'function') window.switchPanel('chat', {fromRailClick: true});
      byId('btnNewChat')?.click();
    }});
    for (const [tab, title] of [['changes', 'Workspace changes'], ['github', 'GitHub'], ['integrations', 'Integrations']]) {
      const existing = doc.querySelector(`[data-sentry-inspector-tab="${tab}"]`);
      if (existing && typeof window.selectSentryInspectorTab === 'function') commands.push({title, detail: 'Open existing inspector', run: () => existing.click()});
    }
    if (typeof window.inspectCurrentWorkspace === 'function') commands.push({title: 'Refresh workspace diff', detail: 'Inspect the linked workspace', run: () => window.inspectCurrentWorkspace()});
    if (typeof window.switchPanel === 'function') commands.push({title: 'Settings', detail: 'Open existing settings', run: () => window.switchPanel('settings', {fromRailClick: true})});
    return commands;
  }

  function closePalette() {
    if (!palette) return;
    const {dialog, previous} = palette;
    palette = null; dialog.close(); dialog.remove();
    if (previous?.isConnected) previous.focus();
  }

  function openCommands() {
    if (!active() || memory?.open || confirmation) return;
    if (palette) {palette.input.focus(); return;}
    const previous = doc.activeElement;
    const dialog = node('dialog', 'sw-dialog sw-palette'); dialog.setAttribute('aria-labelledby', 'swCommandsTitle');
    const header = node('div', 'sw-header'), heading = node('div', 'sw-heading');
    const title = node('h2', '', 'Commands'); title.id = 'swCommandsTitle'; heading.append(title);
    header.append(heading, button('Close', closePalette));
    const body = node('div', 'sw-palette-body'), input = node('input', 'sw-search');
    input.type = 'search'; input.placeholder = 'Find a command…'; input.setAttribute('aria-label', 'Search commands');
    const results = node('div'); body.append(input, results); dialog.append(header, body);
    palette = {dialog, input, previous};
    const render = () => {
      results.replaceChildren();
      const items = availableCommands().filter(item => `${item.title} ${item.detail}`.toLocaleLowerCase().includes(input.value.toLocaleLowerCase()));
      for (const item of items) {
        const entry = button('', () => {closePalette(); void item.run();}, 'sw-command');
        entry.append(node('span', '', item.title), node('span', 'sw-muted', item.detail)); results.append(entry);
      }
      if (!items.length) results.append(node('p', 'sw-muted', 'No matching commands.'));
    };
    input.addEventListener('input', render);
    dialog.addEventListener('keydown', event => {
      const items = Array.from(results.querySelectorAll('button'));
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        const index = items.indexOf(doc.activeElement);
        items[(index + step + items.length) % items.length]?.focus();
      } else if (event.key === 'Enter' && doc.activeElement === input) {event.preventDefault(); items[0]?.click();}
    });
    dialog.addEventListener('cancel', event => {event.preventDefault(); closePalette();});
    doc.body.append(dialog); render(); dialog.showModal(); input.focus();
  }

  function icon(kind) {
    const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6'); svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    const path = doc.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', kind === 'memory' ? 'M5 4h14v16H5z M9 8h6 M9 12h6 M9 16h3' : 'M5 7l5 5-5 5 M13 17h6');
    svg.append(path); return svg;
  }

  function mount() {
    const nav = byId('frontirNav');
    if (!active()) {
      if (memory) disposeMemory(); closePalette();
      doc.querySelectorAll('[data-sentry-workspace-nav]').forEach(item => item.remove()); return;
    }
    if (!nav || nav.querySelector('[data-sentry-workspace-nav]')) return;
    for (const [kind, title, fn] of [['memory', 'Memory', openMemory], ['commands', 'Commands', openCommands]]) {
      const item = button('', fn, 'frontir-nav-item sw-nav');
      item.dataset.sentryWorkspaceNav = kind;
      item.append(icon(kind), node('span', '', title)); nav.append(item);
    }
  }

  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true; queueMicrotask(() => {scheduled = false; if (!lifetime.signal.aborted) mount();});
  });
  function boot() {
    mount();
    observer.observe(doc.documentElement, {attributes: true, attributeFilter: ['data-skin']});
    observer.observe(doc.body, {attributes: true, attributeFilter: ['data-sentry-product'], childList: true});
    const sidebar = doc.querySelector('.sidebar');
    if (sidebar) observer.observe(sidebar, {childList: true, subtree: true});
  }
  listen(window, 'beforeunload', event => {if (dirty()) {event.preventDefault(); event.returnValue = '';}});
  listen(window, 'pagehide', () => {disposeMemory(); closePalette();});
  listen(window, 'focus', async () => {
    if (!memory?.open || !state?.profile || state.busy) return;
    const ticket = epoch;
    const profile = state.profile;
    try {
      const data = await request(API);
      if (ticket === epoch && state && data.profile_id !== profile) {
        clearForIdentity('Your sign-in context changed. Close and reopen Memory.');
      }
    } catch (error) {
      if (ticket === epoch && state && (error.status === 401 || error.status === 403)) {
        clearForIdentity('Your sign-in context changed. Close and reopen Memory.');
      }
    }
  });
  // Do not steal the app's existing Ctrl/Cmd+K search shortcut.
  listen(doc, 'keydown', event => {
    if (!event.defaultPrevented && (event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'p' &&
        !doc.querySelector('dialog[open]') && active()) {
      event.preventDefault(); openCommands();
    }
  });
  if (doc.readyState === 'loading') listen(doc, 'DOMContentLoaded', boot); else boot();
  window.SentryWorkspace = Object.freeze({openMemory, openCommands, destroy() {
    lifetime.abort(); observer.disconnect(); disposeMemory(); closePalette();
    doc.querySelectorAll('[data-sentry-workspace-nav]').forEach(item => item.remove());
    delete window.SentryWorkspace;
  }});
})();

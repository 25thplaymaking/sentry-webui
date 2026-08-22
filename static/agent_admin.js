/* Agent panel: the agent's pending writes and its provider credentials.
 *
 * Both surfaces live inside Hermes, which this container never loads. They
 * reach us through the Sentry Gateway (/api/agent/*). Before this panel existed
 * neither was reachable from a browser at all: signing a Claude subscription
 * into the harness needed a TTY on the server, and memory writes the agent
 * staged for review accumulated on disk with nothing able to approve them.
 *
 * The rule this file follows everywhere: an outage is REPORTED, never rendered
 * as "nothing here". An empty review queue and an unreachable one must not look
 * alike — that resemblance is what kept the missing surface invisible.
 */

const AGENT_ADMIN_SUBSYSTEMS = ['memory', 'skills'];

let _agentAdminOAuthFlow = null;   // {flow_id, provider, authorize_url}
let _agentAdminOAuthPollTimer = null;
let _agentAdminBusy = false;

function _aaEsc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* The app bans the browser's native modal dialogs: they block the event loop and
 * look nothing like the rest of the UI. Use the house dialog and toast instead,
 * degrading safely if this panel ever loads standalone. */
async function _aaConfirm(title, message, confirmLabel) {
  if (typeof showConfirmDialog === 'function') {
    return await showConfirmDialog({
      title, message, confirmLabel, danger: true, focusCancel: true,
    });
  }
  return true;
}

function _aaToast(message) {
  if (typeof showToast === 'function') { showToast(message); return; }
  console.warn('[agent-admin]', message);
}

function _aaCsrf() {
  // Same token the rest of the app sends on mutating requests.
  if (typeof getCsrfToken === 'function') return getCsrfToken();
  if (typeof window !== 'undefined' && window.CSRF_TOKEN) return window.CSRF_TOKEN;
  return '';
}

async function _aaFetch(path, options = {}) {
  const opts = Object.assign({ headers: {} }, options);
  opts.headers = Object.assign({ 'Accept': 'application/json' }, opts.headers);
  if (opts.body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    const token = _aaCsrf();
    if (token) opts.headers['X-CSRF-Token'] = token;
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch (_) { data = null; }
  if (!data) {
    return { available: false, error: `request failed (HTTP ${resp.status})`, status: resp.status };
  }
  return data;
}

/* An unavailable surface renders as a visible, specific problem. `needs_rebuild`
 * is the case worth separating: no amount of retrying fixes a Hermes image that
 * predates the admin patch. */
function _aaUnavailable(payload, what) {
  const updating = Boolean(payload && payload.needs_rebuild);
  const message = _aaEsc(updating
    ? 'Sentry is still enabling this feature. Try again shortly.'
    : (payload && payload.error) || 'unavailable');
  const rebuild = updating
    ? `<div style="margin-top:6px;font-size:11px;color:var(--muted)">
         Sentry’s automatic updater needs to finish enabling this feature. Try again shortly.
       </div>`
    : '';
  return `<div style="padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--panel-bg)">
            <div style="font-size:12px;color:#e05;font-weight:600">${_aaEsc(what)} unavailable</div>
            <div style="margin-top:4px;font-size:12px;color:var(--muted)">${message}</div>
            ${rebuild}
          </div>`;
}

/* ── Pending writes ─────────────────────────────────────────────────────── */

function _aaRenderPending(payload, subsystem) {
  if (!payload || payload.available !== true) {
    return _aaUnavailable(payload, `Agent ${subsystem} review queue`);
  }
  const items = payload.items || [];
  const gateNote = payload.approval_required
    ? ''
    : `<div style="margin-bottom:8px;padding:8px;border-radius:6px;background:var(--input-bg);font-size:11px;color:var(--muted)">
         Approval is currently <strong>off</strong> for ${_aaEsc(subsystem)}, so the agent writes directly.
         Anything listed here was staged while it was on.
       </div>`;
  if (!items.length) {
    return `${gateNote}<div style="padding:12px;color:var(--muted);font-size:12px">No ${_aaEsc(subsystem)} writes awaiting review.</div>`;
  }
  const rows = items.map(item => {
    const when = item.created_at
      ? new Date(item.created_at * 1000).toLocaleString()
      : '';
    // The proposed content is shown in full, not just the summary: approving a
    // one-line description of a write you cannot see is not review.
    const content = item.content
      ? `<pre style="margin:6px 0 0;padding:8px;background:var(--input-bg);border-radius:6px;white-space:pre-wrap;word-break:break-word;font-size:12px">${_aaEsc(item.content)}</pre>`
      : '';
    const oldText = item.old_text
      ? `<div style="margin-top:6px;font-size:11px;color:var(--muted)">replaces:</div>
         <pre style="margin:2px 0 0;padding:8px;background:var(--input-bg);border-radius:6px;white-space:pre-wrap;word-break:break-word;font-size:12px;text-decoration:line-through;opacity:.7">${_aaEsc(item.old_text)}</pre>`
      : '';
    const id = _aaEsc(item.id);
    const sub = _aaEsc(subsystem);
    return `<div style="padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">
        <div style="font-size:12px;font-weight:600">${_aaEsc(item.summary || item.action || 'write')}</div>
        <div style="font-size:11px;color:var(--muted);white-space:nowrap">${_aaEsc(when)}</div>
      </div>
      <div style="margin-top:2px;font-size:11px;color:var(--muted)">
        ${_aaEsc(item.action || '')}${item.target ? ' → ' + _aaEsc(item.target) : ''}
        ${item.origin ? ' · ' + _aaEsc(item.origin) : ''}
      </div>
      ${content}
      ${oldText}
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="btn" onclick="agentAdminDecide('${sub}','${id}','approve')">Approve</button>
        <button class="btn" onclick="agentAdminDecide('${sub}','${id}','reject')">Reject</button>
      </div>
    </div>`;
  }).join('');
  return gateNote + rows;
}

async function agentAdminDecide(subsystem, pendingId, decision) {
  if (_agentAdminBusy) return;
  if (decision === 'reject') {
    const ok = await _aaConfirm(
      'Discard staged write',
      'This proposal will be discarded without being applied. It cannot be recovered.',
      'Discard',
    );
    if (!ok) return;
  }
  _agentAdminBusy = true;
  try {
    const result = await _aaFetch(
      `/api/agent/pending/${encodeURIComponent(subsystem)}/${encodeURIComponent(pendingId)}/${decision}`,
      { method: 'POST', body: '{}' },
    );
    if (result.available !== true) {
      _aaToast(`Could not ${decision}: ${result.error || 'unknown error'}`);
    }
  } finally {
    _agentAdminBusy = false;
    await loadAgentAdmin();
  }
}

/* ── Credentials ────────────────────────────────────────────────────────── */

function _aaRenderProviders(payload) {
  if (!payload || payload.available !== true) {
    return _aaUnavailable(payload, 'Agent credentials');
  }
  const providers = (payload.providers || []).filter(p => p.oauth_capable || p.authenticated);
  if (!providers.length) {
    return `<div style="padding:12px;color:var(--muted);font-size:12px">No credential providers reported.</div>`;
  }
  return providers.map(p => {
    const id = _aaEsc(p.id);
    const name = _aaEsc(p.name || p.id);
    const creds = (p.credentials || []).map(c =>
      `<div style="font-size:11px;color:var(--muted)">· ${_aaEsc(c.label || c.id)} (${_aaEsc(c.auth_type || 'credential')})</div>`
    ).join('');
    let action;
    if (p.authenticated) {
      action = `<button class="btn" onclick="agentAdminLogout('${id}')">Sign out</button>`;
    } else if (p.browser_login) {
      action = `<button class="btn" onclick="agentAdminStartOAuth('${id}')">Connect</button>`;
    } else {
      const reason = p.unavailable_reason
        || 'This provider does not currently offer an in-app connection flow.';
      action = `<div style="max-width:220px;font-size:11px;color:var(--muted);text-align:right">${_aaEsc(reason)}</div>`;
    }
    return `<div style="padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <div>
          <div style="font-size:12px;font-weight:600">${name}</div>
          ${name !== id ? `<div style="font-size:10px;color:var(--muted)">${id}</div>` : ''}
          <div style="font-size:11px;color:${p.authenticated ? '#2a2' : 'var(--muted)'}">
            ${p.authenticated ? 'Connected' : 'Not connected'}
          </div>
        </div>
        <div>${action}</div>
      </div>
      ${creds}
    </div>`;
  }).join('');
}

async function agentAdminStartOAuth(provider) {
  if (_agentAdminOAuthFlow && _agentAdminOAuthFlow.flow_id) {
    await agentAdminCancelOAuth();
  } else {
    _aaClearOAuthPoll();
  }
  const result = await _aaFetch('/api/agent/auth/oauth/start', {
    method: 'POST', body: JSON.stringify({ provider }),
  });
  if (result.available !== true || !result.flow_id) {
    _aaToast(`Could not start sign-in: ${result.error || 'unknown error'}`);
    return;
  }
  _agentAdminOAuthFlow = result;
  if (result.status === 'success') {
    _aaToast(`${result.name || result.provider} connected.`);
    _aaFinishOAuthUi();
    await loadAgentAdmin();
    return;
  }
  if (result.flow_kind === 'device') {
    _aaRenderDeviceOAuth(result);
    _aaScheduleOAuthPoll(result.poll_interval_seconds);
    return;
  }

  const box = document.getElementById('agentAdminOAuthBox');
  if (box) {
    box.style.display = '';
    box.innerHTML = `
      <div style="font-size:12px;font-weight:600">Connect ${_aaEsc(result.provider)}</div>
      <div style="margin-top:6px;font-size:12px;color:var(--muted)">
        ${_aaEsc(result.instructions || 'Open the link, approve, then paste the code below.')}
      </div>
      <div style="margin-top:8px">
        <a href="${_aaEsc(result.authorize_url)}" target="_blank" rel="noopener noreferrer"
           class="btn">Open authorization page ↗</a>
      </div>
      <input id="agentAdminOAuthCode" placeholder="Paste the full code (looks like abc123#xyz789)"
             style="margin-top:8px;width:100%;background:var(--input-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:12px"
             autocomplete="off" spellcheck="false">
      <div style="margin-top:4px;font-size:11px;color:var(--muted)">
        Paste the whole value including the part after “#”. That half proves the
        response belongs to this sign-in, and it is rejected without it.
      </div>
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="btn" onclick="agentAdminCompleteOAuth()">Finish sign-in</button>
        <button class="btn" onclick="agentAdminCancelOAuth()">Cancel</button>
      </div>`;
    const input = document.getElementById('agentAdminOAuthCode');
    if (input) input.focus();
  }
}

function _aaClearOAuthPoll() {
  if (_agentAdminOAuthPollTimer) {
    clearTimeout(_agentAdminOAuthPollTimer);
    _agentAdminOAuthPollTimer = null;
  }
}

function _aaFinishOAuthUi() {
  _aaClearOAuthPoll();
  _agentAdminOAuthFlow = null;
  const box = document.getElementById('agentAdminOAuthBox');
  if (box) { box.style.display = 'none'; box.innerHTML = ''; }
}

function _aaRenderDeviceOAuth(flow) {
  const box = document.getElementById('agentAdminOAuthBox');
  if (!box) return;
  const ready = flow.status === 'awaiting_user' && flow.authorize_url;
  const code = flow.user_code
    ? `<div style="margin-top:10px;font-size:11px;color:var(--muted)">Authorization code</div>
       <div style="display:flex;align-items:center;gap:8px;margin-top:3px">
         <code style="font-size:16px;letter-spacing:.08em;padding:7px 10px;border-radius:6px;background:var(--input-bg)">${_aaEsc(flow.user_code)}</code>
         <button class="btn" onclick="agentAdminCopyOAuthCode()">Copy</button>
       </div>`
    : '';
  const action = ready
    ? `<a href="${_aaEsc(flow.authorize_url)}" target="_blank" rel="noopener noreferrer" class="btn">Open sign-in page ↗</a>`
    : `<span style="font-size:11px;color:var(--muted)">Preparing secure sign-in…</span>`;
  box.style.display = '';
  box.innerHTML = `
    <div style="font-size:12px;font-weight:600">Connect ${_aaEsc(flow.provider)}</div>
    <div style="margin-top:6px;font-size:12px;color:var(--muted)">
      ${_aaEsc(flow.instructions || 'Preparing a secure authorization code…')}
    </div>
    ${code}
    <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
      ${action}
      <button class="btn" onclick="agentAdminCancelOAuth()">Cancel</button>
    </div>`;
}

async function agentAdminCopyOAuthCode() {
  const code = String((_agentAdminOAuthFlow && _agentAdminOAuthFlow.user_code) || '');
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code);
    _aaToast('Code copied');
  } catch (_) {
    _aaToast('Could not copy automatically. Select the code and copy it manually.');
  }
}

function _aaRenderOAuthTerminal(ok, message) {
  const box = document.getElementById('agentAdminOAuthBox');
  if (!box) return;
  box.style.display = '';
  box.innerHTML = `<div style="font-size:12px;font-weight:600;color:${ok ? '#2a2' : '#e05'}">${ok ? 'Connected' : 'Sign-in did not complete'}</div>
    <div style="margin-top:6px;font-size:12px;color:var(--muted)">${_aaEsc(message)}</div>
    ${ok ? '' : '<button class="btn" style="margin-top:8px" onclick="_aaFinishOAuthUi()">Close</button>'}`;
}

function _aaScheduleOAuthPoll(seconds) {
  _aaClearOAuthPoll();
  const delay = Math.max(1, Number(seconds || 3)) * 1000;
  _agentAdminOAuthPollTimer = setTimeout(agentAdminPollOAuth, delay);
}

async function agentAdminPollOAuth() {
  const flow = _agentAdminOAuthFlow;
  if (!flow || flow.flow_kind !== 'device') return;
  const result = await _aaFetch(`/api/agent/auth/oauth/${encodeURIComponent(flow.flow_id)}`);
  if (!_agentAdminOAuthFlow || _agentAdminOAuthFlow.flow_id !== flow.flow_id) return;
  if (result.available !== true) {
    _agentAdminOAuthFlow = null;
    _aaClearOAuthPoll();
    _aaRenderOAuthTerminal(false, result.error || 'Could not read sign-in status.');
    return;
  }
  _agentAdminOAuthFlow = Object.assign({}, flow, result);
  if (result.status === 'success') {
    _aaClearOAuthPoll();
    _aaRenderOAuthTerminal(true, 'Credentials were stored securely by Sentry.');
    _aaToast(`${result.provider || 'Provider'} connected.`);
    _agentAdminOAuthFlow = null;
    await loadAgentAdmin();
    setTimeout(_aaFinishOAuthUi, 1200);
    return;
  }
  if (result.status === 'error' || result.status === 'cancelled') {
    _agentAdminOAuthFlow = null;
    _aaClearOAuthPoll();
    _aaRenderOAuthTerminal(false, result.error || 'The sign-in was cancelled.');
    return;
  }
  _aaRenderDeviceOAuth(_agentAdminOAuthFlow);
  _aaScheduleOAuthPoll(result.poll_interval_seconds);
}

async function agentAdminCancelOAuth() {
  const flow = _agentAdminOAuthFlow;
  _aaClearOAuthPoll();
  if (flow && flow.flow_id) {
    await _aaFetch(`/api/agent/auth/oauth/${encodeURIComponent(flow.flow_id)}`, {
      method: 'DELETE', body: '{}',
    });
  }
  _aaFinishOAuthUi();
}

async function agentAdminCompleteOAuth() {
  if (!_agentAdminOAuthFlow) return;
  const input = document.getElementById('agentAdminOAuthCode');
  const code = input ? String(input.value || '').trim() : '';
  if (!code) { _aaToast('Paste the code from the authorization page first.'); return; }
  const result = await _aaFetch('/api/agent/auth/oauth/complete', {
    method: 'POST',
    body: JSON.stringify({ flow_id: _agentAdminOAuthFlow.flow_id, code }),
  });
  if (result.available !== true) {
    _aaToast(`Sign-in failed: ${result.error || 'unknown error'}`);
    return;
  }
  _aaFinishOAuthUi();
  _aaToast(`${result.provider || 'Provider'} connected.`);
  await loadAgentAdmin();
}

async function agentAdminLogout(provider) {
  const ok = await _aaConfirm(
    'Remove credentials',
    `Stored ${provider} credentials will be removed from the agent. You can sign in again afterwards.`,
    'Remove',
  );
  if (!ok) return;
  const result = await _aaFetch(`/api/agent/auth/providers/${encodeURIComponent(provider)}`, {
    method: 'DELETE', body: '{}',
  });
  if (result.available !== true) {
    _aaToast(`Could not sign out: ${result.error || 'unknown error'}`);
  }
  await loadAgentAdmin();
}

/* ── Inbox ──────────────────────────────────────────────────────────────── */

function _aaRenderInbox(payload) {
  // An error body without a messages array (e.g. the 401 no-identity refusal)
  // must render as unavailable, not as a false "No messages."
  if (!payload || payload.available === false || payload.unavailable
      || (payload.error && !Array.isArray(payload.messages))) {
    return _aaUnavailable(payload || {}, 'Agent inbox');
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const sendToggle =
    `<div style="margin-top:6px"><a href="#" onclick="agentAdminShowSend();return false" style="font-size:12px">Send a message to another agent…</a></div>`;
  if (!messages.length) {
    return `<div style="padding:12px;color:var(--muted);font-size:12px">No messages.</div>` + sendToggle;
  }
  const rows = messages.map((m) => {
    const when = m.created_at ? new Date(m.created_at).toLocaleString() : '';
    const id = _aaEsc(m.id);
    const readBadge = m.read
      ? ''
      : `<button class="panel-head-btn" style="font-size:11px" onclick="agentAdminMarkRead('${id}')">Mark read</button>`;
    return `
      <div style="padding:10px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;${m.read ? 'opacity:.75' : ''}">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
          <div style="font-size:11px;color:var(--muted)">from ${_aaEsc(m.sender_profile_id)} · ${_aaEsc(when)}</div>
          ${readBadge}
        </div>
        <pre style="margin:6px 0 0;padding:8px;background:var(--input-bg);border-radius:6px;white-space:pre-wrap;word-break:break-word;font-size:12px">${_aaEsc(m.body || '')}</pre>
      </div>`;
  }).join('');
  return rows + sendToggle;
}

function agentAdminShowSend() {
  const box = document.getElementById('agentAdminSendBox');
  if (!box) return;
  box.style.display = '';
  box.innerHTML = `
    <div style="padding:12px;border:1px solid var(--border);border-radius:8px">
      <div style="font-size:12px;font-weight:600">Send to another agent</div>
      <div style="font-size:11px;color:var(--muted);margin:4px 0 8px">
        Delivery needs an operator-granted allow-list entry for your profile → theirs; without one the Gateway refuses.
      </div>
      <input id="agentAdminSendRecipient" type="text" placeholder="Recipient profile id (UUID)"
             style="width:100%;box-sizing:border-box;margin-bottom:6px;padding:6px 8px;font-size:12px" autocomplete="off">
      <textarea id="agentAdminSendBody" rows="3" placeholder="Message"
             style="width:100%;box-sizing:border-box;margin-bottom:6px;padding:6px 8px;font-size:12px"></textarea>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="panel-head-btn" onclick="document.getElementById('agentAdminSendBox').style.display='none'">Cancel</button>
        <button class="panel-head-btn primary" onclick="agentAdminSendMessage()">Send</button>
      </div>
    </div>`;
}

async function agentAdminSendMessage() {
  const recipient = (document.getElementById('agentAdminSendRecipient') || {}).value || '';
  const body = (document.getElementById('agentAdminSendBody') || {}).value || '';
  if (!recipient.trim() || !body.trim()) { _aaToast('Recipient and message are both required.'); return; }
  const result = await _aaFetch('/api/agent-messages', {
    method: 'POST',
    body: JSON.stringify({ recipient_profile_id: recipient.trim(), body }),
  });
  if (result && (result.delivered || result.ok)) {
    _aaToast('Message delivered.');
    const box = document.getElementById('agentAdminSendBox');
    if (box) box.style.display = 'none';
  } else {
    _aaToast(`Could not send: ${(result && result.error) || 'unknown error'}`);
  }
}

async function agentAdminMarkRead(messageId) {
  const result = await _aaFetch('/api/agent-messages/read', {
    method: 'POST', body: JSON.stringify({ id: messageId }),
  });
  if (!result || result.error) {
    _aaToast(`Could not mark read: ${(result && result.error) || 'unknown error'}`);
    return;
  }
  await loadAgentAdmin();
}

/* ── Panel load ─────────────────────────────────────────────────────────── */

async function loadAgentAdmin() {
  const pendingEl = document.getElementById('agentAdminPending');
  const providersEl = document.getElementById('agentAdminProviders');
  if (!pendingEl && !providersEl) return;

  if (pendingEl) pendingEl.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">Loading…</div>';
  if (providersEl) providersEl.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">Loading…</div>';

  const inboxEl = document.getElementById('agentAdminInbox');
  if (inboxEl) inboxEl.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">Loading…</div>';

  const [memory, skills, providers, inbox] = await Promise.all([
    _aaFetch('/api/agent/pending/memory'),
    _aaFetch('/api/agent/pending/skills'),
    _aaFetch('/api/agent/auth/providers'),
    _aaFetch('/api/agent-messages'),
  ]);
  if (inboxEl) inboxEl.innerHTML = _aaRenderInbox(inbox);

  if (pendingEl) {
    pendingEl.innerHTML =
      `<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:4px 0 6px">Memory</div>`
      + _aaRenderPending(memory, 'memory')
      + `<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:14px 0 6px">Skills</div>`
      + _aaRenderPending(skills, 'skills');
  }
  if (providersEl) providersEl.innerHTML = _aaRenderProviders(providers);
}

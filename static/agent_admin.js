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
let _agentAdminProvidersPayload = null;

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
    return _aaUnavailable(payload, 'AI subscriptions');
  }
  const providers = (payload.providers || [])
    .filter(p => p.oauth_capable || p.authenticated)
    .slice()
    .sort((a, b) => {
      if (Boolean(a.authenticated) !== Boolean(b.authenticated)) return a.authenticated ? -1 : 1;
      if (Boolean(a.browser_login) !== Boolean(b.browser_login)) return a.browser_login ? -1 : 1;
      return String(a.name || a.id).localeCompare(String(b.name || b.id));
    });
  if (!providers.length) {
    return `<div class="agent-provider-empty">No subscription providers are available.</div>`;
  }
  return providers.map(p => {
    const id = _aaEsc(p.id);
    const name = _aaEsc(p.name || p.id);
    const models = Array.isArray(p.models)
      ? p.models.filter(m => m && m.id && m.model)
      : [];
    const currentModel = (typeof S !== 'undefined' && S.session)
      ? String(S.session.model || '')
      : '';
    const current = models.some(m => String(m.id) === currentModel);
    const count = models.length;
    const modelWord = count === 1 ? 'model' : 'models';
    const selectId = agentAdminProviderSelectId(p.id);

    if (p.authenticated) {
      const routeError = String(p.route_error || '').trim();
      const ready = !routeError && count > 0;
      const options = models.map(m => {
        const selected = String(m.id) === currentModel ? ' selected' : '';
        return `<option value="${_aaEsc(m.id)}"${selected}>${_aaEsc(m.model)}</option>`;
      }).join('');
      const modelControl = routeError || !count
        ? `<div class="agent-provider-route-error" role="status">
             ${_aaEsc(routeError || 'Connected, but no selectable models were reported.')}
           </div>
           <button class="btn" onclick="loadAgentAdmin()">Try again</button>`
        : `<label class="agent-provider-model-label" for="${_aaEsc(selectId)}">Choose a model</label>
           <div class="agent-provider-model-row">
             <select id="${_aaEsc(selectId)}" class="agent-provider-model-select">${options}</select>
             <button class="btn" onclick="agentAdminUseProviderModel('${id}')">Use in chat</button>
           </div>`;
      return `<section class="agent-provider-card is-connected" data-provider="${id}">
        <div class="agent-provider-head">
          <div>
            <div class="agent-provider-name">${name}</div>
            <div class="agent-provider-status ${ready ? 'is-ready' : 'is-error'}">
              ${ready ? ((current ? 'In use' : 'Ready') + ' · ' + count + ' ' + modelWord) : 'Connected · models unavailable'}
            </div>
          </div>
          <span class="agent-provider-ready ${ready ? '' : 'has-error'}" aria-label="Connected">${ready ? 'Ready' : 'Connected'}</span>
        </div>
        <div class="agent-provider-models">${modelControl}</div>
        <button class="agent-provider-disconnect" onclick="agentAdminLogout('${id}')">Disconnect</button>
      </section>`;
    }

    if (p.browser_login) {
      return `<section class="agent-provider-card" data-provider="${id}">
        <div class="agent-provider-head">
          <div>
            <div class="agent-provider-name">${name}</div>
            <div class="agent-provider-status">Use your existing subscription. No API key needed.</div>
          </div>
          <button class="btn" onclick="agentAdminStartOAuth('${id}')">Connect</button>
        </div>
      </section>`;
    }

    const reason = p.unavailable_reason
      || 'This provider does not currently offer an in-app connection flow.';
    return `<section class="agent-provider-card is-unavailable" data-provider="${id}">
      <div class="agent-provider-name">${name}</div>
      <div class="agent-provider-status">${_aaEsc(reason)}</div>
    </section>`;
  }).join('');
}

function agentAdminProviderSelectId(provider) {
  return `agentAdminModel-${String(provider || '').replace(/[^A-Za-z0-9_-]/g, '-')}`;
}

function _aaProviderName(provider) {
  const providers = (_agentAdminProvidersPayload && _agentAdminProvidersPayload.providers) || [];
  const match = providers.find(p => String(p.id || '') === String(provider || ''));
  return (match && match.name) || provider || 'account';
}

async function agentAdminUseProviderModel(provider) {
  const select = document.getElementById(agentAdminProviderSelectId(provider));
  const model = select ? String(select.value || '').trim() : '';
  if (!model) {
    _aaToast('Choose a model first.');
    return;
  }
  if (typeof populateModelDropdown === 'function') await populateModelDropdown();
  if (typeof selectModelFromDropdown !== 'function') {
    _aaToast('The model picker is not ready yet. Try again shortly.');
    return;
  }
  await selectModelFromDropdown(model, 'sentry');
  _aaToast(`Using ${select.options && select.selectedIndex >= 0
    ? select.options[select.selectedIndex].textContent
    : model} for this conversation.`);
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
    if (result.route_error) {
      _aaRenderOAuthTerminal(true, result.route_error, true);
    } else {
      _aaToast(`${_aaProviderName(result.provider)} connected and ready.`);
      _aaFinishOAuthUi();
      if (typeof populateModelDropdown === 'function') await populateModelDropdown();
    }
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
      <div class="agent-oauth-title">Connect ${_aaEsc(_aaProviderName(result.provider))}</div>
      <div class="agent-oauth-step">
        <span class="agent-oauth-step-number">1</span>
        <div><strong>Sign in with your provider</strong><br><span>Sentry opens the provider's secure page in a new tab.</span></div>
      </div>
      <div class="agent-oauth-action">
        <a href="${_aaEsc(result.authorize_url)}" target="_blank" rel="noopener noreferrer"
           class="btn">Open sign-in page ↗</a>
      </div>
      <div class="agent-oauth-step">
        <span class="agent-oauth-step-number">2</span>
        <div><strong>Paste the confirmation code</strong><br><span>Copy the complete value exactly as the provider shows it.</span></div>
      </div>
      <input id="agentAdminOAuthCode" class="agent-oauth-code-input" placeholder="Paste the complete confirmation code"
             autocomplete="off" spellcheck="false">
      <div class="agent-oauth-actions">
        <button class="btn" onclick="agentAdminCompleteOAuth()">Connect account</button>
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
    ? `<div class="agent-oauth-code-row">
         <code class="agent-oauth-code">${_aaEsc(flow.user_code)}</code>
         <button class="btn" onclick="agentAdminCopyOAuthCode()">Copy</button>
       </div>`
    : '';
  const action = ready
    ? `<a href="${_aaEsc(flow.authorize_url)}" target="_blank" rel="noopener noreferrer" class="btn">Open sign-in page ↗</a>`
    : `<span class="agent-provider-status">Preparing secure sign-in…</span>`;
  box.style.display = '';
  box.innerHTML = `
    <div class="agent-oauth-title">Connect ${_aaEsc(_aaProviderName(flow.provider))}</div>
    <div class="agent-oauth-step">
      <span class="agent-oauth-step-number">1</span>
      <div><strong>Copy this one-time code</strong>${code}</div>
    </div>
    <div class="agent-oauth-step">
      <span class="agent-oauth-step-number">2</span>
      <div><strong>Open the provider's sign-in page</strong><div class="agent-oauth-action">${action}</div></div>
    </div>
    <div class="agent-oauth-step">
      <span class="agent-oauth-step-number">3</span>
      <div><strong>Return to Sentry</strong><br><span>Models appear automatically when sign-in finishes.</span></div>
    </div>
    <div class="agent-oauth-actions">
      <span class="agent-oauth-waiting">Waiting for you to finish sign-in…</span>
      <button class="agent-provider-disconnect" onclick="agentAdminCancelOAuth()">Cancel</button>
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

function _aaRenderOAuthTerminal(ok, message, warning = false) {
  const box = document.getElementById('agentAdminOAuthBox');
  if (!box) return;
  box.style.display = '';
  const title = warning
    ? 'Connected, but models are not ready'
    : (ok ? 'Connected and ready' : 'Sign-in did not complete');
  box.innerHTML = `<div class="agent-oauth-terminal ${ok && !warning ? 'is-success' : 'is-error'}">${title}</div>
    <div class="agent-provider-status">${_aaEsc(message)}</div>
    ${ok && !warning ? '' : '<button class="btn agent-oauth-close" onclick="_aaFinishOAuthUi()">Close</button>'}`;
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
    const routeError = String(result.route_error || '').trim();
    _aaRenderOAuthTerminal(
      true,
      routeError || `${(result.models || []).length} models are now ready in Sentry.`,
      Boolean(routeError),
    );
    _aaToast(routeError
      ? `${_aaProviderName(result.provider)} connected; models need attention.`
      : `${_aaProviderName(result.provider)} connected and ready.`);
    _agentAdminOAuthFlow = null;
    if (!routeError && typeof populateModelDropdown === 'function') await populateModelDropdown();
    await loadAgentAdmin();
    if (!routeError) setTimeout(_aaFinishOAuthUi, 1200);
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
  const routeError = String(result.route_error || '').trim();
  if (routeError) {
    _aaRenderOAuthTerminal(true, routeError, true);
    _aaToast(`${_aaProviderName(result.provider)} connected; models need attention.`);
  } else {
    _aaFinishOAuthUi();
    _aaToast(`${_aaProviderName(result.provider)} connected and ready.`);
    if (typeof populateModelDropdown === 'function') await populateModelDropdown();
  }
  await loadAgentAdmin();
}

async function agentAdminLogout(provider) {
  const ok = await _aaConfirm(
    'Disconnect subscription',
    `${_aaProviderName(provider)} will be signed out and its models will disappear from Sentry. You can reconnect at any time.`,
    'Disconnect',
  );
  if (!ok) return;
  const result = await _aaFetch(`/api/agent/auth/providers/${encodeURIComponent(provider)}`, {
    method: 'DELETE', body: '{}',
  });
  if (result.available !== true) {
    _aaToast(`Could not disconnect: ${result.error || 'unknown error'}`);
  } else if (typeof populateModelDropdown === 'function') {
    await populateModelDropdown();
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
  _agentAdminProvidersPayload = providers;
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

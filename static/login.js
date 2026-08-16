/* Login page — external script, no inline handlers.
 * Loaded by the /login route. Reads data attributes from the form for
 * i18n strings so the server does not need to inject JS literals.
 */
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('login-form');
  var input = document.getElementById('pw');
  var passkeyBtn = document.getElementById('passkey-login');

  // `input` is absent when password sign-in is disabled (Sentry per-user
  // enrollment is then the only door), so only the form itself is required.
  if (!form) return;

  var invalidPw = form.getAttribute('data-invalid-pw') || 'Invalid password';
  var connFailed = form.getAttribute('data-conn-failed') || 'Connection failed';

  function showErr(msg) {
    var err = document.getElementById('err');
    if (err) { err.textContent = msg; err.style.display = 'block'; }
  }

  function hideErr() {
    var err = document.getElementById('err');
    if (err) { err.style.display = 'none'; }
  }

  // Return the ?next= redirect path if present and safe, otherwise './'
  // Guards against open-redirect: rejects protocol-relative (//evil.com),
  // absolute URLs, backslash variants, and control characters.
  function _safeNextPath() {
    try {
      var raw = new URL(window.location.href).searchParams.get('next');
      if (!raw) return './';
      if (raw.charAt(0) !== '/') return './';             // must be path-absolute
      if (raw.charAt(1) === '/' || raw.charAt(1) === '\\') return './'; // reject // and \\
      if (/[\x00-\x1f\x7f\s]/.test(raw)) return './';  // reject control chars / whitespace
      // #5578: never redirect back to the login page — that self-referential
      // chain is what grows the URL exponentially on repeated expired-auth
      // bounces. Detect the login route even through nested percent-encoding
      // (a nested chain looks like `/session/login%3Fnext%3D...`, where the `?`
      // is encoded so a plain split('?') wouldn't isolate the path). Decode a
      // few levels and check the leading PATH. Only collapse login-route chains
      // — a legitimate non-login path that merely carries its own `next=` query
      // key must still round-trip.
      if (raw.length > 2048) return './';
      var probe = raw;
      var stabilized = false;
      for (var i = 0; i < 8; i++) {
        var pathOnly = probe.split('?')[0].split('#')[0].split('&')[0].replace(/\/+$/, '');
        if (pathOnly === '/login' || /\/login$/.test(pathOnly)) return './';
        var decoded;
        try { decoded = decodeURIComponent(probe); } catch (_) { stabilized = true; break; }
        if (decoded === probe) { stabilized = true; break; }
        probe = decoded;
      }
      // If still decoding at the cap (pathologically deep encoding), fail closed.
      if (!stabilized) return './';
      return raw;
    } catch (_) { return './'; }
  }

  // Sentry per-user credential fields. Absent on shared-password deployments,
  // where every branch below is skipped and behaviour is unchanged.
  var userEl = document.getElementById('sentry-username');
  var userPwEl = document.getElementById('sentry-password');
  var forgotBtn = document.getElementById('forgot-password');

  async function doLogin(e) {
    e.preventDefault();
    var pw = input ? input.value : '';
    hideErr();
    // Sentry multi-user login: if an enrollment-code field is present and
    // filled, send it so the server redeems a per-user Gateway token. The
    // server ignores it unless the deployment is in the sentry dialect, so this
    // is inert for shared-password deployments.
    var payload = { password: pw };
    var enrollEl = document.getElementById('enroll-code');
    if (enrollEl && enrollEl.value.trim()) {
      payload.enrollment_code = enrollEl.value.trim();
      payload.device_name = (navigator.userAgent || 'Sentry Web').slice(0, 80);
    } else if (userEl && userEl.value.trim()) {
      // Username + password: the normal Sentry sign-in. Sent instead of, not
      // as well as, the shared password — the server routes on the username.
      payload.username = userEl.value.trim();
      payload.password = userPwEl ? userPwEl.value : '';
      payload.device_name = (navigator.userAgent || 'Sentry Web').slice(0, 80);
    }
    try {
      var res = await fetch('api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });
      var data = {};
      try { data = await res.json(); } catch (_) {}
      if (res.ok && data.ok) {
        // The operator has seen this password, so it is a handover credential,
        // not the user's own. Change it before going anywhere.
        if (data.must_change) { showChangeForm(); return; }
        window.location.href = _safeNextPath();
      } else {
        showErr(data.error || invalidPw);
      }
    } catch (ex) {
      showErr(connFailed);
    }
  }

  // Forced password change. Rendered client-side only after a successful
  // sign-in reported must_change, so it can never be reached without a session.
  function showChangeForm() {
    hideErr();
    [userEl, userPwEl, input, forgotBtn, document.getElementById('enroll-code'),
     document.getElementById('passkey-login'), document.getElementById('oidc-login')]
      .forEach(function (el) { if (el) el.style.display = 'none'; });
    var submit = form.querySelector('button[type="submit"]');
    if (submit) submit.style.display = 'none';

    var current = document.createElement('input');
    current.type = 'password';
    current.id = 'change-current';
    current.placeholder = 'Current password';
    current.autocomplete = 'current-password';
    var next = document.createElement('input');
    next.type = 'password';
    next.id = 'change-new';
    next.placeholder = 'New password (12+ characters)';
    next.autocomplete = 'new-password';
    var confirm = document.createElement('input');
    confirm.type = 'password';
    confirm.id = 'change-confirm';
    confirm.placeholder = 'Repeat new password';
    confirm.autocomplete = 'new-password';
    var go = document.createElement('button');
    go.type = 'button';
    go.id = 'change-submit';
    go.textContent = 'Set new password';

    var note = document.createElement('p');
    note.className = 'sub';
    note.style.marginTop = '4px';
    note.textContent = 'Choose your own password before continuing.';

    form.appendChild(note);
    form.appendChild(current);
    form.appendChild(next);
    form.appendChild(confirm);
    form.appendChild(go);
    current.focus();

    async function submitChange() {
      hideErr();
      if (next.value.length < 12) {
        showErr('New password must be at least 12 characters.');
        return;
      }
      if (next.value !== confirm.value) {
        showErr('The two new passwords do not match.');
        return;
      }
      go.disabled = true;
      try {
        var res = await fetch('api/auth/password/change', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_password: current.value,
            new_password: next.value,
          }),
          credentials: 'include',
        });
        var data = {};
        try { data = await res.json(); } catch (_) {}
        if (res.ok && data.ok) {
          window.location.href = _safeNextPath();
        } else {
          showErr(data.error || 'Could not change the password.');
        }
      } catch (ex) {
        showErr(connFailed);
      } finally {
        go.disabled = false;
      }
    }

    go.addEventListener('click', submitChange);
    [current, next, confirm].forEach(function (el) {
      el.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); submitChange(); }
      });
    });
  }

  // Lost-password recovery is authorized in Server Control, then completed
  // here so the new password never passes through the operations portal.
  function showRecoveryForm() {
    hideErr();
    var original = Array.prototype.slice.call(form.children);
    original.forEach(function (el) { el.style.display = 'none'; });

    var note = document.createElement('p');
    note.className = 'recovery-note';
    note.textContent = 'In Server Control, open Settings → Sentry account recovery and create a one-time code. Then set your new password here.';
    // The owner's desktop shell also forwards the loopback-only operations
    // portal. Public/PWA clients cannot reach that private URL and instead ask
    // their operator for a code.
    var localHost = window.location.hostname === '[::1]' || window.location.hostname === '::1';
    if (localHost) {
      var controlLink = document.createElement('a');
      controlLink.href = 'http://[::1]:17443/server-control/#settings';
      controlLink.target = '_blank';
      controlLink.rel = 'noreferrer';
      controlLink.textContent = 'Open Server Control';
      note.appendChild(document.createElement('br'));
      note.appendChild(controlLink);
    }
    var recoveryUser = document.createElement('input');
    recoveryUser.type = 'text';
    recoveryUser.id = 'recovery-username';
    recoveryUser.placeholder = 'Username';
    recoveryUser.autocomplete = 'username';
    recoveryUser.spellcheck = false;
    recoveryUser.value = userEl ? userEl.value.trim() : '';
    var recoveryCode = document.createElement('input');
    recoveryCode.type = 'text';
    recoveryCode.id = 'recovery-code';
    recoveryCode.placeholder = 'One-time recovery code';
    recoveryCode.autocomplete = 'one-time-code';
    recoveryCode.spellcheck = false;
    var next = document.createElement('input');
    next.type = 'password';
    next.id = 'recovery-new';
    next.placeholder = 'New password (12+ characters)';
    next.autocomplete = 'new-password';
    var confirm = document.createElement('input');
    confirm.type = 'password';
    confirm.id = 'recovery-confirm';
    confirm.placeholder = 'Repeat new password';
    confirm.autocomplete = 'new-password';
    // Second door: an identity provider the operator can still get into. Shown
    // only when the Gateway reports one is configured, so a deployment without
    // one looks exactly as it did before.
    var providerBtn = document.createElement('button');
    providerBtn.type = 'button';
    providerBtn.className = 'button button--text';
    providerBtn.style.display = 'none';
    providerBtn.textContent = 'Reset with your identity provider';
    providerBtn.addEventListener('click', function () {
      providerBtn.disabled = true;
      window.location.assign('api/auth/sentry/oidc/start');
    });
    fetch('api/auth/sentry/oidc/status', { credentials: 'include' })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !data.available) return;
        providerBtn.textContent = 'Reset with ' + (data.display_name || 'your identity provider');
        providerBtn.style.display = '';
      })
      .catch(function () { /* No provider, no button. */ });

    var actions = document.createElement('div');
    actions.className = 'recovery-actions';
    var back = document.createElement('button');
    back.type = 'button';
    back.className = 'forgot-password';
    back.textContent = 'Back to sign in';
    var go = document.createElement('button');
    go.type = 'button';
    go.id = 'recovery-submit';
    go.textContent = 'Reset password';
    actions.appendChild(back);
    actions.appendChild(go);

    [note, recoveryUser, recoveryCode, next, confirm, providerBtn, actions]
      .forEach(function (el) { form.appendChild(el); });
    (recoveryUser.value ? recoveryCode : recoveryUser).focus();

    function restoreSignIn() {
      [note, recoveryUser, recoveryCode, next, confirm, providerBtn, actions]
        .forEach(function (el) { el.remove(); });
      original.forEach(function (el) { el.style.display = ''; });
      if (userEl) userEl.focus();
    }

    async function submitRecovery() {
      hideErr();
      if (!recoveryUser.value.trim() || !recoveryCode.value.trim()) {
        showErr('Enter your username and the one-time code from Server Control.');
        return;
      }
      if (next.value.length < 12) {
        showErr('New password must be at least 12 characters.');
        return;
      }
      if (next.value !== confirm.value) {
        showErr('The two new passwords do not match.');
        return;
      }
      go.disabled = true;
      try {
        var res = await fetch('api/auth/password/recover', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: recoveryUser.value.trim(),
            code: recoveryCode.value.trim(),
            new_password: next.value,
          }),
          credentials: 'include',
        });
        var data = {};
        try { data = await res.json(); } catch (_) {}
        if (!res.ok || !data.ok) {
          showErr(data.error || 'Could not reset the password.');
          return;
        }
        if (userEl) userEl.value = recoveryUser.value.trim();
        if (userPwEl) userPwEl.value = '';
        restoreSignIn();
        showErr('Password reset. Sign in with your new password.');
      } catch (ex) {
        showErr(connFailed);
      } finally {
        go.disabled = false;
      }
    }

    back.addEventListener('click', restoreSignIn);
    go.addEventListener('click', submitRecovery);
    [recoveryUser, recoveryCode, next, confirm].forEach(function (el) {
      el.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); submitRecovery(); }
      });
    });
  }

  // Returned from the identity provider. The recovery code the Gateway minted
  // is held server-side against an HttpOnly ticket cookie -- it deliberately
  // never reaches this script -- so all this form collects is the new password.
  function showProviderRecoveryForm() {
    hideErr();
    var original = Array.prototype.slice.call(form.children);
    original.forEach(function (el) { el.style.display = 'none'; });

    var note = document.createElement('p');
    note.className = 'recovery-note';
    note.textContent = 'Your identity provider verified you. Choose a new password.';

    var next = document.createElement('input');
    next.type = 'password';
    next.id = 'provider-recovery-new';
    next.placeholder = 'New password (12+ characters)';
    next.autocomplete = 'new-password';
    var confirm = document.createElement('input');
    confirm.type = 'password';
    confirm.id = 'provider-recovery-confirm';
    confirm.placeholder = 'Repeat new password';
    confirm.autocomplete = 'new-password';

    var actions = document.createElement('div');
    actions.className = 'recovery-actions';
    var back = document.createElement('button');
    back.type = 'button';
    back.className = 'forgot-password';
    back.textContent = 'Back to sign in';
    var go = document.createElement('button');
    go.type = 'button';
    go.id = 'provider-recovery-submit';
    go.textContent = 'Reset password';
    actions.appendChild(back);
    actions.appendChild(go);

    [note, next, confirm, actions].forEach(function (el) { form.appendChild(el); });
    next.focus();

    function restoreSignIn() {
      [note, next, confirm, actions].forEach(function (el) { el.remove(); });
      original.forEach(function (el) { el.style.display = ''; });
      if (userEl) userEl.focus();
    }

    async function submitProviderRecovery() {
      hideErr();
      if (next.value.length < 12) {
        showErr('New password must be at least 12 characters.');
        return;
      }
      if (next.value !== confirm.value) {
        showErr('The two new passwords do not match.');
        return;
      }
      go.disabled = true;
      try {
        var res = await fetch('api/auth/sentry/oidc/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_password: next.value }),
          credentials: 'include',
        });
        var data = {};
        try { data = await res.json(); } catch (_) {}
        if (!res.ok || !data.ok) {
          showErr(data.error || 'Could not reset the password.');
          return;
        }
        if (userEl && data.username) userEl.value = data.username;
        if (userPwEl) userPwEl.value = '';
        restoreSignIn();
        showErr('Password reset. Sign in with your new password.');
      } catch (ex) {
        showErr(connFailed);
      } finally {
        go.disabled = false;
      }
    }

    back.addEventListener('click', restoreSignIn);
    go.addEventListener('click', submitProviderRecovery);
    [next, confirm].forEach(function (el) {
      el.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); submitProviderRecovery(); }
      });
    });
  }

  form.addEventListener('submit', doLogin);
  if (forgotBtn) forgotBtn.addEventListener('click', showRecoveryForm);

  // The provider callback is a server-side redirect, so it reports its outcome
  // through the fragment. Read it once and strip it, so a refresh does not
  // re-enter a recovery whose ticket has already been spent.
  (function handleProviderReturn() {
    var hash = window.location.hash;
    if (hash !== '#recovery-provider' && hash !== '#recovery-provider-failed') return;
    history.replaceState(null, '', window.location.pathname + window.location.search);
    if (hash === '#recovery-provider') {
      showProviderRecoveryForm();
    } else {
      showRecoveryForm();
      showErr('That sign-in could not be verified for recovery. Use a Server Control code instead.');
    }
  })();

  function b64uToBytes(s) {
    s = String(s || '').replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64u(buf) {
    var bytes = new Uint8Array(buf);
    var bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  async function doPasskeyLogin() {
    if (!window.PublicKeyCredential || !navigator.credentials) return;
    hideErr();
    try {
      passkeyBtn.disabled = true;
      var optRes = await fetch('api/auth/passkey/options', { method: 'POST', body: '{}', credentials: 'include' });
      var optData = await optRes.json();
      if (!optRes.ok || !optData.publicKey) throw new Error(optData.error || 'Passkey unavailable');
      var pk = optData.publicKey;
      pk.challenge = b64uToBytes(pk.challenge);
      if (Array.isArray(pk.allowCredentials)) {
        pk.allowCredentials = pk.allowCredentials.map(function (c) { return Object.assign({}, c, { id: b64uToBytes(c.id) }); });
      }
      var cred = await navigator.credentials.get({ publicKey: pk });
      if (!cred) throw new Error('Passkey sign-in cancelled');
      var payload = {
        id: cred.id,
        rawId: bytesToB64u(cred.rawId),
        type: cred.type,
        response: {
          authenticatorData: bytesToB64u(cred.response.authenticatorData),
          clientDataJSON: bytesToB64u(cred.response.clientDataJSON),
          signature: bytesToB64u(cred.response.signature),
          userHandle: cred.response.userHandle ? bytesToB64u(cred.response.userHandle) : null,
        },
      };
      var res = await fetch('api/auth/passkey/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), credentials: 'include',
      });
      var data = {};
      try { data = await res.json(); } catch (_) {}
      if (res.ok && data.ok) window.location.href = _safeNextPath();
      else showErr(data.error || invalidPw);
    } catch (ex) {
      showErr(ex && ex.message ? ex.message : connFailed);
    } finally {
      passkeyBtn.disabled = false;
    }
  }

  if (passkeyBtn && window.PublicKeyCredential && navigator.credentials) {
    fetch('api/auth/status', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s && s.passkeys_enabled) passkeyBtn.style.display = 'block'; })
      .catch(function () {});
    passkeyBtn.addEventListener('click', doPasskeyLogin);
  }

  // Enter-to-submit on whichever field the page actually rendered.
  [input, userEl, userPwEl, document.getElementById('enroll-code')].forEach(function (el) {
    if (!el) return;
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        doLogin(e);
      }
    });
  });

  // On page load, probe the server so we can distinguish "can't reach server"
  // (Tailscale off, wrong network) from "session expired / need to log in".
  // Uses /health — public for WebUI auth, but deployment access proxies may
  // require same-origin cookies before the request reaches WebUI.
  // If unreachable, retries every 3 s and auto-reloads once the server is back.
  (function checkConnectivity() {
    var retryTimer = null;

    function setFormDisabled(disabled) {
      [input, userEl, userPwEl, document.getElementById('enroll-code')]
        .forEach(function (el) { if (el) el.disabled = disabled; });
      var btn = form.querySelector('button');
      if (btn) btn.disabled = disabled;
    }

    function probe() {
      fetch('health', { method: 'GET', credentials: 'same-origin' })
        .then(function (r) {
          if (r.ok) {
            // Server is reachable — if we were in retry mode, reload so the
            // page reflects the correct auth state (expired session, etc.).
            if (retryTimer !== null) {
              clearInterval(retryTimer);
              retryTimer = null;
              window.location.reload();
            }
          } else {
            showErr(connFailed + ' (server error ' + r.status + ')');
          }
        })
        .catch(function () {
          showErr('Cannot reach server — check your VPN / Tailscale connection.');
          setFormDisabled(true);
          // Keep retrying so the page auto-recovers once the network is back.
          if (retryTimer === null) {
            retryTimer = setInterval(probe, 3000);
          }
        });
    }

    probe();
  })();
});

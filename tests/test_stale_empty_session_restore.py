"""Regression tests for stale empty sessions after a WebUI restart.

When a saved session ID returns 404 (e.g. the session was deleted from another
browser, or a state DB rotation removed it), the prior behavior was to show
\"Session not available in web UI.\" and stick there forever — the saved
localStorage entry never got cleared, so every reload reproduced the broken
state.

These tests lock in:
  1. ``api()`` attaches HTTP context (``.status``, ``.statusText``, ``.body``)
     to thrown errors so callers can branch on status without re-parsing text.
  2. ``loadSession()`` clears the stale ``hermes-webui-session`` key on a 404
     and strips the ``/session/<id>`` URL, then recovers immediately to a fresh
     composer when the active session vanished (#2798, #2782).
  3. Clicking a different dead row restores the still-current conversation
     instead of replacing it with a permanent error pane.
  4. A boot-time stale-session fallback also removes the temporary
     "Loading conversation..." placeholder before showing the fresh composer.
  5. The server 404s a deleted *WebUI* session on ``GET /api/session`` instead
     of synthesising a read-only CLI stub, so ``GET`` and the ``POST`` write
     paths agree on whether a session exists and the client can self-heal
     (#2782). A genuine CLI-origin session still returns 200 after its sidecar
     is gone.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse
import json
import re
import shutil
import subprocess

import pytest


REPO = Path(__file__).parent.parent
WORKSPACE_JS = (REPO / "static" / "workspace.js").read_text(encoding="utf-8")
SESSIONS_JS = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")
MESSAGES_JS = (REPO / "static" / "messages.js").read_text(encoding="utf-8")
BOOT_JS = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _api_body() -> str:
    m = re.search(r"async function api\(path,opts=.*?\n\}", WORKSPACE_JS, re.DOTALL)
    assert m, "api() function must exist in workspace.js"
    return m.group(0)


def _load_session_error_block() -> str:
    start = SESSIONS_JS.find("data = await api(`/api/session?")
    assert start > 0, "loadSession metadata request not found"
    catch_idx = SESSIONS_JS.find("} catch(e) {", start)
    assert catch_idx > start, "loadSession metadata catch block not found"
    end = SESSIONS_JS.find("\n  // Guard: api()", catch_idx)
    assert end > catch_idx, "loadSession metadata catch terminator not found"
    return SESSIONS_JS[catch_idx:end]


def _load_session_404_block() -> str:
    """The body of the `if(e.status===404){ ... }` arm only."""
    block = _load_session_error_block()
    start = block.find("if(e.status===404){")
    assert start >= 0, "loadSession 404 arm not found"
    end = block.find("const _msgInner", start)
    assert end > start, "loadSession 404 arm terminator not found"
    return block[start:end]


def _send_catch_block() -> str:
    """The catch(e) body of send() after POST /api/chat/start."""
    start = MESSAGES_JS.find("const startData=await api('/api/chat/start'")
    assert start > 0, "send() /api/chat/start call not found"
    catch_idx = MESSAGES_JS.find("}catch(e){", start)
    assert catch_idx > start, "send() catch block not found"
    # Stop at the conflictActiveStream marker; the 404 branch must precede it.
    end = MESSAGES_JS.find("const conflictActiveStream", catch_idx)
    assert end > catch_idx, "send() catch conflictActiveStream marker not found"
    return MESSAGES_JS[catch_idx:end]


def _boot_saved_session_catch_block() -> str:
    start = BOOT_JS.find("await loadSession(saved, {preserveActiveInput:true})")
    assert start > 0, "boot saved-session restore not found"
    catch_idx = BOOT_JS.find("catch(e){", start)
    assert catch_idx > start, "boot saved-session restore catch not found"
    end = BOOT_JS.find("// no saved session", catch_idx)
    assert end > catch_idx, "boot saved-session fallback terminator not found"
    return BOOT_JS[catch_idx:end]


def test_api_http_errors_preserve_response_status():
    """Callers must be able to distinguish stale-session 404s from generic failures."""
    body = _api_body()
    assert re.search(r"\w+\.status\s*=\s*res\.status", body), (
        "api() must attach res.status to thrown HTTP errors"
    )
    assert re.search(r"\w+\.statusText\s*=\s*res\.statusText", body), (
        "api() must attach res.statusText to thrown HTTP errors"
    )
    assert re.search(r"\w+\.body\s*=\s*text", body), (
        "api() must attach the raw error body to thrown HTTP errors"
    )


def test_load_session_clears_saved_stale_404_and_rethrows_to_boot():
    """A missing saved session should be removed and let boot show the empty state."""
    block = _load_session_error_block()
    assert "e.status===404" in block, "loadSession must keep a 404-specific branch"
    assert "localStorage.removeItem('hermes-webui-session')" in block, (
        "loadSession must clear stale saved session IDs on 404"
    )
    assert "history.replaceState" in block, (
        "loadSession must strip stale /session/{id} from the URL so a refresh "
        "doesn't re-trigger the 404 loop"
    )
    assert "_loadingSessionId = null" in block, (
        "loadSession must clear the in-flight load marker on 404"
    )
    # Boot-time (!currentSid) rethrow so boot falls through to the empty state.
    assert "!currentSid" in block, (
        "loadSession must keep the !currentSid gate around the boot-time rethrow"
    )
    assert re.search(r"throw\s+e", block), (
        "loadSession must rethrow the stale saved-session 404 so boot can fall "
        "through to the no-session empty state"
    )


def test_load_session_404_self_heal_gated_to_active_or_boot():
    """#2782: the localStorage clear + URL strip self-heal runs only when the
    404'd id is the one being activated, gated on (!currentSid || currentSid===sid):
    a boot-time restore (#2798) or a reload of the *current* session whose sidecar
    was deleted. A click into a *different* dead session preserves the live
    session's saved id and URL. Only the rethrow stays gated on !currentSid."""
    arm = _load_session_404_block()
    self_heal = "if(!currentSid || currentSid===sid)"
    assert self_heal in arm, (
        "self-heal must be gated to boot or the active session, not unconditional"
    )
    heal_idx = arm.find(self_heal)
    clear_idx = arm.find("localStorage.removeItem('hermes-webui-session')")
    strip_idx = arm.find("history.replaceState")
    assert clear_idx > heal_idx, "localStorage clear must run inside the self-heal gate"
    assert strip_idx > heal_idx, "URL strip must run inside the self-heal gate"
    # The boot-time rethrow stays nested on !currentSid, inside the self-heal gate.
    rethrow_gate_idx = arm.find("if(!currentSid)")
    assert rethrow_gate_idx > heal_idx, "the !currentSid rethrow gate must remain"
    assert re.search(r"throw\s+e", arm[rethrow_gate_idx:]), (
        "the !currentSid gate must still contain the boot-time rethrow"
    )


def test_active_session_404_recovers_to_fresh_composer_immediately():
    """A current session removed server-side must not leave the running app on
    the old permanent "Session not available" pane until a manual refresh."""
    arm = _load_session_404_block()
    active_gate = "if(!currentSid || currentSid===sid)"
    gate_idx = arm.find(active_gate)
    reset_idx = arm.find("_resetUnavailableActiveSession(sid)")
    assert reset_idx > gate_idx, "active-session 404 must reset to a usable composer"
    assert re.search(r"_resetUnavailableActiveSession\(sid\);\s*.*?return\s*;", arm[reset_idx:], re.DOTALL), (
        "active-session recovery must return before the generic failed-load pane"
    )
    helper_start = SESSIONS_JS.find("function _resetUnavailableActiveSession(sid)")
    helper_end = SESSIONS_JS.find("\n}\n", helper_start)
    assert helper_start > 0 and helper_end > helper_start, "recovery helper must exist"
    helper = SESSIONS_JS[helper_start:helper_end]
    for required in (
        "S.session=null",
        "S.messages=[]",
        "S.entries=[]",
        "S.toolCalls=[]",
        "S.activeStreamId=null",
        "S.busy=false",
        "inner.innerHTML=''",
        "empty.style.display=''",
        "renderSessionList()",
    ):
        assert required in helper, f"fresh-composer recovery must include {required}"
    assert "S.pendingFiles=[]" not in helper, "recovery must preserve pending attachments"


def test_different_dead_session_404_restores_current_conversation():
    """A stale sidebar row must bounce back to the healthy session that was
    already open, without clearing its saved URL/localStorage identity."""
    arm = _load_session_404_block()
    restore = "return loadSession(currentSid,{"
    assert restore in arm, "failed sidebar switch must reload the current session"
    restore_block = arm[arm.find(restore):]
    assert "force:true" in restore_block
    assert "preserveActiveInput:true" in restore_block
    assert "skipExtHooks:true" in restore_block
    assert "Session not available in web UI." not in arm, (
        "a 404 must no longer replace the transcript with a permanent error pane"
    )


def test_boot_stale_session_clears_loading_placeholder():
    """The saved-session 404 fallback must not leave its loading row visible
    over the fresh composer after loadSession rethrows to boot."""
    block = _boot_saved_session_catch_block()
    clear_saved_idx = block.find("localStorage.removeItem('hermes-webui-session')")
    find_placeholder_idx = block.find("$('msgInner')")
    clear_placeholder_idx = block.find("innerHTML=''", find_placeholder_idx)
    assert clear_saved_idx >= 0
    assert find_placeholder_idx > clear_saved_idx
    assert clear_placeholder_idx > find_placeholder_idx


@pytest.mark.skipif(NODE is None, reason="node is required for session recovery behavior")
def test_active_session_404_behavior_preserves_draft_and_opens_fresh_composer():
    """Execute the real loadSession() 404 path and recovery helper together.

    This catches runtime-only failures that source assertions cannot, while the
    stubs model only browser services outside the behavior under test.
    """
    script = f"""
const src = {SESSIONS_JS!r};
function extractFunc(name) {{
  const re = new RegExp('(?:async\\\\s+)?function\\\\s+' + name + '\\\\s*\\\\(');
  const start = src.search(re);
  if (start < 0) throw new Error(name + ' not found');
  let i = src.indexOf('{{', start), depth = 1; i++;
  while (depth > 0 && i < src.length) {{
    if (src[i] === '{{') depth++;
    else if (src[i] === '}}') depth--;
    i++;
  }}
  return src.slice(start, i);
}}
const nodes = {{
  msg: {{ value:'unsent draft' }},
  msgInner: {{ innerHTML:'old transcript' }},
  emptyState: {{ style:{{display:'none'}} }},
  topbarTitle: {{ textContent:'Old chat' }},
  topbarMeta: {{ textContent:'3 messages' }},
}};
function $(id) {{ return nodes[id] || null; }}
var S = {{
  session:{{session_id:'dead-active', title:'Old chat'}},
  messages:[{{role:'user',content:'old'}}], entries:[{{kind:'old'}}],
  toolCalls:[{{id:'tool'}}], busy:true, activeStreamId:'stream-1',
  pendingFiles:[{{name:'keep-me.txt'}}], _pendingSessionToolsets:['old'],
}};
var INFLIGHT = {{'dead-active':{{messages:[]}}}};
var _loadSessionGeneration=0, _loadingSessionId=null;
var _messagesTruncated=true, _oldestIdx=4, _loadingOlder=true;
var _pendingCarryForwardSnapshot=null, _yoloEnabled=true;
var _messageUserUnpinned=false, _scrollPinned=true;
var clearedInflight=[], calls=[], toasts=[];
var localStorage = {{
  data:{{'hermes-webui-session':'dead-active'}},
  removeItem(k){{ delete this.data[k]; }},
  getItem(k){{ return this.data[k] || null; }},
}};
var history = {{ path:'/session/dead-active', replaceState(_a,_b,path){{ this.path=path; }} }};
var window = {{ _clearPendingSelections(){{ calls.push('clearSelections'); }} }};
function _appRootPath(){{ return '/'; }}
function _rearmActiveSessionStream(){{}}
function stopApprovalPolling(){{}} function hideApprovalCard(){{}}
function stopSessionStream(){{}} function _updateYoloPill(){{}}
function stopClarifyPolling(){{}} function hideClarifyCard(){{}}
function clearCompressionUi(){{}} function _captureSameSessionForceReloadHint(){{}}
function _clearSameSessionForceReloadHint(){{ calls.push('clearReloadHint'); }}
function _sessionProfileMismatchFromError(){{ return null; }}
function clearInflightState(sid){{ clearedInflight.push(sid); }}
function clearOptimisticSessionStreaming(sid){{ calls.push('clearStreaming:'+sid); }}
function clearLiveToolCards(){{ calls.push('clearTools'); }}
function removeThinking(){{ calls.push('removeThinking'); }}
function _hydrateTodosFromSession(value){{ calls.push(value===null?'clearTodos':'hydrateTodos'); }}
function updateSendBtn(){{ calls.push('sendReady'); }}
function setComposerStatus(value){{ calls.push('composer:'+value); }}
function updateQueueBadge(){{ calls.push('queueReady'); }}
function assistantDisplayName(){{ return 'Sentry'; }}
function syncTopbar(){{ calls.push('topbar'); }}
function syncWorkspacePanelState(){{ calls.push('workspace'); }}
async function renderSessionList(){{ calls.push('sessions'); }}
function showToast(message){{ toasts.push(message); }}
async function api(){{ const error=new Error('missing'); error.status=404; throw error; }}
globalThis._resetUnavailableActiveSession=(0,eval)('('+extractFunc('_resetUnavailableActiveSession')+')');
globalThis.loadSession=(0,eval)('('+extractFunc('loadSession')+')');
(async()=>{{
  await loadSession('dead-active',{{force:true,skipLineageResolve:true,skipExtHooks:true}});
  await Promise.resolve();
  console.log(JSON.stringify({{
    session:S.session, messages:S.messages, entries:S.entries, toolCalls:S.toolCalls,
    busy:S.busy, activeStreamId:S.activeStreamId, pendingFiles:S.pendingFiles,
    pendingToolsets:S._pendingSessionToolsets, stored:localStorage.getItem('hermes-webui-session'),
    path:history.path, inner:nodes.msgInner.innerHTML, empty:nodes.emptyState.style.display,
    title:nodes.topbarTitle.textContent, meta:nodes.topbarMeta.textContent,
    input:nodes.msg.value, inflight:INFLIGHT['dead-active'] || null,
    clearedInflight, calls, toasts,
  }}));
}})().catch(error=>{{ console.error(error); process.exitCode=1; }});
"""
    result = subprocess.run(
        [NODE],
        input=script,
        cwd=str(REPO),
        capture_output=True,
        encoding="utf-8",
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["session"] is None
    assert state["messages"] == []
    assert state["entries"] == []
    assert state["toolCalls"] == []
    assert state["busy"] is False
    assert state["activeStreamId"] is None
    assert state["pendingFiles"] == [{"name": "keep-me.txt"}]
    assert state["pendingToolsets"] is None
    assert state["stored"] is None
    assert state["path"] == "/"
    assert state["inner"] == ""
    assert state["empty"] == ""
    assert state["title"] == "Sentry"
    assert state["meta"] == "Start a new conversation"
    assert state["input"] == "unsent draft"
    assert state["inflight"] is None
    assert state["clearedInflight"] == ["dead-active"]
    assert "sessions" in state["calls"]
    assert state["toasts"] == [
        "That session is no longer available. Start a new conversation."
    ]


def test_send_chat_start_404_self_heals_instead_of_error_bubble():
    """#2782: POST /api/chat/start 404 (deleted sidecar) must clear localStorage,
    strip the URL, and reset to empty state, before the generic error path that
    would otherwise push an "Error:" bubble into the chat."""
    block = _send_catch_block()
    assert "e.status===404" in block, (
        "send() must branch on a 404 from /api/chat/start before the generic path"
    )
    assert "localStorage.removeItem('hermes-webui-session')" in block, (
        "send() 404 branch must clear the saved session key"
    )
    assert "history.replaceState" in block, (
        "send() 404 branch must strip the stale /session/<id> URL"
    )
    assert re.search(r"return\s*;", block), (
        "send() 404 branch must return before pushing an error bubble"
    )
    # The error bubble (`**Error:**`) lives after the conflictActiveStream
    # marker, so confirming the 404 branch + return precede that marker is
    # enough to prove no bubble is appended on a 404.
    assert "**Error:**" not in block, (
        "the 404 self-heal branch must run before the error-bubble path"
    )


# ── Server: GET /api/session 404s a deleted WebUI session (#2782) ──


def _invoke_api_session_keyerror(*, index_json, cli_messages):
    """Drive GET /api/session with get_session() raising KeyError (the deleted-
    session fallthrough) and a patched _index.json. Returns the captured status.
    """
    import api.routes as routes

    captured = {}

    def fake_j(_handler, data, status=200, extra_headers=None):
        captured["data"] = data
        captured["status"] = status
        return data

    def fake_bad(_handler, msg, status=400):
        captured["data"] = {"error": msg}
        captured["status"] = status
        return {"error": msg}

    class _FakeIndexFile:
        def exists(self):
            return index_json is not None

        def read_text(self, encoding="utf-8"):
            return index_json

        def read_bytes(self):
            # The index reader now parses raw bytes (json.loads decodes UTF-8 in
            # one pass); model that so this fake matches the real Path interface.
            return None if index_json is None else index_json.encode("utf-8")

    parsed = urlparse("/api/session?session_id=gone_001&messages=0&resolve_model=0")
    with patch("api.routes.get_session", side_effect=KeyError("gone_001")), \
         patch("api.routes.SESSION_INDEX_FILE", _FakeIndexFile()), \
         patch("api.routes._lookup_cli_session_metadata", return_value={}), \
         patch("api.routes.get_cli_session_messages", return_value=cli_messages), \
         patch("api.routes.j", side_effect=fake_j), \
         patch("api.routes.bad", side_effect=fake_bad):
        routes.handle_get(SimpleNamespace(), parsed)
    return captured


def test_get_session_404s_deleted_webui_session():
    """A WebUI session in _index.json (no/webui source) whose sidecar is gone
    must 404 on GET, not synthesise a read-only CLI stub, so the client can
    self-heal and POST/GET agree (#2782)."""
    index = '[{"session_id": "gone_001", "source_tag": null, "raw_source": null, "session_source": null}]'
    captured = _invoke_api_session_keyerror(
        index_json=index,
        cli_messages=[{"role": "user", "content": "hi", "timestamp": 1}],
    )
    assert captured["status"] == 404, (
        "a deleted WebUI session must return 404, not a 200 CLI stub"
    )


def test_get_session_404s_deleted_fork_session():
    """A forked WebUI session is stamped session_source='fork' (the /api/session/
    branch handler); its deleted sidecar must 404 too, not fall through to a 200
    CLI stub, since a fork is WebUI-origin and bricks identically (#2782)."""
    index = '[{"session_id": "gone_001", "source_tag": null, "raw_source": null, "session_source": "fork"}]'
    captured = _invoke_api_session_keyerror(
        index_json=index,
        cli_messages=[{"role": "user", "content": "hi", "timestamp": 1}],
    )
    assert captured["status"] == 404, (
        "a deleted fork (WebUI-origin) session must return 404, not a 200 CLI stub"
    )


def test_get_session_keeps_200_for_genuine_cli_session():
    """A genuine CLI-origin session (source_tag set to a non-webui value in the
    index) still returns the 200 CLI stub after its sidecar is gone (#2782)."""
    index = '[{"session_id": "gone_001", "source_tag": "claude-code", "raw_source": "claude-code", "session_source": "cli"}]'
    captured = _invoke_api_session_keyerror(
        index_json=index,
        cli_messages=[{"role": "user", "content": "hi", "timestamp": 1}],
    )
    assert captured["status"] == 200, (
        "a genuine CLI session must keep the 200 CLI-stub path"
    )
    assert captured["data"]["session"]["session_id"] == "gone_001"


def test_get_session_keeps_200_when_id_absent_from_index():
    """An id absent from _index.json was never a WebUI session, so the existing
    CLI-store 200 path is preserved (no false-positive 404)."""
    captured = _invoke_api_session_keyerror(
        index_json='[{"session_id": "other_999", "source_tag": null}]',
        cli_messages=[{"role": "user", "content": "hi", "timestamp": 1}],
    )
    assert captured["status"] == 200, (
        "an id not in the index must keep the CLI-store 200 path"
    )


def test_get_session_keeps_200_for_legacy_cli_row_with_blank_source():
    """Regression (#3501 review, Codex CORE catch): a legacy CLI/imported session
    can be present in _index.json with is_cli_session:true but BLANK source fields
    (source_tag/raw_source/session_source all null). The earlier
    `source_tag or raw_source or session_source or ""` collapse defaulted blank to
    WebUI and would WRONGLY 404 it. Per-field classification must treat a blank-
    source row marked is_cli_session (or read_only) as a genuine CLI session and
    keep the 200 stub."""
    index = (
        '[{"session_id": "gone_001", "source_tag": null, "raw_source": null, '
        '"session_source": null, "is_cli_session": true}]'
    )
    captured = _invoke_api_session_keyerror(
        index_json=index,
        cli_messages=[{"role": "user", "content": "hi", "timestamp": 1}],
    )
    assert captured["status"] == 200, (
        "a legacy CLI row (is_cli_session:true, blank source) must keep the 200 "
        "CLI-stub path, not be 404'd as a deleted WebUI session"
    )


def test_get_session_keeps_200_for_read_only_row_with_blank_source():
    """A read-only imported session with blank source fields is also CLI-origin
    and must keep the 200 stub (companion to the is_cli_session case)."""
    index = (
        '[{"session_id": "gone_001", "source_tag": null, "raw_source": null, '
        '"session_source": null, "read_only": true}]'
    )
    captured = _invoke_api_session_keyerror(
        index_json=index,
        cli_messages=[{"role": "user", "content": "hi", "timestamp": 1}],
    )
    assert captured["status"] == 200, (
        "a read-only imported row (blank source) must keep the 200 CLI-stub path"
    )

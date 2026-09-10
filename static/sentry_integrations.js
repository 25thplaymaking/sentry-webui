/* Sentry's linked-session, target, repository, and IDE surface.
 *
 * Local operations stay behind the authenticated Gateway. The browser only
 * handles opaque node/workspace/session identifiers and bounded display data.
 */
(function(){
'use strict';

const state={
  status:null,
  sessions:[],
  selectedSession:null,
  providerSnapshot:null,
  workspaceSnapshot:null,
  watching:false,
  watchOrderId:null,
  refreshPromise:null,
  syncStarted:false,
};

const byId=(id)=>document.getElementById(id);
const isSentry=()=>document.body&&document.body.dataset.sentryProduct==='true';
const selectedTarget=()=>{
  const persisted=typeof S!=='undefined'&&S.session&&S.session.sentry_target;
  if(persisted&&typeof persisted==='object'&&(persisted.kind==='workspace'||persisted.kind==='service')) return persisted;
  const pending=typeof S!=='undefined'&&S._pendingSentryTarget;
  return pending&&typeof pending==='object'&&(pending.kind==='workspace'||pending.kind==='service')?pending:null;
};
const onlineNodes=()=>Array.isArray(state.status&&state.status.nodes)
  ?state.status.nodes.filter(node=>node&&node.online):[];
const integrationWorkspaces=()=>onlineNodes().flatMap(node=>(Array.isArray(node.workspaces)?node.workspaces:[])
  .filter(ws=>Array.isArray(ws.harnesses)&&ws.harnesses.includes('integrations'))
  .map(ws=>({...ws,node_id:node.node_id,node_name:node.name,integration:node.integration||{}})));
const workspaceForTarget=(target=selectedTarget())=>{
  if(!target||target.kind!=='workspace') return null;
  return integrationWorkspaces().find(ws=>String(ws.node_id)===String(target.node_id)&&String(ws.id)===String(target.workspace_id))||null;
};
const currentWorkspace=()=>{
  const target=selectedTarget();
  // An explicit stale/offline target must never fall through to another machine.
  if(target) return target.kind==='workspace'?workspaceForTarget(target):null;
  return integrationWorkspaces()[0]||null;
};
const sentryWorkspaceTargetForId=(workspaceId)=>{
  const workspace=integrationWorkspaces().find(item=>String(item.id)===String(workspaceId||''));
  return workspace?{kind:'workspace',node_id:workspace.node_id,node_name:workspace.node_name,workspace_id:workspace.id}:null;
};
const safeTime=(value)=>{
  const stamp=Date.parse(String(value||''));
  if(!Number.isFinite(stamp)) return '';
  const seconds=Math.max(0,Math.floor((Date.now()-stamp)/1000));
  if(seconds<60) return 'now';
  if(seconds<3600) return `${Math.floor(seconds/60)}m`;
  if(seconds<86400) return `${Math.floor(seconds/3600)}h`;
  return `${Math.floor(seconds/86400)}d`;
};
const toast=(message,error=false)=>{
  if(typeof showToast==='function') showToast(message,error?4200:2400,error?'error':undefined);
};

async function runAction(payload,onEvent,{timeout=50000}={}){
  const started=await api('/api/sentry/integrations/action',{
    method:'POST',body:JSON.stringify(payload),
  });
  const id=String(started&&started.work_order_id||'');
  if(!id) throw new Error('The linked machine did not accept the action.');
  let after=0;
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){
    const result=await api(`/api/sentry/integrations/action?work_order_id=${encodeURIComponent(id)}&after=${after}`);
    for(const event of (Array.isArray(result&&result.events)?result.events:[])){
      after=Math.max(after,Number(event.index)||0);
      if(typeof onEvent==='function') await onEvent(event,id);
    }
    if(result&&result.terminal){
      if(result.state==='cancelled'||result.outcome==='cancelled'){
        throw new Error('The linked-machine action was cancelled; completion was not verified.');
      }
      if(result.outcome&&result.outcome!=='succeeded'){
        throw new Error(result.summary||'The linked-machine action failed.');
      }
      return result;
    }
    await new Promise(resolve=>setTimeout(resolve,700));
  }
  throw new Error('The linked machine did not finish in time.');
}

function setSyncBusy(busy){
  const button=byId('linkedSessionsRefresh');
  if(button) button.setAttribute('aria-busy',busy?'true':'false');
}

async function loadStatus(){
  state.status=await api('/api/sentry/integrations/status');
  renderTargetOptions();
  renderIntegrations();
  syncSurface();
  return state.status;
}

async function syncSessions(){
  const workspaces=integrationWorkspaces();
  if(!workspaces.length){state.sessions=[];renderLinkedSessions();return;}
  setSyncBusy(true);
  const snapshots=[];
  const failures=[];
  try{
    for(const workspace of workspaces){
      try{
        await runAction({action:'sessionsSync',node_id:workspace.node_id,workspace_id:workspace.id,provider:'all'},event=>{
          const payload=event&&event.payload;
          if(payload&&payload.kind==='sessions'&&Array.isArray(payload.sessions)) snapshots.push(...payload.sessions.map(session=>({
            ...session,node_id:workspace.node_id,node_name:workspace.node_name,
          })));
        });
      }catch(error){failures.push(error);}
    }
    if(failures.length===workspaces.length) throw failures[0];
    const unique=new Map();
    snapshots.forEach(item=>{
      if(!item||!item.id||!item.provider) return;
      unique.set(`${item.node_id}:${item.provider}:${item.id}`,item);
    });
    state.sessions=[...unique.values()].sort((a,b)=>String(b.updated_at||'').localeCompare(String(a.updated_at||'')));
    renderLinkedSessions();
    if(failures.length) toast('Some linked workspaces did not respond; available sessions are still shown.',true);
  }finally{setSyncBusy(false);}
}

async function refreshSentryIntegrations(options={}){
  if(state.refreshPromise) return state.refreshPromise;
  state.refreshPromise=(async()=>{
    try{
      await loadStatus();
      if(options.sync||!state.syncStarted){state.syncStarted=true;await syncSessions();}
      const target=selectedTarget();
      if(target&&target.kind==='workspace'&&document.body.dataset.sentryExperience==='work'){
        void inspectCurrentWorkspace();
      }
    }catch(error){
      renderUnavailable(error);
      if(options.sync) toast(error&&error.message?error.message:'Could not sync linked sessions.',true);
    }finally{state.refreshPromise=null;}
  })();
  return state.refreshPromise;
}

function renderUnavailable(error){
  const hub=byId('linkedSessionHub');
  if(hub&&isSentry()) hub.hidden=false;
  const groups=byId('linkedSessionGroups');
  if(groups){groups.textContent='';const row=document.createElement('div');row.className='linked-session-boundary';row.textContent='Linked machine unavailable.';groups.appendChild(row);}
  const boundary=byId('linkedSessionBoundary');
  if(boundary) boundary.textContent=String(error&&error.message||'Reconnect the execution node to load provider sessions.');
}

function renderLinkedSessions(){
  const hub=byId('linkedSessionHub');
  const groups=byId('linkedSessionGroups');
  if(!hub||!groups) return;
  hub.hidden=!isSentry();
  groups.textContent='';
  const providers=[['codex','Codex'],['claude','Claude Code']];
  for(const [id,label] of providers){
    const items=state.sessions.filter(item=>item.provider===id).slice(0,8);
    const section=document.createElement('section');section.className='linked-session-group';
    const heading=document.createElement('div');heading.className='linked-session-group-title';
    const name=document.createElement('span');name.textContent=label;
    const count=document.createElement('span');count.textContent=String(items.length);
    heading.append(name,count);section.appendChild(heading);
    if(!items.length){
      const empty=document.createElement('div');empty.className='linked-session-boundary';empty.textContent='No local sessions in linked workspaces.';section.appendChild(empty);
    }
    for(const item of items){
      const row=document.createElement('button');row.type='button';row.className=`linked-session-row${item.live?' is-live':''}`;
      if(state.selectedSession&&state.selectedSession.id===item.id&&state.selectedSession.provider===item.provider&&String(state.selectedSession.node_id)===String(item.node_id)) row.classList.add('active');
      row.addEventListener('click',()=>openLinkedProviderSession(item));
      const dot=document.createElement('span');dot.className='linked-session-dot';dot.setAttribute('aria-hidden','true');
      const copy=document.createElement('span');copy.className='linked-session-copy';
      const title=document.createElement('strong');title.textContent=String(item.title||`${label} session`);
      const meta=document.createElement('span');meta.textContent=[item.node_name,item.source,item.model,item.branch].filter(Boolean).join(' · ');
      copy.append(title,meta);
      const time=document.createElement('span');time.className='linked-session-time';time.textContent=safeTime(item.updated_at);
      row.append(dot,copy,time);section.appendChild(row);
    }
    groups.appendChild(section);
  }
  const boundary=byId('linkedSessionBoundary');
  if(boundary) boundary.textContent=String(state.status&&state.status.provider_boundary||'Local installation history only.');
}

function renderProviderSnapshot(snapshot){
  if(!snapshot||snapshot.kind!=='session') return;
  state.providerSnapshot=snapshot;
  const session=snapshot.session||state.selectedSession||{};
  const title=byId('providerSessionTitle');if(title) title.textContent=String(session.title||'Provider session');
  const kicker=byId('providerSessionKicker');if(kicker) kicker.textContent=`${session.provider==='claude'?'Claude Code':'Codex'} · ${session.source||'local session'}`;
  const meta=byId('providerSessionMeta');if(meta) meta.textContent=[state.selectedSession&&state.selectedSession.node_name,session.model,session.branch,session.workspace_id,safeTime(session.updated_at)].filter(Boolean).join(' · ');
  const live=byId('providerSessionLiveState');
  if(live){live.classList.toggle('is-live',!!session.live||state.watching);live.textContent=state.watching?'Watching live':(session.live?'Active now':'Read only');}
  const transcript=byId('providerSessionTranscript');
  if(!transcript) return;
  const wasNearBottom=transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight<120;
  transcript.textContent='';
  const messages=Array.isArray(snapshot.messages)?snapshot.messages:[];
  if(!messages.length){const empty=document.createElement('div');empty.className='provider-session-empty';empty.textContent='No user or assistant messages were found in this local session.';transcript.appendChild(empty);return;}
  for(const message of messages){
    const row=document.createElement('article');row.className=`provider-session-message${message.role==='assistant'?' is-assistant':''}`;
    const role=document.createElement('div');role.className='provider-session-role';role.textContent=message.role==='assistant'?'Assistant':'You';
    const content=document.createElement('div');content.className='provider-session-content';content.textContent=String(message.content||'');
    row.append(role,content);transcript.appendChild(row);
  }
  if(wasNearBottom||state.watching) transcript.scrollTop=transcript.scrollHeight;
}

async function openLinkedProviderSession(session){
  state.selectedSession=session;state.providerSnapshot=null;
  renderLinkedSessions();
  const view=byId('providerSessionView');if(view) view.hidden=false;
  document.body.classList.add('sentry-provider-session-open');
  const transcript=byId('providerSessionTranscript');if(transcript) transcript.innerHTML='<div class="provider-session-empty">Loading this linked session…</div>';
  const title=byId('providerSessionTitle');if(title) title.textContent=String(session.title||'Provider session');
  const kicker=byId('providerSessionKicker');if(kicker) kicker.textContent=`${session.provider==='claude'?'Claude Code':'Codex'} · ${session.source||'local session'}`;
  try{
    await runAction({action:'sessionRead',node_id:session.node_id,workspace_id:session.workspace_id,provider:session.provider,provider_session_id:session.id},event=>{
      if(event&&event.payload&&event.payload.kind==='session') renderProviderSnapshot(event.payload);
    });
  }catch(error){if(transcript) transcript.innerHTML='';renderUnavailableProvider(error);}
}

function renderUnavailableProvider(error){
  const transcript=byId('providerSessionTranscript');if(!transcript) return;
  transcript.textContent='';const empty=document.createElement('div');empty.className='provider-session-empty';empty.textContent=String(error&&error.message||'This linked session is no longer available.');transcript.appendChild(empty);
}

async function cancelWatch(){
  const id=state.watchOrderId;state.watchOrderId=null;
  if(!id) return;
  try{await api('/api/sentry/integrations/cancel',{method:'POST',body:JSON.stringify({work_order_id:id})});}catch(_){ }
}

async function watchLoop(){
  while(state.watching&&state.selectedSession){
    const session=state.selectedSession;
    try{
      await runAction({action:'sessionWatch',node_id:session.node_id,workspace_id:session.workspace_id,provider:session.provider,provider_session_id:session.id,watch_seconds:15},(event,id)=>{
        state.watchOrderId=id;
        if(event&&event.payload&&event.payload.kind==='session') renderProviderSnapshot(event.payload);
      },{timeout:35000});
    }catch(error){if(state.watching) toast(error&&error.message||'Live view paused.',true);}
    state.watchOrderId=null;
    if(state.watching) await new Promise(resolve=>setTimeout(resolve,350));
  }
}

async function toggleLinkedProviderWatch(){
  if(!state.selectedSession) return;
  state.watching=!state.watching;
  const button=byId('providerSessionWatchBtn');if(button) button.textContent=state.watching?'Stop watching':'Watch live';
  renderProviderSnapshot(state.providerSnapshot||{kind:'session',session:state.selectedSession,messages:[]});
  if(state.watching) void watchLoop();else await cancelWatch();
}

async function closeLinkedProviderSession(){
  state.watching=false;await cancelWatch();state.selectedSession=null;state.providerSnapshot=null;
  document.body.classList.remove('sentry-provider-session-open');
  const view=byId('providerSessionView');if(view) view.hidden=true;
  renderLinkedSessions();
}

function positionTargetMenu(){
  const menu=byId('sentryTargetMenu'),button=byId('sentryTargetChip');if(!menu||!button||menu.hidden) return;
  const rect=button.getBoundingClientRect();const width=Math.min(360,window.innerWidth-24);
  menu.style.left=`${Math.max(12,Math.min(rect.left,window.innerWidth-width-12))}px`;
  menu.style.top=`${Math.max(12,rect.top-menu.offsetHeight-7)}px`;
}

function toggleSentryTargetMenu(event){
  if(event&&event.stopPropagation) event.stopPropagation();
  const menu=byId('sentryTargetMenu'),button=byId('sentryTargetChip');if(!menu||!button) return;
  menu.hidden=!menu.hidden;button.setAttribute('aria-expanded',menu.hidden?'false':'true');
  if(!menu.hidden){renderTargetOptions();requestAnimationFrame(positionTargetMenu);}
}

function closeTargetMenu(){const menu=byId('sentryTargetMenu'),button=byId('sentryTargetChip');if(menu) menu.hidden=true;if(button) button.setAttribute('aria-expanded','false');}

function renderTargetOptions(){
  const container=byId('sentryTargetOptions');if(!container) return;container.textContent='';
  const current=selectedTarget();
  const addSection=(title,items,build)=>{
    if(!items.length) return;
    const section=document.createElement('section');section.className='sentry-target-section';
    const heading=document.createElement('div');heading.className='sentry-target-section-title';heading.textContent=title;section.appendChild(heading);
    items.forEach(item=>section.appendChild(build(item)));container.appendChild(section);
  };
  addSection('Linked workspaces',integrationWorkspaces(),workspace=>{
    const target={kind:'workspace',node_id:workspace.node_id,node_name:workspace.node_name,workspace_id:workspace.id};
    const button=document.createElement('button');button.type='button';button.className='sentry-target-option';
    if(current&&current.kind==='workspace'&&current.node_id===target.node_id&&current.workspace_id===target.workspace_id) button.classList.add('active');
    button.append(document.createTextNode(String(workspace.id)));const meta=document.createElement('span');meta.textContent=String(workspace.node_name||'Linked machine');button.appendChild(meta);
    button.addEventListener('click',()=>selectSentryTarget(target));return button;
  });
  const services=Array.isArray(state.status&&state.status.services&&state.status.services.services)?state.status.services.services:[];
  const nativeCodex=typeof _selectedNativeRuntimeId==='function'&&_selectedNativeRuntimeId()==='codex';
  if(!nativeCodex) addSection('Server services',services,service=>{
    const target={kind:'service',service_id:service.id,name:service.name,status:service.status};
    const button=document.createElement('button');button.type='button';button.className='sentry-target-option';
    if(current&&current.kind==='service'&&current.service_id===target.service_id) button.classList.add('active');
    button.append(document.createTextNode(String(service.name)));const meta=document.createElement('span');meta.textContent=String(service.status||'allowlisted');button.appendChild(meta);
    button.addEventListener('click',()=>selectSentryTarget(target));return button;
  });
}

async function selectSentryTarget(target){
  const previous=selectedTarget();
  const inChat=!!target&&typeof _currentExperience==='function'&&_currentExperience()==='chat';
  if(inChat){
    if(typeof S!=='undefined'&&S.busy){toast('Wait for the current response to finish before targeting a machine or service.',true);return;}
    if(typeof S!=='undefined') S._pendingSentryTarget={...target};
    syncTargetChip();closeTargetMenu();
    try{
      if(typeof selectExperience!=='function') throw new Error('Work mode is unavailable.');
      await selectExperience('work');
      if(typeof _currentExperience==='function'&&_currentExperience()!=='work') throw new Error('Work mode did not open.');
      toast('Opened Work so Hermes can use the selected target.');
      if(target.kind==='workspace') void inspectCurrentWorkspace();
      return;
    }catch(error){
      if(typeof S!=='undefined') S._pendingSentryTarget=previous||null;
      syncTargetChip();toast(error&&error.message||'Could not open Work for that target.',true);return;
    }
  }
  if(typeof S!=='undefined') S._pendingSentryTarget=target?{...target}:null;
  if(typeof S!=='undefined'&&S.session) S.session.sentry_target=target?{...target}:{};
  syncTargetChip();closeTargetMenu();
  try{
    if(typeof S!=='undefined'&&S.session){
      const data=await api('/api/session/update',{method:'POST',body:JSON.stringify({
        session_id:S.session.session_id,workspace:S.session.workspace,
        native_workspace_id:S.session.native_workspace_id||S._pendingNativeWorkspaceId||null,
        native_runtime_options:S.session.native_runtime_options||S._pendingNativeRuntimeOptions||{},
        sentry_target:target||{},
      })});
      if(typeof _applySessionContextMetadataUpdate==='function') _applySessionContextMetadataUpdate(data);
    }
    if(target&&target.kind==='workspace'){
      const runtime=typeof _selectedNativeRuntimeId==='function'?_selectedNativeRuntimeId():'';
      if(runtime==='codex'&&typeof selectNativeWorkspace==='function') await selectNativeWorkspace(target.workspace_id);
      if(document.body.dataset.sentryExperience==='work') void inspectCurrentWorkspace();
    }else{state.workspaceSnapshot=null;renderWorkspaceSnapshot(null);}
  }catch(error){
    if(typeof S!=='undefined') S._pendingSentryTarget=previous||null;
    if(typeof S!=='undefined'&&S.session) S.session.sentry_target=previous||{};
    syncTargetChip();toast('Could not update the Hermes target.',true);
  }
}

function targetLabel(target){
  if(!target) return 'No target';
  if(target.kind==='workspace') return `${target.node_name||'Machine'} / ${target.workspace_id}`;
  return target.name||'Server service';
}

function syncTargetChip(){
  const wrap=byId('sentryTargetWrap'),button=byId('sentryTargetChip'),label=byId('sentryTargetLabel');
  if(wrap) wrap.hidden=!isSentry();
  const target=selectedTarget();if(label) label.textContent=targetLabel(target);if(button) button.classList.toggle('has-target',!!target);
  const inspectorTarget=byId('sentryInspectorTarget');if(inspectorTarget) inspectorTarget.textContent=targetLabel(target);
  renderTargetOptions();
}

function selectSentryInspectorTab(name){
  for(const button of document.querySelectorAll('[data-sentry-inspector-tab]')){
    const active=button.dataset.sentryInspectorTab===name;button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false');
  }
  for(const panel of document.querySelectorAll('[data-sentry-inspector-panel]')) panel.hidden=panel.dataset.sentryInspectorPanel!==name;
}

function renderDiff(diff){
  const pre=byId('sentryDiff'),empty=byId('sentryDiffEmpty');if(!pre||!empty) return;
  pre.textContent='';
  if(!diff){pre.hidden=true;empty.hidden=false;empty.textContent=state.workspaceSnapshot&&state.workspaceSnapshot.is_repository?'No tracked changes in this workspace.':'This workspace is not a Git repository.';return;}
  empty.hidden=true;pre.hidden=false;
  String(diff).split('\n').forEach(line=>{
    const row=document.createElement('span');row.className='sentry-diff-line';
    if(line.startsWith('+')&&!line.startsWith('+++')) row.classList.add('is-add');
    else if(line.startsWith('-')&&!line.startsWith('---')) row.classList.add('is-remove');
    else if(line.startsWith('@@')) row.classList.add('is-hunk');
    else if(line.startsWith('diff ')||line.startsWith('---')||line.startsWith('+++')) row.classList.add('is-file');
    row.textContent=line||' ';pre.appendChild(row);
  });
}

function renderWorkspaceSnapshot(snapshot){
  state.workspaceSnapshot=snapshot;
  const count=byId('sentryChangesCount');if(count) count.textContent=String(snapshot&&snapshot.changed_count||0);
  const branch=byId('sentryDiffBranch');if(branch) branch.textContent=snapshot&&snapshot.branch?String(snapshot.branch):'Workspace diff';
  renderDiff(snapshot&&snapshot.diff||'');renderGithub();renderIntegrations();
}

let workspaceInspectEpoch=0;
async function inspectCurrentWorkspace(){
  const epoch=++workspaceInspectEpoch;
  const workspace=currentWorkspace();
  renderWorkspaceSnapshot(null);
  if(!workspace) return;
  const stillCurrent=()=>{
    const current=currentWorkspace();
    return epoch===workspaceInspectEpoch&&current&&
      String(current.node_id)===String(workspace.node_id)&&String(current.id)===String(workspace.id);
  };
  const empty=byId('sentryDiffEmpty');
  if(empty){empty.hidden=false;empty.textContent='Loading the linked workspace diff…';}
  let received=false;
  try{
    await runAction({action:'workspaceInspect',node_id:workspace.node_id,workspace_id:workspace.id},event=>{
      if(stillCurrent()&&event&&event.payload&&event.payload.kind==='workspace'){
        received=true;renderWorkspaceSnapshot(event.payload);
      }
    });
    if(stillCurrent()&&!received) throw new Error('The linked machine returned no workspace snapshot.');
  }catch(error){
    if(!stillCurrent()) return;
    renderWorkspaceSnapshot(null);
    if(empty){empty.hidden=false;empty.textContent=String(error&&error.message||'Could not load workspace changes.');}
    toast('Could not inspect the linked workspace.',true);
  }
}

function updateSentryLiveDiff(payload){
  const target=selectedTarget();
  const workspaceId=target&&target.kind==='workspace'?target.workspace_id:(currentWorkspace()||{}).id;
  const snapshot={...(state.workspaceSnapshot||{}),kind:'workspace',workspace_id:workspaceId,is_repository:true,diff:String(payload&&payload.diff||''),changed_count:Math.max(1,Number(state.workspaceSnapshot&&state.workspaceSnapshot.changed_count)||0),source:'codex-live'};
  renderWorkspaceSnapshot(snapshot);selectSentryInspectorTab('changes');
}

function makeCard(title,statusText,description,statusOn=true){
  const card=document.createElement('article');card.className='sentry-integration-card';
  const head=document.createElement('div');head.className='sentry-integration-card-head';const strong=document.createElement('strong');strong.textContent=title;const status=document.createElement('span');status.className=`status${statusOn?' is-on':''}`;status.textContent=statusText;head.append(strong,status);
  const copy=document.createElement('p');copy.textContent=description;card.append(head,copy);return card;
}

function renderGithub(){
  const container=byId('sentryGithubContent');if(!container) return;container.textContent='';
  const snapshot=state.workspaceSnapshot;
  if(!snapshot){container.appendChild(makeCard('GitHub','Choose a workspace','Select a linked workspace to inspect its repository, branch, changes, and IDE handoff.',false));return;}
  if(!snapshot.github_url){container.appendChild(makeCard('Git remote','Not GitHub','The selected workspace has no GitHub origin. Its local diff remains available in Changes.',false));return;}
  const card=makeCard('GitHub repository',snapshot.github_authenticated?'GitHub CLI connected':'Repository linked',`${snapshot.branch||'Current branch'} · ${snapshot.changed_count||0} changed item(s).`,true);
  const actions=document.createElement('div');actions.className='sentry-integration-actions';
  const link=document.createElement('a');link.href=String(snapshot.github_url);link.target='_blank';link.rel='noopener noreferrer';link.textContent='View on GitHub';actions.appendChild(link);
  for(const ide of (Array.isArray(snapshot.ides)?snapshot.ides:[])){const button=document.createElement('button');button.type='button';button.textContent=`Open in ${ide.label||ide.id}`;button.addEventListener('click',()=>openWorkspaceInIde(ide.id));actions.appendChild(button);}
  card.appendChild(actions);container.appendChild(card);
  const pullRequest=snapshot.pull_request&&typeof snapshot.pull_request==='object'?snapshot.pull_request:null;
  if(pullRequest&&pullRequest.url){
    const prState=pullRequest.draft?'Draft':String(pullRequest.state||'Open').toLowerCase().replace(/^./,value=>value.toUpperCase());
    const fallback=(pullRequest.head||'Current branch')+' → '+(pullRequest.base||'base');
    const pr=makeCard('Pull request #'+(pullRequest.number||''),prState,String(pullRequest.title||fallback),true);
    const prActions=document.createElement('div');prActions.className='sentry-integration-actions';
    const prLink=document.createElement('a');prLink.href=String(pullRequest.url);prLink.target='_blank';prLink.rel='noopener noreferrer';prLink.textContent='Open pull request';prActions.appendChild(prLink);pr.appendChild(prActions);container.appendChild(pr);
  }else if(snapshot.github_authenticated){
    container.appendChild(makeCard('Pull request','None for this branch','Create or switch to a pull request in the linked workspace and refresh to see it here.',false));
  }
  if(!snapshot.github_authenticated) container.appendChild(makeCard('GitHub actions','View-only','Repository links and diffs work now. Push, pull request, and issue mutations stay hidden until GitHub CLI is authenticated on the linked machine.',false));
}

function renderIntegrations(){
  const container=byId('sentryIntegrationsContent');if(!container) return;container.textContent='';
  const nodes=onlineNodes();
  container.appendChild(makeCard('Hermes routing',nodes.length?'Connected':'Offline',nodes.length?'Targets are resolved through the signed outbound node and Server Control allowlist.':'Reconnect the execution node to target workspaces.',nodes.length>0));
  const target=selectedTarget();
  const inventoryNode=target&&target.kind==='workspace'
    ?nodes.find(item=>String(item.node_id)===String(target.node_id))
    :nodes[0];
  const inventory=inventoryNode&&inventoryNode.integration&&inventoryNode.integration.inventory||{};
  for(const provider of (Array.isArray(inventory.providers)?inventory.providers:[])){
    container.appendChild(makeCard(provider.label||provider.id,provider.available?'Local sessions available':'Not found',provider.available?'Sync and live read-only viewing use this machine’s local provider logs.':'No local installation history was found for linked workspaces.',!!provider.available));
  }
  const ides=Array.isArray(inventory.ides)?inventory.ides:[];
  const ideCard=makeCard('IDE handoff',ides.length?'Ready':'No supported IDE',ides.length?'Open a selected linked workspace directly in its installed editor.':'Install Visual Studio Code or Cursor on the linked machine to enable handoff.',ides.length>0);
  if(ides.length){const actions=document.createElement('div');actions.className='sentry-integration-actions';ides.forEach(ide=>{const button=document.createElement('button');button.type='button';button.textContent=ide.label||ide.id;button.addEventListener('click',()=>openWorkspaceInIde(ide.id));actions.appendChild(button);});ideCard.appendChild(actions);}container.appendChild(ideCard);
  container.appendChild(makeCard('Provider website chats','Model access only','ChatGPT, Claude.ai, and other private website histories are not granted by model OAuth. Sentry shows local Codex and Claude Code sessions when their installations expose them.',false));
}

async function openWorkspaceInIde(ide,workspaceId=null,nodeId=null){
  const workspace=workspaceId
    ?integrationWorkspaces().find(item=>String(item.id)===String(workspaceId)&&(!nodeId||String(item.node_id)===String(nodeId)))
    :currentWorkspace();
  if(!workspace){toast('Choose a linked workspace first.',true);return;}
  try{
    await runAction({action:'openIde',node_id:workspace.node_id,workspace_id:workspace.id,ide},()=>{});
    toast('Opened '+(ide==='cursor'?'Cursor':'Visual Studio Code')+' on '+workspace.node_name+'.');
  }catch(error){toast(error&&error.message||'Could not open the IDE.',true);}
}
function openCurrentWorkspaceInIde(){
  const session=state.selectedSession;
  const node=session&&onlineNodes().find(item=>String(item.node_id)===String(session.node_id));
  const nodeIdes=node&&node.integration&&node.integration.inventory&&Array.isArray(node.integration.inventory.ides)?node.integration.inventory.ides:[];
  const ides=session?nodeIdes:(state.workspaceSnapshot&&Array.isArray(state.workspaceSnapshot.ides)?state.workspaceSnapshot.ides:[]);
  const preferred=ides.find(item=>item.id==='vscode')||ides[0];
  if(!preferred){toast('No supported IDE is available on the linked machine.',true);return;}
  void openWorkspaceInIde(preferred.id,session&&session.workspace_id,session&&session.node_id);
}

function syncSurface(){
  const sentry=isSentry();const hub=byId('linkedSessionHub'),wrap=byId('sentryTargetWrap'),inspector=byId('sentryInspector');
  if(hub) hub.hidden=!sentry;if(wrap) wrap.hidden=!sentry;if(inspector) inspector.hidden=!sentry;
  syncTargetChip();renderLinkedSessions();
}

document.addEventListener('click',event=>{
  const target=event.target&&event.target.closest?event.target.closest('#sentryTargetMenu,#sentryTargetChip'):null;if(!target) closeTargetMenu();
});
window.addEventListener('resize',positionTargetMenu);
document.addEventListener('DOMContentLoaded',()=>{
  let attempts=0;
  const boot=()=>{
    attempts++;
    if(isSentry()){syncSurface();void refreshSentryIntegrations();return;}
    if(attempts<30) setTimeout(boot,300);
  };
  boot();
});

Object.assign(window,{
  refreshSentryIntegrations,
  openLinkedProviderSession,
  closeLinkedProviderSession,
  toggleLinkedProviderWatch,
  toggleSentryTargetMenu,
  selectSentryTarget,
  selectSentryInspectorTab,
  inspectCurrentWorkspace,
  updateSentryLiveDiff,
  openWorkspaceInIde,
  openCurrentWorkspaceInIde,
  sentryWorkspaceTargetForId,
  syncSentryIntegrationSurface:syncSurface,
});
})();

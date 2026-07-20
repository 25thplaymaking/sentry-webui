/* ═══════════════════════════════════════════════════════════════════════════
   FRONTIR: Frontir Sentry — voice console + skin registration
   ───────────────────────────────────────────────────────────────────────────
   Additive module, loaded after boot.js. It never rewrites upstream DOM or
   patches upstream internals; it only:

     • registers the "frontir" skin through the documented extension API
       (window.registerHermesSkin) so it appears in the native Settings
       picker and `/theme frontir` — zero edits to boot/commands/panels;
     • injects a small nav block (New task / Voice / Scheduled) and a user
       chip into the sidebar (both CSS-hidden unless the frontir skin is
       active, so switching skins restores stock Hermes exactly);
     • mounts the full-screen voice console (orb, glass cards, dock) on
       <body> as its own scroll container — no upstream scroll container
       (.messages etc.) is touched, preserving the iOS scroll fixes;
     • follows the built-in voice-mode state machine passively via a
       MutationObserver on #voiceModeIndicator / #btnVoiceMode — it never
       reimplements or monkey-patches the voice loop.

   Guarded for idempotence: re-injecting this script is a no-op.
   ═══════════════════════════════════════════════════════════════════════ */
(function(){
  'use strict';
  if(window.__FRONTIR_INIT__) return;
  window.__FRONTIR_INIT__=true;

  var doc=document;
  function byId(id){ return doc.getElementById(id); }
  function el(tag,cls,text){
    var n=doc.createElement(tag);
    if(cls) n.className=cls;
    if(text!=null) n.textContent=text;
    return n;
  }
  function svgIcon(paths,size){
    var s='<svg width="'+(size||16)+'" height="'+(size||16)+'" viewBox="0 0 24 24" fill="none" '+
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '+
      'aria-hidden="true">'+paths+'</svg>';
    var span=el('span');
    span.innerHTML=s;                 // static string above — no user input
    return span.firstChild;
  }
  var ICO={
    plus:'<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    voice:'<path d="M2 10v4"/><path d="M6 6v12"/><path d="M10 3v18"/><path d="M14 8v8"/><path d="M18 5v14"/><path d="M22 10v4"/>',
    clock:'<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 13.5"/>',
    grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    transcript:'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8"/><path d="M8 13h5"/>',
    mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="19" x2="12" y2="22"/>',
    speaker:'<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9.5 9.5 0 0 1 0 13"/>',
    /* muted = same cone with the arcs replaced by a cross, the conventional
       "speaker off" glyph. Same stroke weight/box as `speaker` so swapping
       between them does not shift the icon's optical centre.              */
    speakerOff:'<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="16" y1="9.5" x2="22" y2="15.5"/><line x1="22" y1="9.5" x2="16" y2="15.5"/>',
    gear:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82V15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    close:'<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'
  };

  function skinActive(){
    return (doc.documentElement.dataset.skin||'')==='frontir';
  }

  /* ── 1. Skin registration ─────────────────────────────────────────────
     Token values are IDENTICAL to the :root[data-skin="frontir"] light
     block in frontir.css (the injected extension <style> would otherwise
     win the cascade tie); the dark variant lives only in frontir.css via
     the higher-specificity :root.dark[data-skin="frontir"] block.        */
  function registerSkin(){
    if(typeof window.registerHermesSkin!=='function') return false;
    return window.registerHermesSkin({
      name:'Frontir',
      value:'frontir',
      label:'Frontir',
      colors:['#09090B','#F4F3EF','#7FD4C1'],
      tokens:{
        '--bg':'#F4F3EF',
        '--sidebar':'#F4F3EF',
        '--surface':'#FBFAF7',
        '--surface-subtle':'rgba(20,20,24,.04)',
        '--text':'#1B1B1F',
        '--muted':'#565660',
        '--accent':'#22222A',
        '--accent-hover':'#000000',
        '--accent-text':'#22222A',
        '--accent-bg':'rgba(34,34,42,.07)',
        '--accent-bg-strong':'rgba(34,34,42,.14)',
        '--border':'rgba(20,20,24,.12)',
        '--border2':'rgba(20,20,24,.22)',
        '--hover-bg':'rgba(20,20,24,.06)',
        '--code-bg':'#ECEBE5',
        '--code-text':'#3A3A42',
        '--success':'#2C7A57',
        '--warning':'#8A5F14',
        '--danger':'#B3403C',
        '--info':'#14766A'
      }
    });
  }

  /* ── 2. Default assistant display name: Hermes → Sentry ───────────────
     assistantDisplayName() (ui.js) falls back to 'Hermes' when the user
     has not chosen a bot name. Wrap — don't replace — so a user-chosen
     name always wins and upstream changes to the function keep working.  */
  function rebrandAssistantName(){
    var orig=window.assistantDisplayName;
    if(typeof orig!=='function'||orig.__frontir) return;
    var wrapped=function(){
      var n=orig.apply(this,arguments);
      return n==='Hermes'?'Sentry':n;
    };
    wrapped.__frontir=true;
    window.assistantDisplayName=wrapped;
  }

  /* ── 3. Sidebar nav + user chip (CSS-gated to the frontir skin) ────── */
  function navItem(label,icon,onClick){
    var b=el('button','frontir-nav-item');
    b.type='button';
    b.appendChild(svgIcon(icon,16));
    b.appendChild(el('span',null,label));
    b.addEventListener('click',onClick);
    return b;
  }
  var navVoiceBtn=null;
  function injectSidebar(){
    var sidebar=doc.querySelector('.sidebar');
    if(!sidebar||byId('frontirNav')) return;

    var nav=el('nav');
    nav.id='frontirNav';
    nav.setAttribute('aria-label','Frontir shortcuts');
    nav.appendChild(navItem('New task',ICO.plus,function(){
      var b=byId('btnNewChat');
      if(typeof window.switchPanel==='function') window.switchPanel('chat',{fromRailClick:true});
      if(b) b.click();
      markNavActive(null);
    }));
    navVoiceBtn=navItem('Voice',ICO.voice,function(){
      openConsole();
    });
    nav.appendChild(navVoiceBtn);
    nav.appendChild(navItem('Scheduled',ICO.clock,function(e){
      if(typeof window.switchPanel==='function') window.switchPanel('tasks',{fromRailClick:true});
      markNavActive(e.currentTarget);
    }));

    var firstPanel=sidebar.querySelector('.panel-view');
    sidebar.insertBefore(nav,firstPanel||null);

    var user=el('div');
    user.id='frontirUser';
    var avatar=el('span','frontir-user-avatar','S');
    avatar.setAttribute('aria-hidden','true');
    var name=el('button','frontir-user-name');
    name.type='button';
    name.title='Agent profiles';
    var gear=el('button','frontir-user-gear');
    gear.type='button';
    gear.setAttribute('aria-label','Settings');
    gear.appendChild(svgIcon(ICO.gear,15));
    name.addEventListener('click',function(){
      if(typeof window.switchPanel==='function') window.switchPanel('profiles',{fromRailClick:true});
    });
    gear.addEventListener('click',function(){
      if(typeof window.switchPanel==='function') window.switchPanel('settings',{fromRailClick:true});
    });
    user.appendChild(avatar);
    user.appendChild(name);
    user.appendChild(gear);
    sidebar.appendChild(user);
    syncUserChip();
  }
  function markNavActive(target){
    doc.querySelectorAll('#frontirNav .frontir-nav-item').forEach(function(b){
      b.classList.toggle('active',b===target);
    });
  }
  function syncUserChip(){
    var name=doc.querySelector('#frontirUser .frontir-user-name');
    var avatar=doc.querySelector('#frontirUser .frontir-user-avatar');
    if(!name) return;
    var label='Sentry';
    try{
      if(typeof window.assistantDisplayName==='function') label=window.assistantDisplayName()||label;
    }catch(_){}
    name.textContent=label;
    if(avatar) avatar.textContent=(label.charAt(0)||'S').toUpperCase();
  }

  /* ── 3b. Projects section (product decision, 2026-07-20) ──────────────
     The target mock has a "Projects" sidebar section. Hermes already has a
     complete project system — create / rename / delete / colour, profile
     scoped, persisted in projects.json, and rendered as `.project-bar` at
     the top of the session list, where selecting one filters the list.

     So this ships the section as a *promotion of the real thing*, not a
     second one: no project state, no API calls and no click handlers are
     added here. We only name the existing bar; frontir.css lays it out as
     a titled vertical section. Every upstream interaction survives intact
     — double-click rename, right-click / long-press menu, "+" create,
     quick-assign, profile scoping — and any other skin restores the stock
     horizontal chip row exactly.

     The bar is absent only when a profile has no projects AND no
     conversations at all, i.e. a fresh install; the section therefore
     appears with the first conversation, which is also the first moment it
     could say anything true. That is deliberate — an always-present empty
     "Projects" header on an empty install is chrome, not information.    */
  function enrichProjectBar(){
    var bar=doc.querySelector('#sessionList .project-bar');
    if(!bar||bar.dataset.frontirProjects) return;
    bar.dataset.frontirProjects='1';
    bar.setAttribute('role','group');
    bar.setAttribute('aria-label','Projects');
    /* aria-hidden: the group above already carries the name, so exposing
       the heading too would announce "Projects" twice.                    */
    var head=el('h3','frontir-projects-head','Projects');
    head.setAttribute('aria-hidden','true');
    bar.insertBefore(head,bar.firstChild);
  }
  function watchProjectBar(){
    var list=byId('sessionList');
    if(!list) return;
    enrichProjectBar();
    /* renderSessionList() rebuilds the bar from scratch on every render, so
       re-label each new one. childList (not subtree) on purpose: our own
       insertBefore lands inside .project-bar and so cannot re-trigger this
       observer.                                                           */
    try{ new MutationObserver(enrichProjectBar).observe(list,{childList:true}); }catch(_){}
  }

  /* ── 4. Voice console ───────────────────────────────────────────────── */
  var console_=null, orbBtn=null, stateWord=null, stateHint=null,
      statusText=null, startBtn=null, startLabel=null, widgetsBtn=null,
      speakerBtn=null, lastFocus=null, refreshTimer=null;

  var cardDefs={
    context:{
      title:'Live context',
      foot:'View context',
      rows:['Project','Focus','Files','Recent','Workspace']
    },
    goals:{
      title:'Current goals',
      foot:'View goals',
      rows:[]
    }
  };

  function buildCard(kind){
    var def=cardDefs[kind];
    var card=el('section','frontir-card frontir-card--'+kind);
    card.dataset.frontirCard=kind;
    card.setAttribute('aria-label',def.title);
    var handle=el('span','frontir-card-handle');
    handle.setAttribute('aria-hidden','true');
    card.appendChild(handle);
    card.appendChild(el('h2','frontir-card-title',def.title));
    var rows=el('div','frontir-card-rows');
    rows.dataset.frontirRows=kind;
    card.appendChild(rows);
    var foot=el('button','frontir-card-foot');
    foot.type='button';
    foot.appendChild(el('span',null,def.foot));
    foot.addEventListener('click',function(){
      closeConsole();
      if(kind==='context'){
        try{
          if(typeof window.toggleWorkspacePanel==='function'&&
             doc.documentElement.dataset.workspacePanel!=='open'){
            window.toggleWorkspacePanel(true);
          }
        }catch(_){}
      }else if(typeof window.switchPanel==='function'){
        window.switchPanel('todos',{fromRailClick:true});
      }
    });
    card.appendChild(foot);
    enableDrag(card,handle,kind);
    return card;
  }

  function cardRow(label,value,mono){
    var row=el('div','frontir-card-row');
    row.appendChild(el('span','frontir-card-label',label));
    var v=el('span','frontir-card-value'+(mono?' is-mono':''),value);
    v.title=value;
    row.appendChild(v);
    return row;
  }

  function dockBtn(label,icon,opts){
    opts=opts||{};
    var b=el('button','frontir-dock-btn'+(opts.primary?' frontir-dock-btn--primary':''));
    b.type='button';
    b.setAttribute('aria-label',opts.aria||label);
    var circle=el('span','frontir-dock-circle');
    circle.appendChild(svgIcon(icon,opts.primary?20:17));
    b.appendChild(circle);
    b.appendChild(el('span','frontir-dock-label',label));
    return b;
  }

  /* ── Speaker = a persistent mute (product decision, 2026-07-20) ───────
     Previously this stopped the current utterance only, so the next reply
     spoke again — not what a speaker glyph means anywhere else.

     It deliberately does NOT drive `hermes-tts-enabled`, despite that
     looking like the obvious preference to share with Settings. That key's
     entire effect is the `body.tts-enabled` class, which CSS uses to SHOW
     the per-message read-aloud buttons (`.msg-tts-btn`). It gates an
     affordance, not audio — a mute wired to it would hide buttons and
     still silence nothing. Hermes has no mute preference, so we own one.

     Enforcement point: window.autoReadLastAssistant is the single entry to
     every speech path — messages.js calls it on stream completion, and
     boot.js overrides it so a live voice session routes into
     _speakResponse(). Wrapping it (the §6 pattern) gates speech with no
     upstream patch.

     Deliberate exception — a live voice session is let through. boot.js
     only returns the turn loop to listening from *inside* _speakResponse(),
     so skipping it would park the session in 'thinking' forever. Muting
     still stops the utterance that is playing; ending the session is what
     stops voice. Documented in FRONTIR-UI.md §9.                          */
  var MUTE_KEY='frontir-muted';
  function muted(){
    try{ return localStorage.getItem(MUTE_KEY)==='1'; }catch(_){ return false; }
  }
  function setMuted(on){
    try{ localStorage.setItem(MUTE_KEY,on?'1':'0'); }catch(_){}
    /* a mute that lets the current sentence finish reads as a dead button */
    if(on){ try{ if(typeof window.stopTTS==='function') window.stopTTS(); }catch(_){} }
    syncSpeakerBtn();
  }
  /* boot.js swaps window.autoReadLastAssistant in on voice activate and
     restores the original on deactivate — which drops our wrapper with it.
     Re-assert idempotently from the voice observer instead of patching
     boot.js; the marker makes repeat calls free.                          */
  function guardAutoRead(){
    var fn=window.autoReadLastAssistant;
    if(typeof fn!=='function'||fn.__frontirMute) return;
    var wrapped=function(){
      if(muted()&&!voiceActive()) return;
      return fn.apply(this,arguments);
    };
    wrapped.__frontirMute=true;
    window.autoReadLastAssistant=wrapped;
  }
  var speakerWasMuted=null;
  function syncSpeakerBtn(){
    if(!speakerBtn) return;
    var m=muted();
    if(speakerWasMuted===m) return;
    speakerWasMuted=m;
    speakerBtn.classList.toggle('is-muted',m);
    speakerBtn.setAttribute('aria-pressed',m?'true':'false');
    var label=speakerBtn.querySelector('.frontir-dock-label');
    if(label) label.textContent=m?'Muted':'Speaker';
    var circle=speakerBtn.querySelector('.frontir-dock-circle');
    if(circle){
      circle.textContent='';
      circle.appendChild(svgIcon(m?ICO.speakerOff:ICO.speaker,17));
    }
  }
  /* a second tab toggling the same preference */
  function watchMutePreference(){
    window.addEventListener('storage',function(e){
      if(!e||e.key===MUTE_KEY||e.key===null) syncSpeakerBtn();
    });
  }

  function buildConsole(){
    if(console_) return;
    console_=el('section','frontir-console');
    console_.id='frontirConsole';
    console_.hidden=true;
    console_.setAttribute('role','dialog');
    console_.setAttribute('aria-modal','true');
    console_.setAttribute('aria-label','Voice session');
    console_.dataset.frontirState='idle';
    console_.dataset.frontirCards=
      localStorage.getItem('frontir-cards')==='hidden'?'hidden':'shown';

    var close=el('button','frontir-close');
    close.type='button';
    close.setAttribute('aria-label','Close voice session view');
    close.appendChild(svgIcon(ICO.close,15));
    close.addEventListener('click',closeConsole);
    console_.appendChild(close);

    /* stage */
    var stage=el('div','frontir-stage');
    stage.appendChild(el('h1','frontir-stage-title','Voice session'));
    var status=el('p','frontir-stage-status');
    status.appendChild(el('span','frontir-status-dot'));
    statusText=el('span',null,'Realtime ready');
    status.appendChild(statusText);
    stage.appendChild(status);

    orbBtn=el('button','frontir-orb');
    orbBtn.type='button';
    orbBtn.id='frontirOrb';
    orbBtn.setAttribute('aria-label','Start voice session');
    orbBtn.setAttribute('aria-pressed','false');
    var halo=el('span','frontir-orb-halo'); halo.setAttribute('aria-hidden','true');
    var sphere=el('span','frontir-orb-sphere'); sphere.setAttribute('aria-hidden','true');
    sphere.appendChild(el('span','frontir-orb-wave frontir-orb-wave--a'));
    sphere.appendChild(el('span','frontir-orb-wave frontir-orb-wave--b'));
    sphere.appendChild(el('span','frontir-orb-rim'));
    var speckle=el('span','frontir-orb-speckle'); speckle.setAttribute('aria-hidden','true');
    orbBtn.appendChild(halo);
    orbBtn.appendChild(sphere);
    orbBtn.appendChild(speckle);
    orbBtn.addEventListener('click',toggleSession);
    stage.appendChild(orbBtn);

    stateWord=el('p','frontir-stage-state','Ready');
    stateWord.setAttribute('role','status');
    stateWord.setAttribute('aria-live','polite');
    stateHint=el('p','frontir-stage-hint','Tap to start');
    stage.appendChild(stateWord);
    stage.appendChild(stateHint);
    console_.appendChild(stage);

    /* floating cards */
    var cards=el('div','frontir-cards');
    cards.appendChild(buildCard('context'));
    cards.appendChild(buildCard('goals'));
    console_.appendChild(cards);

    /* dock */
    var dock=el('div','frontir-dock');
    var row=el('div','frontir-dock-row');
    widgetsBtn=dockBtn('Widgets',ICO.grid,{aria:'Toggle context and goal cards'});
    widgetsBtn.setAttribute('aria-pressed',
      console_.dataset.frontirCards==='shown'?'true':'false');
    widgetsBtn.addEventListener('click',function(){
      var hidden=console_.dataset.frontirCards==='hidden';
      console_.dataset.frontirCards=hidden?'shown':'hidden';
      widgetsBtn.setAttribute('aria-pressed',hidden?'true':'false');
      try{ localStorage.setItem('frontir-cards',hidden?'shown':'hidden'); }catch(_){}
    });
    var transcriptBtn=dockBtn('Transcript',ICO.transcript,{aria:'Show conversation transcript'});
    transcriptBtn.addEventListener('click',function(){
      closeConsole();
      if(typeof window.switchPanel==='function') window.switchPanel('chat',{fromRailClick:true});
    });
    startBtn=dockBtn('Start session',ICO.mic,{primary:true,aria:'Start voice session'});
    startLabel=startBtn.querySelector('.frontir-dock-label');
    startBtn.addEventListener('click',toggleSession);
    speakerBtn=dockBtn('Speaker',ICO.speaker,{aria:'Mute speaker'});
    /* Toggle-button pattern: the accessible name stays the action ("Mute
       speaker") while aria-pressed carries the state; the visible label
       flips Speaker/Muted so the state is legible without a screen reader. */
    speakerBtn.setAttribute('aria-pressed','false');
    speakerBtn.addEventListener('click',function(){ setMuted(!muted()); });
    var settingsBtn=dockBtn('Settings',ICO.gear,{aria:'Open settings'});
    settingsBtn.addEventListener('click',function(){
      closeConsole();
      if(typeof window.switchPanel==='function') window.switchPanel('settings',{fromRailClick:true});
    });
    row.appendChild(widgetsBtn);
    row.appendChild(transcriptBtn);
    row.appendChild(startBtn);
    row.appendChild(speakerBtn);
    row.appendChild(settingsBtn);
    dock.appendChild(row);

    var wordmark=el('div','frontir-dock-wordmark');
    var imgLight=doc.createElement('img');
    imgLight.className='frontir-wordmark-light';
    imgLight.src='static/frontir-wordmark.png';
    imgLight.alt='';
    var imgInk=doc.createElement('img');
    imgInk.className='frontir-wordmark-ink';
    imgInk.src='static/frontir-wordmark-ink.png';
    imgInk.alt='';
    wordmark.appendChild(imgLight);
    wordmark.appendChild(imgInk);
    wordmark.appendChild(el('span',null,'Sentry'));
    dock.appendChild(wordmark);
    console_.appendChild(dock);

    console_.addEventListener('keydown',onConsoleKeydown);
    doc.body.appendChild(console_);
  }

  /* keyboard: Escape closes; Tab stays inside the dialog                  */
  function onConsoleKeydown(e){
    if(e.key==='Escape'){ e.preventDefault(); closeConsole(); return; }
    if(e.key!=='Tab') return;
    var focusables=Array.prototype.filter.call(
      console_.querySelectorAll('button:not([disabled])'),
      function(b){ return b.offsetParent!==null||b===doc.activeElement; }
    );
    if(!focusables.length) return;
    var first=focusables[0], last=focusables[focusables.length-1];
    if(e.shiftKey&&doc.activeElement===first){ e.preventDefault(); last.focus(); }
    else if(!e.shiftKey&&doc.activeElement===last){ e.preventDefault(); first.focus(); }
  }

  function openConsole(){
    buildConsole();
    if(!console_.hidden) return;
    lastFocus=doc.activeElement;
    console_.hidden=false;
    refreshAvailability();
    refreshState();
    refreshCards();
    syncSpeakerBtn();
    markNavActive(navVoiceBtn);
    if(orbBtn) orbBtn.focus({preventScroll:true});
    if(refreshTimer) clearInterval(refreshTimer);
    refreshTimer=setInterval(refreshCards,10000);   // only while open
  }
  function closeConsole(){
    if(!console_||console_.hidden) return;
    console_.hidden=true;
    markNavActive(null);
    if(refreshTimer){ clearInterval(refreshTimer); refreshTimer=null; }
    if(lastFocus&&typeof lastFocus.focus==='function'){
      try{ lastFocus.focus({preventScroll:true}); }catch(_){}
    }
    lastFocus=null;
  }

  /* ── 5. Voice-mode integration (passive observation) ────────────────── */
  function realtimeAvailable(){
    /* boot.js only exposes _voiceModeActive when SpeechRecognition AND
       speechSynthesis both exist — exactly the availability we surface.  */
    return typeof window._voiceModeActive==='function';
  }
  function voiceActive(){
    try{ return realtimeAvailable()&&!!window._voiceModeActive(); }
    catch(_){ return false; }
  }
  function toggleSession(){
    if(!realtimeAvailable()) return;
    var b=byId('btnVoiceMode');
    if(b) b.click();          // boot.js owns activate/deactivate
  }
  function currentVoiceState(){
    if(!voiceActive()) return 'idle';
    var ind=byId('voiceModeIndicator');
    var cls=ind?ind.className:'';
    if(/listening/.test(cls)) return 'listening';
    if(/thinking/.test(cls))  return 'thinking';
    if(/speaking/.test(cls))  return 'speaking';
    return 'listening';       // active but between turns
  }
  var STATE_COPY={
    idle:      {word:'Ready',     hint:'Tap to start'},
    listening: {word:'Listening', hint:'Pause to send'},
    thinking:  {word:'Thinking',  hint:'Working on it'},
    speaking:  {word:'Speaking',  hint:'Tap to end'}
  };
  function refreshAvailability(){
    if(!console_) return;
    var ok=realtimeAvailable();
    console_.dataset.frontirAvail=ok?'ready':'unavailable';
    if(statusText) statusText.textContent=ok?'Realtime ready':'Realtime unavailable';
    if(orbBtn) orbBtn.disabled=!ok;
    if(startBtn) startBtn.disabled=!ok;
    if(!ok&&stateHint) stateHint.textContent='Voice needs browser speech support';
  }
  function refreshState(){
    if(!console_) return;
    var s=currentVoiceState();
    if(console_.dataset.frontirState===s) return;
    console_.dataset.frontirState=s;
    var copy=STATE_COPY[s];
    if(stateWord) stateWord.textContent=copy.word;
    if(stateHint&&realtimeAvailable()) stateHint.textContent=copy.hint;
    var active=s!=='idle';
    if(orbBtn){
      orbBtn.setAttribute('aria-pressed',active?'true':'false');
      orbBtn.setAttribute('aria-label',active?'End voice session':'Start voice session');
    }
    if(startBtn){
      startBtn.classList.toggle('is-live',active);
      startBtn.setAttribute('aria-label',active?'End voice session':'Start voice session');
      if(startLabel) startLabel.textContent=active?'End session':'Start session';
    }
  }
  function watchVoiceMode(){
    var ind=byId('voiceModeIndicator');
    var modeBtn=byId('btnVoiceMode');
    var mo=new MutationObserver(function(){
      refreshState();
      /* boot.js installs/restores its autoReadLastAssistant override on
         exactly these transitions, so re-assert the mute wrapper here.   */
      guardAutoRead();
      /* auto-surface the console when a session starts under this skin   */
      if(skinActive()&&voiceActive()&&(!console_||console_.hidden)) openConsole();
    });
    if(ind) mo.observe(ind,{attributes:true,attributeFilter:['class']});
    if(modeBtn) mo.observe(modeBtn,{attributes:true,attributeFilter:['class']});
  }

  /* ── 6. Card data (read-only, defensive) ────────────────────────────── */
  function textOf(sel){
    var n=doc.querySelector(sel);
    var t=n?(n.textContent||'').trim():'';
    return t||'';
  }
  function refreshCards(){
    if(!console_||console_.hidden) return;
    var S_=window.S||{};
    var ctx=doc.querySelector('[data-frontir-rows="context"]');
    if(ctx){
      ctx.textContent='';
      var project=textOf('#composerWorkspaceLabel')||'Default';
      var focus=(S_.session&&S_.session.title)||'New session';
      var fileCount=doc.querySelectorAll('#fileTree .file-item').length;
      var recent=textOf('#sessionList .session-time')||'—';
      var dir=(S_.currentDir&&S_.currentDir!=='.')?S_.currentDir:'~';
      ctx.appendChild(cardRow('Project',project));
      ctx.appendChild(cardRow('Focus',focus));
      ctx.appendChild(cardRow('Files',fileCount?String(fileCount)+' in tree':'—',true));
      ctx.appendChild(cardRow('Recent',recent,true));
      ctx.appendChild(cardRow('Workspace',dir,true));
    }
    var goals=doc.querySelector('[data-frontir-rows="goals"]');
    if(goals){
      goals.textContent='';
      var todos=Array.isArray(S_.todos)?S_.todos:[];
      var shown=0;
      for(var i=0;i<todos.length&&shown<4;i++){
        var td=todos[i]||{};
        if(td.status==='completed') continue;
        var label=td.status==='in_progress'?'In progress':'Queued';
        var body=td.content!=null?td.content:(td.text!=null?td.text:'');
        if(!body) continue;
        goals.appendChild(cardRow(label,String(body)));
        shown++;
      }
      if(!shown){
        var empty=el('div','frontir-card-row');
        empty.appendChild(el('span','frontir-card-empty','Nothing on watch. Goals from the active task appear here.'));
        goals.appendChild(empty);
      }
    }
  }

  /* ── 7. Card drag (pointer, handle-only, clamped, persisted) ────────── */
  function enableDrag(card,handle,kind){
    var key='frontir-card-pos-'+kind;
    function apply(dx,dy){
      card.style.transform='translate('+dx+'px,'+dy+'px)';
    }
    function clamp(dx,dy){
      var r=card.getBoundingClientRect();
      var baseX=r.left-currentDx, baseY=r.top-currentDy;
      var minDx=8-baseX, maxDx=window.innerWidth-r.width-8-baseX;
      var minDy=8-baseY, maxDy=window.innerHeight-r.height-8-baseY;
      return [Math.min(Math.max(dx,minDx),Math.max(minDx,maxDx)),
              Math.min(Math.max(dy,minDy),Math.max(minDy,maxDy))];
    }
    var currentDx=0,currentDy=0;
    try{
      var saved=JSON.parse(localStorage.getItem(key)||'null');
      if(saved&&typeof saved.dx==='number'&&typeof saved.dy==='number'&&
         Math.abs(saved.dx)<window.innerWidth&&Math.abs(saved.dy)<window.innerHeight){
        currentDx=saved.dx; currentDy=saved.dy; apply(currentDx,currentDy);
      }
    }catch(_){}
    var startX=0,startY=0,fromDx=0,fromDy=0,dragging=false;
    handle.addEventListener('pointerdown',function(e){
      if(getComputedStyle(card).position!=='fixed') return;  // stacked layout
      dragging=true;
      card.classList.add('dragging');
      startX=e.clientX; startY=e.clientY; fromDx=currentDx; fromDy=currentDy;
      try{ handle.setPointerCapture(e.pointerId); }catch(_){}
      e.preventDefault();
    });
    handle.addEventListener('pointermove',function(e){
      if(!dragging) return;
      var next=clamp(fromDx+(e.clientX-startX),fromDy+(e.clientY-startY));
      currentDx=next[0]; currentDy=next[1];
      apply(currentDx,currentDy);
    });
    function endDrag(){
      if(!dragging) return;
      dragging=false;
      card.classList.remove('dragging');
      try{ localStorage.setItem(key,JSON.stringify({dx:currentDx,dy:currentDy})); }catch(_){}
    }
    handle.addEventListener('pointerup',endDrag);
    handle.addEventListener('pointercancel',endDrag);
  }

  /* ── 8. Boot ─────────────────────────────────────────────────────────── */
  function init(){
    registerSkin();
    rebrandAssistantName();
    injectSidebar();
    watchProjectBar();
    guardAutoRead();
    watchMutePreference();
    watchVoiceMode();
    /* keep the user chip in sync with profile changes (cheap observer)   */
    var chipSrc=byId('profileChipLabel');
    if(chipSrc){
      new MutationObserver(syncUserChip)
        .observe(chipSrc,{childList:true,characterData:true,subtree:true});
    }
    /* clear our nav active state when any core nav tab is used           */
    doc.addEventListener('click',function(e){
      if(e.target&&e.target.closest&&e.target.closest('.nav-tab')) markNavActive(null);
    },true);
  }

  if(doc.readyState==='loading') doc.addEventListener('DOMContentLoaded',init);
  else init();
})();

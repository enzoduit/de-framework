// ── DIGITAL EMPLOYEES TAB ──────────────────────────────────────────────────
let deSelectedDE=null,deSelectedSession=null,deRefreshTimer=null;
function deStopRefresh(){if(deRefreshTimer){clearInterval(deRefreshTimer);deRefreshTimer=null;}}
function deStartRefresh(name,sid){
  deStopRefresh();
  deRefreshTimer=setInterval(async()=>{
    try{
      const r=await fetch(`/de/${name}/sessions/${sid}`);const s=await r.json();
      const c=document.getElementById('de-steps-container');
      if(c)c.innerHTML=(s.steps||[]).map(step=>deRenderStep(step)).join('');
      const si={complete:'✅',paused_human:'⏳',running:'🔄',error:'❌',paused_colleague:'💬',queued:'📋',max_iterations_reached:'🔄'};
      const hdr=document.getElementById('de-session-status');
      if(hdr)hdr.textContent=si[s.status]||'◌';
      if(s.status!=='running'&&s.status!=='queued'){deStopRefresh();const ind=document.getElementById('de-live-indicator');if(ind)ind.style.display='none';deSelect(deSelectedDE);}
    }catch(e){}
  },3000);
}

async function deInit(){await deLoadList();}

async function deLoadList(){
  try{
    const r=await fetch('/de-list');const d=await r.json();
    const des=d.des||[];
    const c=document.getElementById('de-list-cards');if(!c)return;
    c.innerHTML=des.map(de=>`
      <div class="de-card" id="de-card-${de.name}" onclick="deSelect('${de.name}')">
        <div class="de-dot" style="background:${de.color||'#FF4500'}"></div>
        <div style="min-width:0">
          <div class="mono" style="font-size:11px;font-weight:700;color:var(--text)">${de.display_name||de.name.toUpperCase()}</div>
          <div style="font-size:10px;color:var(--text-muted);line-height:1.3;margin-top:1px">${(de.role||'').substring(0,30)}</div>
          ${(de.pending_decisions||0)>0?`<div style="font-size:9px;color:var(--orange);margin-top:2px">⚠ ${de.pending_decisions} pending</div>`:''}
          ${de.last_session?`<div style="font-size:9px;color:var(--text-muted);margin-top:2px">${deTimeAgo(de.last_session.created_at)}</div>`:''}
        </div>
      </div>`).join('');
  }catch(e){const c=document.getElementById('de-list-cards');if(c)c.innerHTML='<div style="color:var(--red);font-size:10px;padding:8px">Failed to load</div>';}
}

// mdToHtml: minimal markdown → HTML
function mdToHtml(text){
  if(!text)return'';
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/^# (.+)$/gm,'<div style="font-size:13px;font-weight:700;color:var(--text);margin:8px 0 4px">$1</div>')
    .replace(/^## (.+)$/gm,'<div style="font-size:12px;font-weight:600;color:var(--text-sec);margin:6px 0 3px">$1</div>')
    .replace(/^---$/gm,'<hr style="border:none;border-top:1px solid var(--border);margin:8px 0">')
    .replace(/^[\*\-] (.+)$/gm,'<div style="padding-left:12px">· $1</div>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/`(.+?)`/g,'<code style="background:var(--surface2);border-radius:3px;padding:1px 4px;font-family:\'JetBrains Mono\',monospace;font-size:0.9em">$1</code>')
    .replace(/\n/g,'<br>');
}

async function deSelect(name){
  deStopRefresh();
  deSelectedDE=name;deSelectedSession=null;
  document.querySelectorAll('.de-card').forEach(c=>c.classList.remove('active'));
  const card=document.getElementById('de-card-'+name);if(card)card.classList.add('active');
  const center=document.getElementById('de-center-pane');
  const profile=document.getElementById('de-profile-pane');
  if(center)center.innerHTML='<div style="color:var(--text-muted);font-size:11px;padding:20px">Loading...</div>';
  if(profile)profile.innerHTML='<div style="color:var(--text-muted);font-size:11px;padding:20px">Loading...</div>';
  try{
    const r=await fetch('/de/'+name);const de=await r.json();
    deRenderCenter(name,de.sessions||de.recent_sessions||[]);
    deRenderProfilePane(de);
  }catch(e){
    if(center)center.innerHTML=`<div style="color:var(--red);padding:20px">Error: ${e.message}</div>`;
  }
  // On mobile: auto-switch to sessions pane after selecting a DE
  if(window.innerWidth<=767)deMobileShowPane('sessions');
}

function deRenderCenter(deName,sessions){
  const center=document.getElementById('de-center-pane');if(!center)return;
  const si={complete:'✅',paused_human:'⏳',running:'🔄',error:'❌',paused_colleague:'💬',queued:'📋',max_iterations_reached:'🔄'};
  const sessionCards=sessions.length
    ? sessions.map(s=>`
        <div class="de-session-card" id="de-sc-${s.id}" onclick="deLoadSession('${deName}','${s.id}')">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-size:13px">${si[s.status]||'◌'}</span>
            <span class="mono" style="font-size:9px;color:var(--text-muted)">${deTimeAgo(s.created_at)}</span>
          </div>
          <div style="font-size:10px;color:var(--text-muted);margin-top:3px">${s.trigger_type||'cron'} · ${s.step_count||0} steps</div>
          ${s.summary?`<div style="font-size:11px;color:var(--text-sec);margin-top:4px;line-height:1.4">${s.summary.substring(0,70)}${s.summary.length>70?'…':''}</div>`:''}
        </div>`).join('')
    : '<div style="color:var(--text-muted);font-size:11px;padding:16px">No sessions yet. Click ▶ START to begin.</div>';
  center.innerHTML=`
    <div class="de-center-header">
      <span class="mono" style="flex:1;font-size:11px;font-weight:700;color:var(--text)">${deName.toUpperCase()}</span>
      <button class="de-start-btn" id="de-start-btn" onclick="deStartSession()">▶ START</button>
      <button class="de-new-btn" id="de-new-btn" onclick="deNewSession()">＋ NEW SESSION</button>
    </div>
    <div id="de-new-session-area" style="display:none">
      <div class="de-new-session-form">
        <div class="mono" style="font-size:10px;color:var(--text-muted);margin-bottom:8px">Message to ${deName.toUpperCase()}:</div>
        <textarea id="de-new-session-msg" rows="3" placeholder="Describe what you need..."></textarea>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button onclick="deNewSessionCancel()" style="flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-sec);cursor:pointer">Cancel</button>
          <button onclick="deNewSessionSend('${deName}')" style="flex:2;background:var(--orange);border:none;border-radius:6px;padding:8px;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:#fff;cursor:pointer">▶ Send</button>
        </div>
      </div>
    </div>
    <div id="de-session-list" style="flex:1;overflow-y:auto">${sessionCards}</div>`;
}

function deRenderProfilePane(de){
  const profile=document.getElementById('de-profile-pane');if(!profile)return;
  const profileContent=`
    <div style="margin-bottom:16px">
      <div class="mono" style="font-size:9px;color:var(--text-muted);letter-spacing:0.1em">${de.role||''}</div>
      <div style="font-size:18px;font-weight:700;color:${de.color||'var(--orange)'};margin:4px 0 2px">${de.display_name||de.name?.toUpperCase()}</div>
    </div>
    <div class="section-label">MISSION</div>
    <p style="font-size:12px;color:var(--text-sec);line-height:1.7;margin-bottom:16px">${de.mission||'—'}</p>
    <div class="section-label">KPIs</div>
    <ul style="font-size:11px;color:var(--text-sec);padding-left:14px;margin-bottom:16px;line-height:1.8">${(de.kpis||[]).map(k=>`<li>${k}</li>`).join('')}</ul>
    <div class="section-label">AUTONOMY</div>
    <div style="margin-bottom:16px">
      ${deLevel('Level 0 — No Approval','#22c55e',de.responsibilities?.level_0||[])}
      ${deLevel('Level 1 — Do + Document','#FFC800',de.responsibilities?.level_1||[])}
      ${deLevel('Level 2 — Approval Required','#FF4500',de.responsibilities?.level_2||[])}
    </div>
    ${(de.hard_constraints||[]).length?`<div class="section-label">HARD CONSTRAINTS</div><ul style="font-size:11px;color:var(--red);padding-left:14px;margin-bottom:16px;line-height:1.8">${de.hard_constraints.map(c=>`<li>${c}</li>`).join('')}</ul>`:''}
    <div class="section-label">TRIGGERS</div>
    <div style="margin-bottom:16px">${(de.triggers||[]).map(t=>`<div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px"><div class="mono" style="font-size:9px;color:var(--orange);letter-spacing:0.1em;margin-bottom:3px">${(t.type||'').toUpperCase()}</div><div style="font-size:11px;color:var(--text)">${t.schedule||t.description||''}</div>${t.schedule&&t.description?`<div style="font-size:10px;color:var(--text-muted);margin-top:2px">${t.description}</div>`:''}</div>`).join('')}</div>
    <div class="section-label">COLLEAGUES</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px">${(de.colleagues||[]).map(c=>`<span style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:3px 8px;font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--text-muted)">${c.toUpperCase()}</span>`).join('')}</div>
    <div class="section-label">DATA SOURCES</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-muted);margin-bottom:16px;line-height:1.8">${(de.data_sources||[]).map(s=>`<div>· ${s}</div>`).join('')}</div>`;
  const workspaceContent=`<div id="de-workspace-body"><div style="color:var(--text-muted);font-size:12px">Loading workspace...</div></div>`;
  profile.innerHTML=`
    <div class="de-profile-tabs">
      <div class="de-profile-tab active" id="de-ptab-profile" onclick="deProfileTab('profile')">PROFILE</div>
      <div class="de-profile-tab" id="de-ptab-workspace" onclick="deProfileTab('workspace')">WORKSPACE</div>
    </div>
    <div id="de-profile-content-profile" class="de-profile-body">${profileContent}</div>
    <div id="de-profile-content-workspace" class="de-profile-body" style="display:none">${workspaceContent}</div>`;
}

function deProfileTab(tab){
  document.querySelectorAll('.de-profile-tab').forEach(t=>t.classList.remove('active'));
  const activeTab=document.getElementById('de-ptab-'+tab);
  if(activeTab)activeTab.classList.add('active');
  ['profile','workspace'].forEach(t=>{
    const el=document.getElementById('de-profile-content-'+t);
    if(el)el.style.display=t===tab?'block':'none';
  });
  if(tab==='workspace'&&deSelectedDE)deRenderWorkspace(deSelectedDE);
}

async function deLoadSession(deName,sessionId){
  deSelectedSession=sessionId;
  document.querySelectorAll('.de-session-card').forEach(c=>c.classList.remove('active'));
  const sc=document.getElementById('de-sc-'+sessionId);if(sc)sc.classList.add('active');
  const center=document.getElementById('de-center-pane');
  if(center)center.innerHTML='<div style="padding:20px;color:var(--text-muted);font-size:11px">Loading session...</div>';
  try{
    const r=await fetch(`/de/${deName}/sessions/${sessionId}`);const s=await r.json();
    const si={complete:'✅',paused_human:'⏳',running:'🔄',error:'❌',paused_colleague:'💬',queued:'📋',max_iterations_reached:'🔄'};
    const isLive=s.status==='running'||s.status==='queued';
    if(isLive)deStartRefresh(deName,sessionId);
    if(center)center.innerHTML=`
      <div class="de-center-header">
        <button onclick="deStopRefresh();deBackToList()" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:18px;padding:0;line-height:1">←</button>
        <div style="flex:1;min-width:0;margin-left:8px">
          <div class="mono" style="font-size:9px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.id||sessionId}</div>
          <div style="font-size:12px;margin-top:2px"><span id="de-session-status">${si[s.status]||'◌'}</span> <strong>${s.trigger_type||'cron'}</strong> · ${(s.steps||[]).length} steps · ${deTimeAgo(s.created_at)}</div>
        </div>
        ${isLive?'<span id="de-live-indicator" style="background:var(--red);color:#fff;font-size:9px;font-family:monospace;font-weight:700;padding:3px 8px;border-radius:4px;letter-spacing:0.08em;animation:pulse 1.5s infinite">🔴 LIVE</span>':''}
      </div>
      <div style="overflow-y:auto;flex:1;padding:16px">
        ${s.trigger_context?`<div style="font-size:11px;color:var(--text-muted);margin-bottom:16px;padding:8px 12px;background:var(--surface);border-radius:6px">${s.trigger_context}</div>`:''}
        <div id="de-steps-container">${(s.steps||[]).map(step=>deRenderStep(step)).join('')}</div>
        ${!s.steps||!s.steps.length?'<div style="color:var(--text-muted);font-size:11px">No steps recorded yet.</div>':''}
      </div>`;
  }catch(e){if(center)center.innerHTML=`<div style="color:var(--red);padding:20px">Error: ${e.message}</div>`;}
}

function deBackToList(){
  if(deSelectedDE)deSelect(deSelectedDE);
}

function deRenderStep(step){
  const cfg={
    trigger:{label:'TRIGGER',color:'#6366F1',bg:'rgba(99,102,241,0.08)'},
    reasoning:{label:'THINKING',color:'#888',bg:'rgba(255,255,255,0.03)'},
    action:{label:'ACTION',color:'#FF4500',bg:'rgba(255,69,0,0.08)'},
    observation:{label:'RESULT',color:'#22c55e',bg:'rgba(34,197,94,0.08)'},
    decision_request:{label:'⏳ DECISION NEEDED',color:'#FFC800',bg:'rgba(255,200,0,0.08)'},
    decision_response:{label:'✓ DECIDED',color:'#22c55e',bg:'rgba(34,197,94,0.06)'},
    colleague_request:{label:'💬 ASKING',color:'#a855f7',bg:'rgba(168,85,247,0.08)'},
    colleague_response:{label:'💬 REPLY',color:'#a855f7',bg:'rgba(168,85,247,0.05)'},
    complete:{label:'✅ COMPLETE',color:'#22c55e',bg:'rgba(34,197,94,0.06)'},
  };
  const c=cfg[step.type]||{label:(step.type||'STEP').toUpperCase(),color:'var(--text-muted)',bg:'var(--surface)'};
  const ts=step.ts?new Date(step.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
  let body='';
  if(step.type==='trigger'||step.type==='reasoning'){
    if(step.content){
      const rendered=mdToHtml(step.content.substring(0,600)+(step.content.length>600?'…':''));
      body+=step.type==='reasoning'
        ?`<div style="font-size:13px;color:var(--text-muted);line-height:1.7;font-style:italic">${rendered}</div>`
        :`<div style="font-size:13px;color:var(--text-sec);line-height:1.7">${rendered}</div>`;
    }
  }else if(step.type==='action'){
    if(step.tool)body+=`<div class="mono" style="font-size:12px;color:var(--orange);font-weight:700;margin-bottom:4px">→ ${step.tool}</div>`;
    if(step.input)body+=`<div class="mono" style="font-size:10px;color:var(--text-muted);word-break:break-all">${(typeof step.input==='string'?step.input:JSON.stringify(step.input,null,2)).substring(0,300)}</div>`;
    if(step.content)body+=`<div class="mono" style="font-size:11px;color:var(--text-sec);margin-top:6px;white-space:pre-wrap;word-break:break-word">${step.content.substring(0,400)}</div>`;
  }else if(step.type==='observation'){
    if(step.result){
      const isErr=step.result.toLowerCase().includes('error')||step.result.toLowerCase().includes('fail');
      body+=`<div class="mono" style="font-size:11px;color:${isErr?'var(--red)':'var(--green)'};margin-top:4px;white-space:pre-wrap;word-break:break-all">${step.result.substring(0,400)}${step.result.length>400?'…':''}</div>`;
    }
    if(step.content&&!step.result)body+=`<div style="font-size:12px;color:var(--text-sec);margin-top:4px">${step.content.substring(0,400)}</div>`;
  }else{
    if(step.content)body+=`<div style="font-size:12px;color:var(--text-sec);line-height:1.6;white-space:pre-wrap;word-break:break-word">${step.content.substring(0,400)}${step.content.length>400?'…':''}</div>`;
    if(step.tool)body+=`<div class="mono" style="font-size:11px;color:${c.color};margin-top:6px">→ ${step.tool}</div>`;
    if(step.input)body+=`<div class="mono" style="font-size:10px;color:var(--text-muted);margin-top:3px;word-break:break-all">${(typeof step.input==='string'?step.input:JSON.stringify(step.input)).substring(0,200)}</div>`;
    if(step.result)body+=`<div style="font-size:11px;color:var(--text-sec);margin-top:5px;border-top:1px solid rgba(255,255,255,0.05);padding-top:5px">${step.result.substring(0,300)}${step.result.length>300?'…':''}</div>`;
  }
  if(step.summary)body+=`<div style="font-size:12px;color:var(--text);margin-top:5px;font-style:italic">${step.summary.substring(0,300)}</div>`;
  if(step.colleague)body+=`<div style="font-size:12px;color:#a855f7;margin-top:5px">→ ${step.colleague}: ${(step.message||'').substring(0,120)}</div>`;
  if(step.title)body+=`<div style="font-size:12px;color:var(--yellow);margin-top:4px;font-weight:600">${step.title}</div>`;
  return`<div class="de-step" style="border-color:${c.color};background:${c.bg}">
    <div style="display:flex;justify-content:space-between;margin-bottom:6px">
      <span class="de-step-label" style="color:${c.color}">${c.label}</span>
      <span class="mono" style="font-size:9px;color:var(--text-muted)">${ts}</span>
    </div>${body}</div>`;
}

async function deStartSession(){
  if(!deSelectedDE)return;
  const btn=document.getElementById('de-start-btn');
  if(btn){btn.disabled=true;btn.textContent='...';}
  try{
    const r=await fetch('/de-start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({de_name:deSelectedDE,trigger_type:'user',trigger_context:'Manual session started by Ed via portal'})});
    const d=await r.json();
    if(d.ok){
      if(btn){btn.textContent='✅ QUEUED';setTimeout(()=>{btn.textContent='▶ START';btn.disabled=false;},3000);}
      setTimeout(()=>deSelect(deSelectedDE),2000);
    }else{if(btn){btn.textContent='❌ ERR: '+(d.error||'unknown');setTimeout(()=>{btn.textContent='▶ START';btn.disabled=false;},3000);}}
  }catch(e){if(btn){btn.textContent='❌ '+e.message.substring(0,20);setTimeout(()=>{btn.textContent='▶ START';btn.disabled=false;},3000);}}
}

function deNewSession(){
  const area=document.getElementById('de-new-session-area');
  if(area){area.style.display=area.style.display==='none'?'block':'none';}
}

function deNewSessionCancel(){
  const area=document.getElementById('de-new-session-area');
  if(area)area.style.display='none';
  const msg=document.getElementById('de-new-session-msg');
  if(msg)msg.value='';
}

async function deNewSessionSend(deName){
  const msg=document.getElementById('de-new-session-msg');
  const text=(msg?msg.value:'').trim();
  if(!text)return;
  const sendBtn=document.querySelector('#de-new-session-area button:last-child');
  if(sendBtn){sendBtn.disabled=true;sendBtn.textContent='Sending...';}
  try{
    const r=await fetch('/de-start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({de_name:deName,trigger_type:'user_message',trigger_context:text})});
    const d=await r.json();
    const area=document.getElementById('de-new-session-area');
    if(d.ok){
      if(area)area.innerHTML='<div style="padding:14px;font-family:\'JetBrains Mono\',monospace;font-size:11px;color:var(--green)">✅ Queued</div>';
      setTimeout(()=>{if(area)area.style.display='none';deSelect(deName);},2000);
    }else{
      if(sendBtn){sendBtn.disabled=false;sendBtn.textContent='▶ Send';}
      alert('Error: '+(d.error||'unknown'));
    }
  }catch(e){if(sendBtn){sendBtn.disabled=false;sendBtn.textContent='▶ Send';}alert('Error: '+e.message);}
}

function deRenderWorkspace(deName) {
  fetch(`/de/${deName}/workspace`)
    .then(r => r.json())
    .then(data => {
      const files = data.files || [];
      const container = document.getElementById('de-workspace-body');
      if (!container) return;
      container.innerHTML = `
        <div style="margin-bottom:16px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="file" id="de-upload-input" style="display:none" onchange="deUploadFile('${deName}')">
            <button onclick="document.getElementById('de-upload-input').click()" style="background:var(--orange);border:none;color:#fff;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;padding:6px 12px;border-radius:6px;cursor:pointer">＋ UPLOAD FILE</button>
            <span id="de-upload-status" style="font-size:10px;color:var(--text-muted)"></span>
          </label>
        </div>
        ${files.length === 0
          ? '<div style="color:var(--text-muted);font-size:11px">No files yet. Upload files to share with this DE.</div>'
          : files.map(f => `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
              <div>
                <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text)">${f.name}</div>
                <div style="font-size:10px;color:var(--text-muted)">${f.size_kb}KB · ${f.modified}</div>
              </div>
              <button onclick="deViewFile('${deName}','${f.name}')" style="font-size:9px;font-family:'JetBrains Mono',monospace;color:var(--text-muted);background:none;padding:4px 10px;border:1px solid var(--border);border-radius:4px;cursor:pointer">👁 VIEW</button>
            </div>
          `).join('')
        }
      `;
    })
    .catch(e => {
      const c = document.getElementById('de-workspace-body');
      if (c) c.innerHTML = `<div style="color:var(--text-muted);font-size:11px">Workspace unavailable</div>`;
    });
}

async function deUploadFile(deName) {
  const input = document.getElementById('de-upload-input');
  const status = document.getElementById('de-upload-status');
  if (!input || !input.files[0]) return;
  const file = input.files[0];
  if (status) status.textContent = 'Uploading...';
  const form = new FormData();
  form.append('file', file);
  try {
    const r = await fetch(`/de/${deName}/workspace/upload`, {method:'POST', body: form});
    const d = await r.json();
    if (status) status.textContent = d.ok ? '✅ Uploaded' : '❌ ' + (d.error || 'Error');
    if (d.ok) setTimeout(() => deRenderWorkspace(deName), 500);
  } catch(e) {
    if (status) status.textContent = '❌ ' + e.message;
  }
}

function deLevel(title,color,items){
  if(!items.length)return'';
  return`<div style="margin-bottom:10px"><div style="font-size:10px;color:${color};font-weight:600;margin-bottom:4px">${title}</div><ul style="font-size:11px;color:var(--text-sec);padding-left:14px;line-height:1.7;margin:0">${items.map(i=>`<li>${i}</li>`).join('')}</ul></div>`;
}

function deTimeAgo(iso){
  if(!iso)return'';
  const diff=Date.now()-new Date(iso).getTime();
  if(diff<0)return'just now';
  const m=Math.floor(diff/60000),h=Math.floor(diff/3600000),d=Math.floor(diff/86400000);
  if(d>0)return d+'d ago';if(h>0)return h+'h ago';if(m>0)return m+'m ago';return'just now';
}
// ── File viewer popup ─────────────────────────────────────────────────────
function deViewFile(deName, filename) {
  let modal = document.getElementById('de-file-viewer');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'de-file-viewer';
    modal.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.88);z-index:9999;align-items:center;justify-content:center;padding:16px;box-sizing:border-box';
    modal.innerHTML = `
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;width:min(840px,100%);max-height:88vh;display:flex;flex-direction:column;overflow:hidden">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--surface2)">
          <div class="mono" style="font-size:12px;font-weight:700;color:var(--text)" id="de-fv-name"></div>
          <div style="display:flex;gap:8px;align-items:center">
            <span id="de-fv-size" style="font-size:10px;color:var(--text-muted)"></span>
            <button onclick="document.getElementById('de-file-viewer').style.display='none'" style="background:none;border:none;color:var(--text-muted);font-size:22px;cursor:pointer;padding:0;line-height:1">×</button>
          </div>
        </div>
        <pre id="de-fv-content" style="padding:20px;overflow:auto;flex:1;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-sec);line-height:1.7;white-space:pre-wrap;word-break:break-word;margin:0;background:var(--bg)"></pre>
      </div>`;
    modal.addEventListener('click', e => { if(e.target===modal) modal.style.display='none'; });
    document.body.appendChild(modal);
  }
  document.getElementById('de-fv-name').textContent = filename;
  document.getElementById('de-fv-size').textContent = '';
  document.getElementById('de-fv-content').textContent = 'Loading...';
  modal.style.display = 'flex';
  fetch(`/de/${deName}/workspace/${encodeURIComponent(filename)}`)
    .then(r => r.json())
    .then(d => {
      document.getElementById('de-fv-content').textContent = d.content || '[Empty file]';
      document.getElementById('de-fv-size').textContent = d.size_kb ? d.size_kb + 'KB' : '';
    })
    .catch(e => { document.getElementById('de-fv-content').textContent = 'Error: ' + e.message; });
}

// ── Mobile pane navigation ───────────────────────────────────────────
function deMobileShowPane(pane) {
  const isMobile = window.innerWidth <= 767;
  if (!isMobile) return;
  const map = {agents: '.de-sidebar', sessions: '#de-center-pane', profile: '#de-profile-pane'};
  document.querySelectorAll('.de-sidebar, #de-center-pane, #de-profile-pane').forEach(el => el.classList.remove('mobile-active'));
  const el = document.querySelector(map[pane]);
  if (el) el.classList.add('mobile-active');
  document.querySelectorAll('.de-mobile-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.pane === pane));
}

function deJumpToSession(deName, sessionId) {
  showTab('team');
  deInit();
  setTimeout(async () => {
    await deSelect(deName);
    setTimeout(() => deLoadSession(deName, sessionId), 600);
  }, 800);
}

// ── Profile pane resizer ────────────────────────────────────────────────────
(function(){
  let resizing=false,startX=0,startW=0;
  const KEY='de-profile-w';
  function init(){
    const handle=document.getElementById('de-resize-handle');
    const pane=document.getElementById('de-profile-pane');
    if(!handle||!pane)return;
    const saved=localStorage.getItem(KEY);
    if(saved)pane.style.width=parseInt(saved)+'px';
    handle.addEventListener('mousedown',e=>{
      resizing=true;startX=e.clientX;startW=pane.offsetWidth;
      handle.classList.add('dragging');
      document.body.style.cssText+='cursor:col-resize;user-select:none;';
      e.preventDefault();
    });
    document.addEventListener('mousemove',e=>{
      if(!resizing)return;
      const w=Math.min(620,Math.max(180,startW+(startX-e.clientX)));
      pane.style.width=w+'px';
    });
    document.addEventListener('mouseup',()=>{
      if(!resizing)return;
      resizing=false;
      handle.classList.remove('dragging');
      document.body.style.cursor='';
      document.body.style.userSelect='';
      localStorage.setItem(KEY,pane.offsetWidth);
    });
  }
  document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
})();
// ── END DIGITAL EMPLOYEES TAB ──────────────────────────────────────────────────

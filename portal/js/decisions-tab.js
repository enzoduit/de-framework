// ── DECISIONS TAB ──────────────────────────────────────────────────────────
async function loadDecisionsList() {
  var list = document.getElementById('decisions-list');
  if (!list) return;
  try {
    var r = await fetch('/decisions');
    var data = await r.json();
    var pending = data.pending || [];
    if (pending.length === 0) {
      list.innerHTML = '<div style="font-family:var(--font-mono);font-size:12px;color:#888;padding:12px;">No pending decisions · All clear ✓</div>';
      return;
    }
    var uc = {high:'#FF4444',medium:'#FFC800',low:'#888'};
    var html = '';
    for (var i = 0; i < pending.length; i++) {
      var d = pending[i];
      var agent = (d.agent||'?').toUpperCase();
      var title = (d.title||'').replace(/[\u23F3\u1F4A1\u26A0\uFE0F\u{1F680}-\u{1FFFF}]/gu,'').trim();
      var urgencyRaw = d.urgency;
      var urgency = typeof urgencyRaw === 'number'
        ? (urgencyRaw >= 2 ? 'high' : urgencyRaw === 1 ? 'medium' : 'low')
        : (urgencyRaw || 'medium');
      var color = uc[urgency]||'#888';
      var did = d.id||'';
      // Build full detail text
      var desc = d.description || '';
      var proposed = d.proposed_action || '';
      var impact = d.estimated_impact || d.impact || '';
      var detailHtml = '';
      if (proposed) detailHtml += '<div style="margin-top:8px;font-size:11px;color:#aaa;"><span style="color:#666;font-family:var(--font-mono);font-size:10px;">PROPOSED:</span><br>' + proposed.replace(/\n/g,'<br>') + '</div>';
      if (desc && desc !== proposed) detailHtml += '<div style="margin-top:6px;font-size:11px;color:#888;">' + desc.replace(/\n/g,'<br>') + '</div>';
      if (impact) detailHtml += '<div style="margin-top:6px;font-size:10px;color:#666;font-style:italic;">' + impact.replace(/\n/g,'<br>') + '</div>';

      html += '<div style="background:#141414;border:1px solid #1C1C1C;padding:12px 14px;margin-bottom:8px;" id="dec' + i + '">';
      // Header row: urgency + agent + title + expand + action buttons
      html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">';
      html += '<div style="min-width:0;flex:1;cursor:pointer;" onclick="toggleDecDetail(' + i + ')">';
      html += '<div style="font-family:var(--font-mono);font-size:10px;color:' + color + ';margin-bottom:3px;">' + urgency.toUpperCase() + ' · ' + agent + '</div>';
      html += '<div style="font-size:12px;color:#F0F0F0;">' + title + ' <span style="color:#555;font-size:10px;" id="dectog' + i + '">▼</span></div>';
      html += '</div>';
      html += '<div style="display:flex;gap:6px;flex-shrink:0;margin-top:2px;">';
      html += '<button data-id="' + did + '" data-action="approve" data-idx="' + i + '" onclick="qd(this.dataset.id,this.dataset.action,this.dataset.idx)" style="background:rgba(0,200,100,0.1);border:1px solid rgba(0,200,100,0.3);color:#00C864;font-family:var(--font-mono);font-size:10px;padding:5px 10px;cursor:pointer;">✓</button>';
      html += '<button data-id="' + did + '" data-action="reject" data-idx="' + i + '" onclick="qd(this.dataset.id,this.dataset.action,this.dataset.idx)" style="background:rgba(255,68,68,0.1);border:1px solid rgba(255,68,68,0.3);color:#FF4444;font-family:var(--font-mono);font-size:10px;padding:5px 10px;cursor:pointer;">✗</button>';
      if (d.session_id) { html += '<button onclick="deJumpToSession(\'' + (d.agent||'') + '\',\'' + d.session_id + '\')" style="background:none;border:1px solid var(--text-muted);color:var(--text-muted);font-family:\'JetBrains Mono\',monospace;font-size:9px;padding:5px 10px;cursor:pointer;margin-left:2px">→ SESSION</button>'; }
      html += '</div></div>';
      // Collapsible detail section (hidden by default)
      html += '<div id="decdetail' + i + '" style="display:none;border-top:1px solid #1C1C1C;margin-top:10px;padding-top:8px;">';
      html += detailHtml;
      html += '<div style="margin-top:10px;">';
      html += '<textarea id="decnote' + i + '" placeholder="Optional: conditions, instructions, context for the agent..." rows="2" style="width:100%;box-sizing:border-box;background:#0A0A0A;border:1px solid #2a2a2a;color:#ccc;font-family:var(--font-mono);font-size:11px;padding:8px;resize:vertical;outline:none;"></textarea>';
      html += '</div>';
      html += '</div>';
      html += '</div>';
    }
    list.innerHTML = html;
  } catch(e) {
    if (list) list.innerHTML = '<div style="font-family:var(--font-mono);font-size:12px;color:#888;padding:12px;">Error: ' + e.message + '</div>';
  }
}

function toggleDecDetail(i) {
  var el = document.getElementById('decdetail' + i);
  var tog = document.getElementById('dectog' + i);
  if (!el) return;
  var hidden = el.style.display === 'none';
  el.style.display = hidden ? 'block' : 'none';
  if (tog) tog.textContent = hidden ? '▲' : '▼';
}

async function qd(id, action, index) {
  var noteEl = document.getElementById('decnote' + index);
  var note = noteEl ? noteEl.value.trim() : '';
  var el = document.getElementById('dec' + index);
  if (el) el.style.opacity = '0.4';
  try {
    await fetch('/decide', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id, action: action, note: note})
    });
    var label = action === 'approve' ? '✓ APPROVED' : '✗ REJECTED';
    var color = action === 'approve' ? '#00C864' : '#FF4444';
    var noteDisplay = note ? '<div style="font-size:10px;color:#666;margin-top:4px;font-style:italic;">"' + note + '"</div>' : '';
    if (el) el.innerHTML = '<div style="font-family:var(--font-mono);font-size:11px;color:' + color + ';padding:8px;">' + label + noteDisplay + '</div>';
  } catch(e) { if (el) el.style.opacity = '1'; }
}
// ── END DECISIONS TAB ──────────────────────────────────────────────────────

// ═══════════════════════════════════════════════════════════════════════════
// EMAILS MODULE — inbox, sent, drafts, trash, all mail
// Prefix: _em
// ═══════════════════════════════════════════════════════════════════════════

let _emMessages = [];
let _emFolder = 'inbox';
let _emSearch = '';
let _emTotal = 0;
let _emAccounts = [];

// Account colour palette (cycles for multiple accounts)
const _EM_COLOURS = ['#185FA5','#3B6D11','#8a5a00','#A32D2D','#00695c','#7c3aed'];

async function pageEmails(folder) {
  _emFolder = folder || 'inbox';
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading…</div>';

  try {
    _emAccounts = await apiFetch('/api/accounts');
    await _emLoad();
  } catch(e) {
    mc.innerHTML = `<div class="state-error">Failed to load: ${esc(e.message)}</div>`;
  }
}

async function _emLoad() {
  const params = new URLSearchParams({ folder: _emFolder, limit: 200 });
  if (_emSearch) params.set('q', _emSearch);
  const data = await apiFetch('/api/emails?' + params);
  _emMessages = data.messages || [];
  _emTotal = data.total || 0;
  _emRender();
}

function _emRender() {
  const mc = document.getElementById('module-content');
  const msgs = _emMessages;

  mc.innerHTML = `
    <div class="em-toolbar">
      <input class="em-search" id="em-q" placeholder="Search messages…" value="${esc(_emSearch)}">
      <div class="em-filter-group" id="em-filters"></div>
      <button class="btn btn-primary btn-sm" onclick="composeNew()">✏ Compose</button>
    </div>
    <div class="em-list-panel">
      <div class="tbl-overflow-x">
        <table class="em-list-table">
          <thead><tr>
            <th style="width:14px"></th>
            <th>From</th>
            <th>Subject</th>
            <th style="min-width:260px">Preview</th>
            <th>Date</th>
            <th style="width:22px"></th>
          </tr></thead>
          <tbody id="em-tbody">
            ${msgs.length ? msgs.map(_emRow).join('') : `<tr><td colspan="6" class="em-empty">No messages</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
    <div class="mt-8">
      <span class="count-pill">${msgs.length} of ${_emTotal} message${_emTotal !== 1 ? 's' : ''}</span>
    </div>`;

  // Search
  const q = document.getElementById('em-q');
  if (q) {
    q.addEventListener('input', e => { _emSearch = e.target.value; _emLoad(); });
    q.addEventListener('keydown', e => { if (e.key === 'Escape') { _emSearch = ''; q.value = ''; _emLoad(); } });
  }
}

function _emRow(msg) {
  const acctIdx = _emAccounts.findIndex(a => a.id === msg.account_id);
  const colour = _EM_COLOURS[acctIdx >= 0 ? acctIdx % _EM_COLOURS.length : 0];
  const flags = msg.flags || '[]';
  const isUnread = !flags.includes('Seen');
  const unreadCls = isUnread ? ' unread' : '';

  const displayFrom = msg.from_name || msg.from_addr || '(unknown)';

  return `<tr class="em-row${unreadCls}" onclick="emOpen(${msg.id}, '${esc(msg.thread_id || '')}')">
    <td><span class="em-acct-dot" style="background:${colour}" title="${esc(msg.account_name || '')}"></span></td>
    <td class="em-from">${esc(displayFrom)}</td>
    <td class="em-subject">${esc(msg.subject || '(no subject)')}</td>
    <td class="em-snippet">${esc(msg.snippet || '')}</td>
    <td class="em-date">${fmtDate(msg.date)}</td>
    <td>${msg.has_attachments ? '<span class="em-att-icon" title="Has attachments">📎</span>' : ''}</td>
  </tr>`;
}

async function emOpen(msgId, threadId) {
  detOpen('');
  try {
    const msg = await apiFetch(`/api/emails/${msgId}`);
    document.getElementById('det-title').textContent = msg.subject || '(no subject)';
    _emRenderDetail(msg, threadId);
    // Trigger AI summary in background
    if (threadId) _emLoadSummary(threadId);
  } catch(e) {
    document.getElementById('det-body').innerHTML = `<div class="state-error">${esc(e.message)}</div>`;
  }
}

function _emRenderDetail(msg, threadId) {
  const toList = _emParseAddrs(msg.to_addrs);
  const toStr = toList.map(a => a.name ? `${a.name} <${a.addr}>` : a.addr).join(', ');
  const fromStr = msg.from_name ? `${msg.from_name} <${msg.from_addr}>` : msg.from_addr;

  const hasHtml = msg.body_html && msg.body_html.trim();

  document.getElementById('det-body').innerHTML = `
    <div class="ai-summary-box" id="ai-summary-box">
      <div class="ai-summary-label">✦ AI Summary</div>
      <div id="ai-summary-text"></div>
    </div>
    <div class="em-meta-strip">
      <div class="em-meta-row"><span class="em-meta-label">From</span><span class="em-meta-val">${esc(fromStr)}</span></div>
      <div class="em-meta-row"><span class="em-meta-label">To</span><span class="em-meta-val">${esc(toStr)}</span></div>
      <div class="em-meta-row"><span class="em-meta-label">Date</span><span class="em-meta-val">${fmtDate(msg.date)}</span></div>
    </div>
    ${hasHtml
      ? `<iframe class="em-body-frame" id="em-iframe" sandbox="allow-same-origin" style="height:500px"></iframe>`
      : `<pre class="em-body-text">${esc(msg.body_text || '(empty)')}</pre>`
    }`;

  if (hasHtml) {
    const iframe = document.getElementById('em-iframe');
    iframe.srcdoc = `<html><head><base target="_blank"><style>body{font-family:sans-serif;font-size:14px;line-height:1.6;color:#1A2E45;padding:12px}a{color:#185FA5}</style></head><body>${msg.body_html}</body></html>`;
    iframe.onload = () => {
      try { iframe.style.height = (iframe.contentWindow.document.body.scrollHeight + 40) + 'px'; } catch(e) {}
    };
  }

  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';

  // Reply button
  const replyBtn = document.createElement('button');
  replyBtn.className = 'btn btn-primary btn-sm';
  replyBtn.textContent = '↩ Reply';
  replyBtn.onclick = () => composeReply(msg);
  foot.appendChild(replyBtn);

  // AI Draft button
  const aiBtn = document.createElement('button');
  aiBtn.className = 'btn btn-outline btn-sm';
  aiBtn.textContent = '✦ Draft with AI';
  aiBtn.onclick = () => _emAiDraft(msg, threadId);
  foot.appendChild(aiBtn);

  // Forward button
  const fwdBtn = document.createElement('button');
  fwdBtn.className = 'btn btn-outline btn-sm';
  fwdBtn.textContent = '→ Forward';
  fwdBtn.onclick = () => composeForward(msg);
  foot.appendChild(fwdBtn);
}

async function _emLoadSummary(threadId) {
  try {
    const data = await fetch('/api/ai/summarise', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({thread_id: threadId}),
    }).then(r => r.json());
    if (data.ok && data.data && data.data.summary) {
      const box = document.getElementById('ai-summary-box');
      const txt = document.getElementById('ai-summary-text');
      if (box && txt) {
        txt.textContent = data.data.summary;
        box.classList.add('loaded');
      }
    }
  } catch(e) {}
}

async function _emAiDraft(msg, threadId) {
  const intent = prompt('Describe your reply in one line:\n(e.g. "Confirm the meeting", "Decline politely", "Ask for more info")');
  if (!intent) return;

  // Find account_id from current accounts
  const acct = _emAccounts.find(a => a.id === msg.account_id);
  try {
    const r = await fetch('/api/ai/draft', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        thread_id: threadId || msg.message_id,
        intent,
        account_id: msg.account_id,
      }),
    }).then(r => r.json());
    if (r.ok && r.data && r.data.draft) {
      composeReply(msg, r.data.draft);
    } else {
      toast(r.error || 'Draft failed', 'err');
    }
  } catch(e) {
    toast('AI draft failed: ' + e.message, 'err');
  }
}

function _emParseAddrs(json_str) {
  try { return JSON.parse(json_str || '[]'); } catch(e) { return []; }
}

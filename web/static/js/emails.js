// ═══════════════════════════════════════════════════════════════════════════
// EMAILS MODULE — inbox, sent, drafts, trash, all mail, folder view
// Prefix: _em
// ═══════════════════════════════════════════════════════════════════════════

let _emMessages      = [];
let _emFolder        = 'inbox';   // role name OR null when using _emFolderId
let _emFolderId      = null;      // specific folder id (overrides role)
let _emFolderName    = 'Inbox';
let _emSearch        = '';
let _emTotal         = 0;
let _emOffset        = 0;
let _emAccounts      = [];
let _emSort          = { col: 'date', dir: -1 };
let _emPriorityFilter  = null;     // null=all, 1=urgent only
let _emCategoryFilter  = null;     // null=all, or category string
let _emAccountId       = null;     // null=all accounts, or account id
let _emSelectedId      = null;     // keyboard-selected message id
let _emOpenMsg         = null;     // message currently shown in detail panel
let _emPendingTrash    = null;     // deferred trash: {timer, commit, done}

const _EM_COLOURS = ['#185FA5','#3B6D11','#8a5a00','#A32D2D','#00695c','#7c3aed'];

function _emSelectMsg(id) {
  _emSelectedId = id;
  document.querySelectorAll('tr.em-selected').forEach(r => r.classList.remove('em-selected'));
  const row = document.querySelector(`tr[data-msgid="${id}"]`);
  if (row) { row.classList.add('em-selected'); row.scrollIntoView({ block: 'nearest' }); }
}

function _emSetTitleBadge() {
  apiFetch('/api/emails/unread_count').then(r => {
    const n = r.unread || 0;
    const base = document.title.replace(/^\(\d+\)\s*/, '');
    document.title = n > 0 ? `(${n}) ${base}` : base;
  }).catch(() => {});
}

function _emKeyHandler(e) {
  if (!document.getElementById('em-q')) return;  // not on emails page
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (document.querySelector('.modal-bd')) return;

  const panelOpen = document.querySelector('.det-panel')?.classList.contains('open');
  if (!panelOpen) _emOpenMsg = null;

  switch (e.key) {
    case 'j':
    case 'ArrowDown': {
      e.preventDefault();
      const cur = _emOpenMsg?.id ?? _emSelectedId;
      const idx  = _emMessages.findIndex(m => m.id === cur);
      const next = _emMessages[idx + 1];
      if (!next) break;
      _emSelectMsg(next.id);
      if (panelOpen) emOpen(next.id, next.thread_id);
      break;
    }
    case 'k':
    case 'ArrowUp': {
      e.preventDefault();
      const cur = _emOpenMsg?.id ?? _emSelectedId;
      const idx  = _emMessages.findIndex(m => m.id === cur);
      const prev = _emMessages[Math.max(0, idx - 1)];
      if (!prev || prev.id === cur) break;
      _emSelectMsg(prev.id);
      if (panelOpen) emOpen(prev.id, prev.thread_id);
      break;
    }
    case 'Enter': {
      if (!panelOpen && _emSelectedId) {
        const msg = _emMessages.find(m => m.id === _emSelectedId);
        if (msg) emOpen(msg.id, msg.thread_id);
      }
      break;
    }
    case 'r':
      if (_emOpenMsg) composeReply(_emOpenMsg);
      break;
    case 'a':
      if (_emOpenMsg) composeReplyAll(_emOpenMsg);
      break;
    case 'f':
      if (_emOpenMsg) composeForward(_emOpenMsg);
      break;
    case 'e': {
      const target = _emOpenMsg || _emMessages.find(m => m.id === _emSelectedId);
      if (target) _emTrash(target.id);
      break;
    }
    case 'u':
      if (_emOpenMsg) _emMarkUnread(_emOpenMsg.id);
      break;
    case 'n':
      composeNew(_emAccountId);
      break;
    case '/':
      e.preventDefault();
      document.getElementById('em-q')?.focus();
      break;
    case 'Escape':
      if (panelOpen) { detClose(); _emOpenMsg = null; }
      break;
  }
}

const _EM_SORT_COLS = {
  from_name: (a, b) => (a.from_name||a.from_addr||'').localeCompare(b.from_name||b.from_addr||''),
  subject:   (a, b) => (a.subject||'').localeCompare(b.subject||''),
  date:      (a, b) => (a.date||'').localeCompare(b.date||''),
};

function _emStopAutoRefresh() {
  if (_emAutoRefreshTimer) { clearInterval(_emAutoRefreshTimer); _emAutoRefreshTimer = null; }
}

// Called by navigate() for role-based folders (inbox/sent/drafts/trash/all)
// accountId is optional — pass to pre-filter to a specific account (from sidebar account sections)
async function pageEmails(folder, folderName, accountId = null) {
  if (_emPendingTrash) { _emPendingTrash.commit(); _emPendingTrash = null; }
  _emStopAutoRefresh();
  const _folderAlias = { junk: 'spam' };
  _emFolder        = _folderAlias[folder] || folder || 'inbox';
  _emFolderId      = null;
  _emFolderName    = folderName || { inbox:'Inbox', sent:'Sent', drafts:'Drafts', trash:'Trash', spam:'Junk', all:'All Mail' }[_emFolder] || _emFolder;
  _emSearch         = '';
  _emOffset         = 0;
  _emPriorityFilter = null;
  _emCategoryFilter = null;
  _emAccountId      = accountId;
  _emSelectedId     = null;
  _emOpenMsg        = null;
  document.removeEventListener('keydown', _emKeyHandler);
  document.addEventListener('keydown', _emKeyHandler);
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading...</div>';
  try {
    _emAccounts = await apiFetch('/api/accounts');
    await _emLoad();
    if (_emFolder === 'inbox') {
      _emAutoRefreshTimer = setInterval(() => { if (_emFolder === 'inbox') _emLoad(); }, 120000);
    }
  } catch(e) {
    mc.innerHTML = `<div class="state-error">Failed to load: ${esc(e.message)}</div>`;
  }
}

// Called by sidebar folder list for specific folder by ID
async function pageEmailsFolder(folderId, folderDisplayName) {
  if (_emPendingTrash) { _emPendingTrash.commit(); _emPendingTrash = null; }
  _emStopAutoRefresh();
  _emFolder         = null;
  _emFolderId       = folderId;
  _emFolderName     = folderDisplayName || 'Folder';
  _emSearch         = '';
  _emOffset         = 0;
  _emCategoryFilter = null;
  _emAccountId      = null;
  _emSelectedId     = null;
  _emOpenMsg        = null;
  document.removeEventListener('keydown', _emKeyHandler);
  document.addEventListener('keydown', _emKeyHandler);
  document.getElementById('page-title').textContent = _emFolderName;
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading...</div>';
  try {
    _emAccounts = await apiFetch('/api/accounts');
    await _emLoad();
  } catch(e) {
    mc.innerHTML = `<div class="state-error">Failed to load: ${esc(e.message)}</div>`;
  }
}

async function _emLoad(append = false) {
  const params = new URLSearchParams({ limit: 200, offset: _emOffset });
  if (_emFolderId) {
    params.set('folder_id', _emFolderId);
  } else {
    params.set('folder', _emFolder);
  }
  if (_emSearch) params.set('q', _emSearch);
  if (_emPriorityFilter) params.set('priority', _emPriorityFilter);
  if (_emCategoryFilter) params.set('category', _emCategoryFilter);
  if (_emAccountId) params.set('account', _emAccountId);
  const data = await apiFetch('/api/emails?' + params);
  if (append) {
    _emMessages = _emMessages.concat(data.messages || []);
  } else {
    _emMessages = data.messages || [];
  }
  _emTotal = data.total || 0;
  _emApplySort();
  if (!append && !_emSelectedId && _emMessages.length) _emSelectedId = _emMessages[0].id;
  _emRender();
  if (!append && _emFolder === 'inbox' && !_emPriorityFilter) _emAutoTriage();
  if (!append && _emFolder === 'inbox') _emSetTitleBadge();
}

async function _emLoadMore() {
  _emOffset += 200;
  const mc = document.getElementById('module-content');
  const btn = mc.querySelector('.em-load-more');
  if (btn) { btn.textContent = 'Loading...'; btn.disabled = true; }
  try { await _emLoad(true); } catch(e) { _emOffset -= 200; toast('Load failed: ' + e.message, 'err'); }
}

async function _emLoadAll() {
  const mc = document.getElementById('module-content');
  const btn = mc.querySelector('.em-load-all');
  if (btn) { btn.textContent = 'Loading...'; btn.disabled = true; }
  try {
    const params = new URLSearchParams({ limit: _emTotal, offset: 0 });
    if (_emFolderId) { params.set('folder_id', _emFolderId); } else { params.set('folder', _emFolder); }
    if (_emSearch) params.set('q', _emSearch);
    const data = await apiFetch('/api/emails?' + params);
    _emMessages = data.messages || [];
    _emTotal    = data.total || 0;
    _emOffset   = _emMessages.length;
    _emApplySort();
    _emRender();
  } catch(e) { toast('Load failed: ' + e.message, 'err'); }
}

function _emSetPriority(p) {
  _emPriorityFilter = p;
  _emOffset = 0;
  _emLoad();
}

function _emSetCategory(cat) {
  _emCategoryFilter = cat;
  _emOffset = 0;
  _emLoad();
}

function _emSetAccount(id) {
  _emAccountId = id;
  _emOffset = 0;
  _emLoad();
}

async function _emAutoTriage() {
  try {
    const r = await fetch('/api/ai/triage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 50 }),
    }).then(r => r.json());
    if (r.ok && r.data && r.data.triaged > 0) {
      const byId = {};
      for (const item of r.data.results) byId[item.id] = item;
      _emMessages = _emMessages.map(m =>
        byId[m.id] ? { ...m, ai_priority: byId[m.id].priority, ai_category: byId[m.id].category } : m
      );
      _emRender(true);
    }
  } catch(e) {}
}

function _emApplySort() {
  const cmp = _EM_SORT_COLS[_emSort.col];
  if (cmp) _emMessages.sort((a, b) => cmp(a, b) * _emSort.dir);
}

function emSort(col) {
  if (_emSort.col === col) {
    _emSort.dir = -_emSort.dir;
  } else {
    _emSort.col = col;
    _emSort.dir = col === 'date' ? -1 : 1;
  }
  _emApplySort();
  _emRender(true);
}

function _emTh(col, label, extraStyle) {
  const active = _emSort.col === col;
  const arrow  = active ? (_emSort.dir === 1 ? ' ▲' : ' ▼') : '';
  return `<th onclick="emSort('${col}')" style="cursor:pointer;user-select:none${extraStyle ? ';' + extraStyle : ''}" class="${active ? 'sort-active' : ''}">${label}${arrow}</th>`;
}

let _emSearchTimer      = null;
let _emAutoRefreshTimer = null;

function _emRender(keepScroll) {
  const mc = document.getElementById('module-content');
  const msgs = _emMessages;
  const scrollTop = keepScroll ? (mc.querySelector('.em-list-panel')?.parentElement?.scrollTop || 0) : 0;
  const searchWasFocused = document.activeElement?.id === 'em-q';

  mc.innerHTML = `
    <div class="em-toolbar">
      <input class="em-search" id="em-q" placeholder="Search messages..." value="${esc(_emSearch)}">
      ${_emAccounts.length > 1 ? `
      <div class="em-filter-pills">
        <button class="em-pill${_emAccountId === null ? ' active' : ''}" onclick="_emSetAccount(null)">All</button>
        ${_emAccounts.map((a, i) => `<button class="em-pill${_emAccountId === a.id ? ' active' : ''}" onclick="_emSetAccount(${a.id})"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${_EM_COLOURS[i % _EM_COLOURS.length]};margin-right:5px;vertical-align:middle"></span>${esc(a.name)}</button>`).join('')}
      </div>` : ''}
      ${_emFolder === 'inbox' ? `
      <div class="em-filter-pills">
        <button class="em-pill${_emPriorityFilter === null ? ' active' : ''}" onclick="_emSetPriority(null)">All</button>
        <button class="em-pill em-pill-urgent${_emPriorityFilter === 1 ? ' active' : ''}" onclick="_emSetPriority(1)">&#9873; Urgent</button>
      </div>
      ${_emCategoryPills()}` : ''}
      ${_emCategoryFilter && _emTotal > 0 ? `<button class="btn btn-outline btn-sm" onclick="_emBulkMove('${_emCategoryFilter}')">Move all ${_emTotal}&hellip;</button>` : ''}
      ${(_emFolder === 'inbox' || _emFolderId) ? `<button class="btn btn-outline btn-sm" onclick="_emMarkAllRead()" title="Mark all as read">&#10003; All read</button>` : ''}
      ${_emFolder === 'trash' ? `<button class="btn btn-outline btn-sm btn-danger" onclick="_emEmptyTrash()">&#128465; Empty Trash</button>` : ''}
      <button class="btn btn-outline btn-sm" onclick="_emPrefetch()" title="Download all message bodies for offline reading">&#8659; Offline</button>
      <button class="btn btn-primary btn-sm" onclick="composeNew(${_emAccountId || 'null'})">&#9998; Compose</button>
    </div>
    <div class="em-list-panel">
      <div class="tbl-overflow-x">
        <table class="em-list-table">
          <thead><tr>
            <th style="width:14px"></th>
            ${_emTh('from_name','From')}
            ${_emTh('subject','Subject')}
            <th>Preview</th>
            ${_emTh('date','Date','min-width:90px')}
            <th style="width:22px"></th>
            <th style="width:20px"></th>
          </tr></thead>
          <tbody>
            ${msgs.length
              ? msgs.map(_emRow).join('')
              : `<tr><td colspan="7" class="em-empty">No messages in this folder</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
    <div class="mt-8">
      <span class="count-pill">${msgs.length} of ${_emTotal} message${_emTotal !== 1 ? 's' : ''}</span>
      ${msgs.length < _emTotal ? `<button class="btn btn-outline btn-sm em-load-more" style="margin-left:12px" onclick="_emLoadMore()">Load more</button><button class="btn btn-outline btn-sm em-load-all" style="margin-left:6px" onclick="_emLoadAll()">Load all</button>` : ''}
    </div>`;

  if (scrollTop) mc.scrollTop = scrollTop;

  const q = document.getElementById('em-q');
  if (q) {
    q.addEventListener('input', e => {
      _emSearch = e.target.value;
      _emOffset = 0;
      clearTimeout(_emSearchTimer);
      _emSearchTimer = setTimeout(() => _emLoad(), 300);
    });
    q.addEventListener('keydown', e => {
      if (e.key === 'Escape') { clearTimeout(_emSearchTimer); _emSearch = ''; q.value = ''; _emLoad(); }
    });
    if (searchWasFocused) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  }
}

const _EM_CATEGORIES = {
  invoice:'#8a5a00', support:'#185FA5', personal:'#3B6D11',
  newsletter:'#555', marketing:'#555', notification:'#555',
};

const _EM_CAT_LABELS = {
  invoice:'Invoices', support:'Support', personal:'Personal',
  newsletter:'Newsletters', marketing:'Marketing', notification:'Notifications', other:'Other',
};

function _emCategoryPills() {
  const cats = [...new Set(_emMessages.filter(m => m.ai_category).map(m => m.ai_category))];
  if (!cats.length) return '';
  return `<div class="em-filter-pills">
    <button class="em-pill${_emCategoryFilter === null ? ' active' : ''}" onclick="_emSetCategory(null)">All types</button>
    ${cats.map(c => `<button class="em-pill em-pill-cat em-pill-cat-${c}${_emCategoryFilter === c ? ' active' : ''}" onclick="_emSetCategory('${c}')">${esc(_EM_CAT_LABELS[c] || c)}</button>`).join('')}
  </div>`;
}

async function _emBulkMove(category) {
  const accountId = _emAccountId || (_emMessages.length ? _emMessages[0].account_id : null);
  let folders;
  try {
    folders = await apiFetch('/api/folders' + (accountId ? '?account=' + accountId : ''));
  } catch(e) {
    toast('Could not load folders: ' + e.message, 'err');
    return;
  }
  const choices = folders.filter(f => f.role !== 'trash');
  const label = _EM_CAT_LABELS[category] || category;

  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.style.display = 'flex';
  bd.innerHTML = `
    <div class="modal-box" style="width:360px;max-height:520px;display:flex;flex-direction:column">
      <div class="modal-hdr">
        <span>Move all ${_emTotal} ${label} to&hellip;</span>
        <button class="modal-close" onclick="this.closest('.modal-bd').remove()">&#x2715;</button>
      </div>
      <div style="padding:10px 16px;border-bottom:1px solid var(--border)">
        <input id="em-bmove-q" class="form-input" placeholder="Search folders&hellip;" autocomplete="off" style="width:100%">
      </div>
      <div id="em-bmove-list" style="overflow-y:auto;flex:1;padding:6px 0"></div>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener('click', e => { if (e.target === bd) bd.remove(); });

  const listEl  = bd.querySelector('#em-bmove-list');
  const searchEl = bd.querySelector('#em-bmove-q');

  function renderList(q) {
    const filtered = q ? choices.filter(f => f.name.toLowerCase().includes(q.toLowerCase())) : choices;
    if (!filtered.length) {
      listEl.innerHTML = '<div style="padding:12px 16px;color:var(--ink3);font-size:13px">No matching folders</div>';
      return;
    }
    listEl.innerHTML = filtered.map(f => {
      const lbl = f.display_name || f.name;
      const roleTag = f.role ? `<span style="font-size:10px;color:var(--ink3);margin-left:6px">${esc(f.role)}</span>` : '';
      return `<div class="em-move-row" data-fid="${f.id}" data-fname="${esc(lbl)}">${esc(lbl)}${roleTag}</div>`;
    }).join('');
    listEl.querySelectorAll('.em-move-row').forEach(row => {
      row.onclick = async () => {
        bd.remove();
        const folderId = parseInt(row.dataset.fid);
        const folderName = row.dataset.fname;
        try {
          const r = await fetch('/api/emails/bulk_move', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ category, folder_id: folderId, folder_role: _emFolder || null, account_id: _emAccountId }),
          }).then(r => r.json());
          if (!r.ok) { toast(r.error || 'Move failed', 'err'); return; }
          const n = r.data.moved;
          _emMessages = _emMessages.filter(m => m.ai_category !== category);
          _emTotal    = Math.max(0, _emTotal - n);
          _emCategoryFilter = null;
          _emRender(true);
          toast(`Moved ${n} message${n !== 1 ? 's' : ''} to ${folderName}`);
        } catch(e) { toast('Move failed: ' + e.message, 'err'); }
      };
    });
  }

  renderList('');
  searchEl.addEventListener('input', e => renderList(e.target.value));
  searchEl.focus();
}

function _emRow(msg) {
  const acctIdx  = _emAccounts.findIndex(a => a.id === msg.account_id);
  const colour   = _EM_COLOURS[Math.max(0, acctIdx) % _EM_COLOURS.length];
  const flags    = JSON.parse(msg.flags || '[]');
  const isUnread = !flags.includes('\\Seen');
  const isStarred = flags.includes('\\Flagged');
  const displayFrom = msg.from_name || msg.from_addr || '(unknown)';
  const priority = msg.ai_priority;
  const category = msg.ai_category;
  const priorityClass = priority === 1 ? ' em-priority-urgent' : '';
  const categoryHtml = (category && category !== 'other' && category !== 'marketing' && category !== 'notification')
    ? `<span class="em-category" style="color:${_EM_CATEGORIES[category]||'#555'}">${esc(category)}</span>` : '';

  return `<tr class="em-row${isUnread ? ' unread' : ''}${priorityClass}${msg.id === _emSelectedId ? ' em-selected' : ''}" data-msgid="${msg.id}" onclick="_emSelectMsg(${msg.id});emOpen(${msg.id}, '${esc(msg.thread_id || '')}')">
    <td><span class="em-acct-dot" style="background:${colour}" title="${esc(msg.account_name||'')}"></span></td>
    <td class="em-from">${priority === 1 ? '<span class="em-urgent-flag" title="Urgent">&#9873;</span> ' : ''}${esc(displayFrom)}</td>
    <td class="em-subject">${esc(msg.subject || '(no subject)')}${categoryHtml}</td>
    <td class="em-snippet">${esc(msg.snippet || '')}</td>
    <td class="em-date">${fmtDate(msg.date)}</td>
    <td>${msg.has_attachments ? '<span class="em-att-icon" title="Has attachments">&#128206;</span>' : ''}</td>
    <td class="em-star-cell" onclick="event.stopPropagation();_emToggleStar(${msg.id},this)">${isStarred ? '<span class="em-star starred" title="Unstar">&#9733;</span>' : '<span class="em-star" title="Star">&#9734;</span>'}</td>
  </tr>`;
}

async function _emToggleStar(msgId, cell) {
  try {
    const r = await fetch(`/api/emails/${msgId}/star`, { method: 'POST' }).then(r => r.json());
    if (!r.ok) return;
    const starred = r.data.starred;
    if (cell) cell.innerHTML = starred
      ? '<span class="em-star starred" title="Unstar">&#9733;</span>'
      : '<span class="em-star" title="Star">&#9734;</span>';
    const msg = _emMessages.find(m => m.id === msgId);
    if (msg) {
      const flags = JSON.parse(msg.flags || '[]');
      if (starred && !flags.includes('\\Flagged')) flags.push('\\Flagged');
      if (!starred) { const i = flags.indexOf('\\Flagged'); if (i > -1) flags.splice(i, 1); }
      msg.flags = JSON.stringify(flags);
    }
  } catch(e) {}
}

async function emOpen(msgId, threadId) {
  // If it's a draft, open compose instead of detail panel
  const listMsg = _emMessages.find(m => m.id === msgId);
  if (listMsg && JSON.parse(listMsg.flags || '[]').includes('\\Draft')) {
    try {
      const msg = await apiFetch(`/api/emails/${msgId}`);
      composeFromDraft(msg);
    } catch(e) { toast('Could not open draft: ' + e.message, 'err'); }
    return;
  }

  detOpen('');
  try {
    if (threadId) {
      const threadMsgs = await apiFetch(`/api/threads/${encodeURIComponent(threadId)}`);
      if (threadMsgs.length > 1) {
        const selMsg = threadMsgs.find(m => m.id === msgId) || threadMsgs[threadMsgs.length - 1];
        document.getElementById('det-title').textContent = selMsg.subject || '(no subject)';
        await _emRenderThread(threadMsgs, msgId, threadId);
        fetch(`/api/emails/${msgId}/mark_read`, { method: 'POST' }).catch(() => {});
        document.querySelector(`tr[data-msgid="${msgId}"]`)?.classList.remove('unread');
        return;
      }
    }
    // Single message view
    const msg = await apiFetch(`/api/emails/${msgId}`);
    document.getElementById('det-title').textContent = msg.subject || '(no subject)';
    _emRenderDetail(msg, threadId);
    _emOpenMsg = msg;
    if (threadId) _emLoadSummary(threadId);
    if (threadId) _emLoadActions(threadId);
    fetch(`/api/emails/${msgId}/mark_read`, { method: 'POST' }).catch(() => {});
    document.querySelector(`tr[data-msgid="${msgId}"]`)?.classList.remove('unread');
    if (_emFolder === 'inbox') _emSetTitleBadge();
  } catch(e) {
    document.getElementById('det-body').innerHTML = `<div class="state-error">${esc(e.message)}</div>`;
  }
}

function _emFmtDetailDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
      + ' ' + d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
  } catch(e) { return iso; }
}

function _emRenderDetail(msg, threadId) {
  const toList  = _emParseAddrs(msg.to_addrs);
  const toStr   = toList.map(a => a.name ? `${a.name} <${a.addr}>` : a.addr).join(', ');
  const ccList  = _emParseAddrs(msg.cc_addrs);
  const ccStr   = ccList.map(a => a.name ? `${a.name} <${a.addr}>` : a.addr).join(', ');
  const fromStr = msg.from_name ? `${msg.from_name} <${msg.from_addr}>` : msg.from_addr;
  const hasHtml = msg.body_html && msg.body_html.trim();

  document.getElementById('det-body').innerHTML = `
    <div class="ai-summary-box" id="ai-summary-box" style="display:none">
      <div class="ai-summary-label">&#10022; AI Summary</div>
      <div id="ai-summary-text"></div>
    </div>
    <div class="ai-actions-box" id="ai-actions-box" style="display:none">
      <div class="ai-actions-label">&#9889; Actions</div>
      <div id="ai-actions-list"></div>
    </div>
    <div class="em-meta-strip">
      <div class="em-meta-row"><span class="em-meta-label">From</span><span class="em-meta-val">${esc(fromStr)}</span></div>
      <div class="em-meta-row"><span class="em-meta-label">To</span><span class="em-meta-val">${esc(toStr)}</span></div>
      ${ccStr ? `<div class="em-meta-row"><span class="em-meta-label">CC</span><span class="em-meta-val">${esc(ccStr)}</span></div>` : ''}
      <div class="em-meta-row"><span class="em-meta-label">Date</span><span class="em-meta-val">${_emFmtDetailDate(msg.date)}</span></div>
    </div>
    ${msg.attachments && msg.attachments.length ? `<div class="em-attachments" id="em-att-bar"></div>` : ''}
    ${msg._fetch_error
      ? `<div class="state-error" style="margin:16px 0">${esc(msg._fetch_error)}</div>`
      : hasHtml
        ? `<iframe class="em-body-frame" id="em-iframe" sandbox="allow-same-origin allow-popups" style="height:500px"></iframe>`
        : `<pre class="em-body-text">${esc(msg.body_text || '(empty)')}</pre>`}`;

  if (hasHtml) {
    const iframe = document.getElementById('em-iframe');
    iframe.srcdoc = `<html><head><base target="_blank"><style>body{font-family:sans-serif;font-size:14px;line-height:1.6;color:#1A2E45;padding:12px}a{color:#185FA5}img{max-width:100%}</style></head><body>${msg.body_html}</body></html>`;
    const _resizeIframe = () => {
      try {
        const h = iframe.contentWindow.document.body.scrollHeight;
        if (h > 0) iframe.style.height = (h + 40) + 'px';
      } catch(e) {}
    };
    iframe.onload = () => {
      _resizeIframe();
      // Re-check after images may have loaded
      setTimeout(_resizeIframe, 800);
    };
  }

  const attBar = document.getElementById('em-att-bar');
  if (attBar && msg.attachments && msg.attachments.length) {
    for (const a of msg.attachments) {
      const chip = document.createElement('span');
      chip.className = 'em-att-chip';
      chip.innerHTML = `&#128206; ${esc(a.filename)}<span class="em-att-size">${_emFmtSize(a.size)}</span>`;
      chip.addEventListener('click', () => _emDownloadAtt(msg.id, a.id, a.filename));
      attBar.appendChild(chip);
    }
  }

  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';

  const replyBtn = document.createElement('button');
  replyBtn.className = 'btn btn-primary btn-sm';
  replyBtn.textContent = 'Reply';
  replyBtn.onclick = () => composeReply(msg);
  foot.appendChild(replyBtn);

  const replyAllBtn = document.createElement('button');
  replyAllBtn.className = 'btn btn-outline btn-sm';
  replyAllBtn.textContent = 'Reply All';
  replyAllBtn.onclick = () => composeReplyAll(msg);
  foot.appendChild(replyAllBtn);

  const aiBtn = document.createElement('button');
  aiBtn.className = 'btn btn-outline btn-sm';
  aiBtn.textContent = 'Draft with AI';
  aiBtn.onclick = () => _emAiDraft(msg, threadId);
  foot.appendChild(aiBtn);

  const fwdBtn = document.createElement('button');
  fwdBtn.className = 'btn btn-outline btn-sm';
  fwdBtn.textContent = 'Forward';
  fwdBtn.onclick = () => composeForward(msg);
  foot.appendChild(fwdBtn);

  const moveBtn = document.createElement('button');
  moveBtn.className = 'btn btn-outline btn-sm';
  moveBtn.textContent = 'Move to…';
  moveBtn.onclick = () => _emMoveModal(msg);
  foot.appendChild(moveBtn);

  const isStarredNow = JSON.parse(msg.flags || '[]').includes('\\Flagged');
  const starBtn = document.createElement('button');
  starBtn.className = 'btn btn-outline btn-sm';
  starBtn.textContent = isStarredNow ? '★ Unstar' : '☆ Star';
  starBtn.onclick = async () => {
    try {
      const r = await fetch(`/api/emails/${msg.id}/star`, { method: 'POST' }).then(r => r.json());
      if (r.ok) {
        starBtn.textContent = r.data.starred ? '★ Unstar' : '☆ Star';
        const flags = JSON.parse(msg.flags || '[]');
        if (r.data.starred && !flags.includes('\\Flagged')) flags.push('\\Flagged');
        if (!r.data.starred) { const i = flags.indexOf('\\Flagged'); if (i > -1) flags.splice(i, 1); }
        msg.flags = JSON.stringify(flags);
        const starCell = document.querySelector(`tr[data-msgid="${msg.id}"] .em-star-cell`);
        if (starCell) starCell.innerHTML = r.data.starred
          ? '<span class="em-star starred" title="Unstar">&#9733;</span>'
          : '<span class="em-star" title="Star">&#9734;</span>';
      }
    } catch(e) {}
  };
  foot.appendChild(starBtn);

  const unreadBtn = document.createElement('button');
  unreadBtn.className = 'btn btn-outline btn-sm';
  unreadBtn.textContent = 'Mark Unread';
  unreadBtn.onclick = () => _emMarkUnread(msg.id);
  foot.appendChild(unreadBtn);

  if (msg.folder_role === 'trash') {
    const restoreBtn = document.createElement('button');
    restoreBtn.className = 'btn btn-outline btn-sm';
    restoreBtn.textContent = 'Restore to Inbox';
    restoreBtn.onclick = () => _emRestore(msg.id);
    foot.appendChild(restoreBtn);
  } else if (msg.folder_role === 'spam') {
    const unspamBtn = document.createElement('button');
    unspamBtn.className = 'btn btn-outline btn-sm';
    unspamBtn.textContent = 'Not Spam';
    unspamBtn.onclick = async () => {
      const r = await fetch(`/api/emails/${msg.id}/unspam`, { method: 'POST' }).then(r => r.json());
      if (r.ok) { detClose(); _emMessages = _emMessages.filter(m => m.id !== msg.id); _emTotal = Math.max(0, _emTotal - 1); _emRender(true); toast('Moved to Inbox'); }
      else toast(r.error || 'Failed', 'err');
    };
    foot.appendChild(unspamBtn);
  } else {
    const spamBtn = document.createElement('button');
    spamBtn.className = 'btn btn-outline btn-sm';
    spamBtn.textContent = 'Spam';
    spamBtn.onclick = async () => {
      const r = await fetch(`/api/emails/${msg.id}/spam`, { method: 'POST' }).then(r => r.json());
      if (r.ok) { detClose(); _emMessages = _emMessages.filter(m => m.id !== msg.id); _emTotal = Math.max(0, _emTotal - 1); _emRender(true); toast('Marked as spam'); }
      else toast(r.error || 'Failed', 'err');
    };
    foot.appendChild(spamBtn);
  }

  const delBtn = document.createElement('button');
  delBtn.className = 'btn btn-outline btn-sm btn-danger';
  delBtn.textContent = msg.folder_role === 'trash' ? 'Delete Forever' : 'Delete';
  delBtn.onclick = () => _emTrash(msg.id);
  foot.appendChild(delBtn);
}

async function _emPrefetch() {
  const payload = {};
  if (_emFolderId)      payload.folder_id  = _emFolderId;
  else if (_emFolder)   payload.folder_role = _emFolder;
  if (_emAccountId)     payload.account_id  = _emAccountId;
  try {
    const r = await fetch('/api/emails/prefetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Failed', 'err'); return; }
    const n = r.data.queued;
    if (n === 0) { toast('All messages already downloaded'); return; }
    toast(`Downloading ${n} message${n !== 1 ? 's' : ''} for offline access…`);
    const key = r.data.key;
    const _poll = setInterval(async () => {
      try {
        const s = await apiFetch(`/api/emails/prefetch_status?key=${encodeURIComponent(key)}`);
        if (!s.running) {
          clearInterval(_poll);
          toast(`Downloaded ${s.done} of ${s.total} messages`);
        }
      } catch(e) { clearInterval(_poll); }
    }, 3000);
  } catch(e) { toast('Failed: ' + e.message, 'err'); }
}

async function _emEmptyTrash() {
  if (!confirm('Permanently delete all messages in Trash?')) return;
  const accountId = _emAccountId || (_emMessages[0]?.account_id) || null;
  if (!accountId) { toast('No account selected', 'err'); return; }
  try {
    const r = await fetch('/api/emails/empty_trash', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId }),
    }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Failed', 'err'); return; }
    const n = r.data.deleted;
    _emMessages = [];
    _emTotal = 0;
    _emRender();
    toast(`Deleted ${n} message${n !== 1 ? 's' : ''} permanently`);
  } catch(e) { toast('Failed: ' + e.message, 'err'); }
}

async function _emMarkUnread(msgId) {
  try {
    await fetch(`/api/emails/${msgId}/mark_unread`, { method: 'POST' });
    const row = document.querySelector(`tr[data-msgid="${msgId}"]`);
    if (row) row.classList.add('unread');
    detClose();
    toast('Marked as unread');
  } catch(e) { toast('Failed: ' + e.message, 'err'); }
}

async function _emMarkAllRead() {
  const payload = {};
  if (_emFolderId) {
    payload.folder_id = _emFolderId;
  } else {
    payload.folder_role = _emFolder;
  }
  if (_emAccountId) payload.account_id = _emAccountId;
  try {
    const r = await fetch('/api/emails/mark_all_read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Failed', 'err'); return; }
    const n = r.data.marked;
    _emMessages = _emMessages.map(m => {
      const flags = JSON.parse(m.flags || '[]');
      if (!flags.includes('\\Seen')) flags.push('\\Seen');
      return { ...m, flags: JSON.stringify(flags) };
    });
    _emRender(true);
    if (n > 0) { toast(`Marked ${n} message${n !== 1 ? 's' : ''} as read`); _emSetTitleBadge(); }
  } catch(e) { toast('Failed: ' + e.message, 'err'); }
}

async function _emRestore(msgId) {
  try {
    const r = await fetch(`/api/emails/${msgId}/restore`, { method: 'POST' }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Restore failed', 'err'); return; }
    detClose();
    _emMessages = _emMessages.filter(m => m.id !== msgId);
    _emTotal = Math.max(0, _emTotal - 1);
    _emRender(true);
    toast('Restored to Inbox');
  } catch(e) { toast('Restore failed: ' + e.message, 'err'); }
}

async function _emTrash(msgId) {
  // Commit any previous deferred trash before queuing a new one
  if (_emPendingTrash) { _emPendingTrash.commit(); _emPendingTrash = null; }

  const idx     = _emMessages.findIndex(m => m.id === msgId);
  const msg     = idx >= 0 ? _emMessages[idx] : null;
  const inTrash = msg?.folder_role === 'trash' || _emFolder === 'trash';

  detClose();
  _emOpenMsg = null;
  if (idx >= 0) {
    _emMessages = _emMessages.filter(m => m.id !== msgId);
    _emTotal = Math.max(0, _emTotal - 1);
    _emRender(true);
  }

  // Already in trash — permanent delete, no undo offered
  if (inTrash) {
    try {
      const r = await fetch(`/api/emails/${msgId}/trash`, { method: 'POST' }).then(r => r.json());
      toast(r.ok ? 'Deleted permanently' : (r.error || 'Delete failed'), r.ok ? undefined : 'err');
    } catch(e) { toast('Delete failed: ' + e.message, 'err'); }
    return;
  }

  // Deferred trash — fire API after 5 s; Undo cancels it
  const state = { done: false, timer: null };
  state.commit = () => {
    if (state.done) return;
    state.done = true;
    fetch(`/api/emails/${msgId}/trash`, { method: 'POST' }).catch(() => {});
  };
  state.timer = setTimeout(() => { state.commit(); _emPendingTrash = null; }, 5000);
  _emPendingTrash = state;

  _emUndoToast('Moved to Trash', () => {
    if (state.done) return;
    state.done = true;
    clearTimeout(state.timer);
    _emPendingTrash = null;
    if (msg && idx >= 0) {
      _emMessages.splice(idx, 0, msg);
      _emTotal += 1;
      _emRender(true);
      _emSelectMsg(msgId);
    }
  });
}

function _emUndoToast(message, onUndo) {
  const tc = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast toast-undo';
  el.innerHTML = `<span>${esc(message)}</span><button class="toast-undo-btn">Undo</button>`;
  tc.appendChild(el);
  const dismiss = () => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.3s';
    setTimeout(() => el.remove(), 300);
  };
  el.querySelector('.toast-undo-btn').addEventListener('click', () => { onUndo(); dismiss(); });
  setTimeout(dismiss, 5500);
}

async function _emMoveModal(msg) {
  // Fetch folders for this account
  let folders;
  try {
    folders = await apiFetch('/api/folders?account=' + msg.account_id);
  } catch(e) {
    toast('Could not load folders: ' + e.message, 'err');
    return;
  }

  // Exclude current folder and trash (use Delete for that)
  const choices = folders.filter(f => f.id !== msg.folder_id && f.role !== 'trash');

  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.style.display = 'flex';
  bd.innerHTML = `
    <div class="modal-box" style="width:360px;max-height:520px;display:flex;flex-direction:column">
      <div class="modal-hdr">
        <span>Move to Folder</span>
        <button class="modal-close" onclick="this.closest('.modal-bd').remove()">&#x2715;</button>
      </div>
      <div style="padding:10px 16px;border-bottom:1px solid var(--border)">
        <input id="em-move-q" class="form-input" placeholder="Search folders…" autocomplete="off" style="width:100%">
      </div>
      <div id="em-move-list" style="overflow-y:auto;flex:1;padding:6px 0"></div>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener('click', e => { if (e.target === bd) bd.remove(); });

  const listEl = bd.querySelector('#em-move-list');
  const searchEl = bd.querySelector('#em-move-q');

  function renderList(q) {
    const filtered = q
      ? choices.filter(f => f.name.toLowerCase().includes(q.toLowerCase()))
      : choices;
    if (!filtered.length) {
      listEl.innerHTML = '<div style="padding:12px 16px;color:var(--ink3);font-size:13px">No matching folders</div>';
      return;
    }
    listEl.innerHTML = filtered.map(f => {
      const label = f.display_name || f.name;
      const roleTag = f.role ? `<span style="font-size:10px;color:var(--ink3);margin-left:6px">${esc(f.role)}</span>` : '';
      return `<div class="em-move-row" data-fid="${f.id}" data-fname="${esc(label)}">${esc(label)}${roleTag}</div>`;
    }).join('');
    listEl.querySelectorAll('.em-move-row').forEach(row => {
      row.onclick = () => _emMoveToFolder(msg, parseInt(row.dataset.fid), row.dataset.fname, bd);
    });
  }

  renderList('');
  searchEl.addEventListener('input', e => renderList(e.target.value));
  searchEl.focus();
}

async function _emMoveToFolder(msg, folderId, folderName, modalEl) {
  if (modalEl) modalEl.remove();
  try {
    const r = await fetch(`/api/emails/${msg.id}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId }),
    }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Move failed', 'err'); return; }
    detClose();
    _emMessages = _emMessages.filter(m => m.id !== msg.id);
    _emTotal = Math.max(0, _emTotal - 1);
    _emRender(true);
    toast(`Moved to ${folderName}`);
  } catch(e) {
    toast('Move failed: ' + e.message, 'err');
  }
}

async function _emLoadSummary(threadId) {
  try {
    const r = await fetch('/api/ai/summarise', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({thread_id: threadId}),
    }).then(r => r.json());
    if (r.ok && r.data && r.data.summary) {
      const box = document.getElementById('ai-summary-box');
      const txt = document.getElementById('ai-summary-text');
      if (box && txt) { txt.textContent = r.data.summary; box.style.display = ''; box.classList.add('loaded'); }
    }
  } catch(e) {}
}

async function _emLoadActions(threadId) {
  if (!threadId) return;
  try {
    const r = await fetch('/api/ai/actions', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({thread_id: threadId}),
    }).then(r => r.json());
    if (!r.ok || !r.data || !r.data.actions || !r.data.actions.length) return;
    const box = document.getElementById('ai-actions-box');
    const list = document.getElementById('ai-actions-list');
    if (!box || !list) return;
    list.innerHTML = r.data.actions.map(a => {
      const typeClass = `ai-action-type-${a.type || 'task'}`;
      return `<div class="ai-action-item">
        <span class="ai-action-type ${typeClass}">${esc(a.type || 'task')}</span>
        <span class="ai-action-desc">${esc(a.description)}</span>
        ${a.due_date ? `<span class="ai-action-due">${esc(a.due_date)}</span>` : ''}
      </div>`;
    }).join('');
    box.style.display = '';
    box.classList.add('loaded');
  } catch(e) {}
}

async function _emAiDraft(msg, threadId) {
  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.style.display = 'flex';
  bd.innerHTML = `
    <div class="modal-box" style="width:480px">
      <div class="modal-hdr">
        <span>&#10022; Draft with AI</span>
        <button class="det-close" onclick="this.closest('.modal-bd').remove()">&#x2715;</button>
      </div>
      <div class="modal-body" style="padding:16px">
        <label style="font-size:13px;color:var(--ink2);display:block;margin-bottom:8px">Describe your reply:</label>
        <textarea id="ai-draft-intent" class="cmp-body" placeholder="e.g. Confirm the meeting, decline politely, ask for more info…" style="height:90px;resize:vertical"></textarea>
      </div>
      <div class="modal-foot">
        <button class="btn btn-outline btn-sm" onclick="this.closest('.modal-bd').remove()">Cancel</button>
        <button class="btn btn-primary btn-sm" id="ai-draft-go-btn">Generate Draft &#8594;</button>
      </div>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener('click', e => { if (e.target === bd) bd.remove(); });

  const textarea = bd.querySelector('#ai-draft-intent');
  const btn      = bd.querySelector('#ai-draft-go-btn');
  textarea.focus();

  const _generate = async () => {
    const intent = textarea.value.trim();
    if (!intent) { toast('Describe your reply', 'err'); return; }
    btn.disabled = true;
    btn.textContent = 'Generating…';
    try {
      const r = await fetch('/api/ai/draft', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ thread_id: threadId || msg.message_id, intent, account_id: msg.account_id }),
      }).then(r => r.json());
      bd.remove();
      if (r.ok && r.data && r.data.draft) { composeReply(msg, r.data.draft); }
      else { toast(r.error || 'Draft failed', 'err'); }
    } catch(e) {
      toast('AI draft failed: ' + e.message, 'err');
      btn.disabled = false;
      btn.textContent = 'Generate Draft →';
    }
  };

  btn.onclick = _generate;
  textarea.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) _generate(); });
}

// ── Thread view ───────────────────────────────────────────────────────────────

async function _emRenderThread(msgs, selectedId, threadId) {
  const det = document.getElementById('det-body');
  det.innerHTML = `
    <div class="ai-summary-box" id="ai-summary-box" style="display:none">
      <div class="ai-summary-label">&#10022; AI Summary</div>
      <div id="ai-summary-text"></div>
    </div>
    <div class="ai-actions-box" id="ai-actions-box" style="display:none">
      <div class="ai-actions-label">&#9889; Actions</div>
      <div id="ai-actions-list"></div>
    </div>
    <div class="th-count">${msgs.length} messages in thread</div>
    <div class="th-list" id="th-list"></div>`;
  _emLoadSummary(threadId);
  _emLoadActions(threadId);

  const list = document.getElementById('th-list');
  const expandId = msgs.find(m => m.id === selectedId) ? selectedId : msgs[msgs.length - 1].id;

  for (const msg of msgs) {
    const isExpanded = msg.id === expandId;
    const fromDisp   = msg.from_name || msg.from_addr || '?';
    const initial    = (fromDisp[0] || '?').toUpperCase();
    const isUnread   = !JSON.parse(msg.flags || '[]').includes('\\Seen');

    const card = document.createElement('div');
    card.className = `th-msg${isExpanded ? ' expanded' : ' collapsed'}${isUnread ? ' unread' : ''}`;
    card.dataset.mid     = msg.id;
    card.dataset.snippet = msg.snippet || '';
    card.innerHTML = `
      <div class="th-hdr" onclick="_emToggleThreadMsg(${msg.id})">
        <span class="th-avatar">${esc(initial)}</span>
        <div class="th-hdr-main">
          <span class="th-from">${esc(fromDisp)}</span>
          ${!isExpanded ? `<span class="th-snippet">${esc(msg.snippet || '')}</span>` : ''}
        </div>
        <span class="th-date">${fmtDate(msg.date)}</span>
      </div>
      <div class="th-body" id="th-body-${msg.id}"${isExpanded ? '' : ' style="display:none"'}>
        ${isExpanded ? '<div class="th-loading">Loading…</div>' : ''}
      </div>`;
    list.appendChild(card);
  }

  // Fetch and render expanded message (with body + attachments)
  try {
    const fullMsg = await apiFetch(`/api/emails/${expandId}`);
    const bodyEl  = document.getElementById(`th-body-${expandId}`);
    if (bodyEl) _emRenderThreadBody(fullMsg, bodyEl);
    _emRenderThreadFoot(fullMsg, threadId);
    _emOpenMsg = fullMsg;
  } catch(e) {
    const bodyEl = document.getElementById(`th-body-${expandId}`);
    if (bodyEl) bodyEl.innerHTML = `<div class="state-error">Failed to load message</div>`;
  }
}

function _emRenderThreadBody(msg, container) {
  const toStr  = _emParseAddrs(msg.to_addrs).map(a => a.name ? `${a.name} <${a.addr}>` : a.addr).join(', ');
  const ccStr  = _emParseAddrs(msg.cc_addrs).map(a => a.name ? `${a.name} <${a.addr}>` : a.addr).join(', ');
  const fromStr = msg.from_name ? `${msg.from_name} <${msg.from_addr}>` : msg.from_addr;
  const hasHtml = msg.body_html && msg.body_html.trim();

  container.innerHTML = `
    <div class="em-meta-strip">
      <div class="em-meta-row"><span class="em-meta-label">From</span><span class="em-meta-val">${esc(fromStr)}</span></div>
      <div class="em-meta-row"><span class="em-meta-label">To</span><span class="em-meta-val">${esc(toStr)}</span></div>
      ${ccStr ? `<div class="em-meta-row"><span class="em-meta-label">CC</span><span class="em-meta-val">${esc(ccStr)}</span></div>` : ''}
      <div class="em-meta-row"><span class="em-meta-label">Date</span><span class="em-meta-val">${_emFmtDetailDate(msg.date)}</span></div>
    </div>
    ${msg.attachments && msg.attachments.length ? `<div class="em-attachments" id="th-att-${msg.id}"></div>` : ''}
    ${msg._fetch_error
      ? `<div class="state-error" style="margin:12px 0">${esc(msg._fetch_error)}</div>`
      : hasHtml
        ? `<iframe class="em-body-frame" id="th-iframe-${msg.id}" sandbox="allow-same-origin allow-popups" style="height:300px"></iframe>`
        : `<pre class="em-body-text">${esc(msg.body_text || '(empty)')}</pre>`}`;

  if (hasHtml) {
    const iframe = document.getElementById(`th-iframe-${msg.id}`);
    iframe.srcdoc = `<html><head><base target="_blank"><style>body{font-family:sans-serif;font-size:14px;line-height:1.6;color:#1A2E45;padding:12px}a{color:#185FA5}img{max-width:100%}</style></head><body>${msg.body_html}</body></html>`;
    const _resize = () => {
      try { const h = iframe.contentWindow.document.body.scrollHeight; if (h > 0) iframe.style.height = (h + 40) + 'px'; } catch(e) {}
    };
    iframe.onload = () => { _resize(); setTimeout(_resize, 800); };
  }

  const attBar = document.getElementById(`th-att-${msg.id}`);
  if (attBar && msg.attachments) {
    for (const a of msg.attachments) {
      const chip = document.createElement('span');
      chip.className = 'em-att-chip';
      chip.innerHTML = `&#128206; ${esc(a.filename)}<span class="em-att-size">${_emFmtSize(a.size)}</span>`;
      chip.addEventListener('click', () => _emDownloadAtt(msg.id, a.id, a.filename));
      attBar.appendChild(chip);
    }
  }
}

function _emRenderThreadFoot(msg, threadId) {
  const foot = document.getElementById('det-foot');
  if (!foot) return;
  foot.innerHTML = '';

  const btn = (label, primary, onclick) => {
    const b = document.createElement('button');
    b.className = `btn ${primary ? 'btn-primary' : 'btn-outline'} btn-sm`;
    b.textContent = label;
    b.onclick = onclick;
    foot.appendChild(b);
    return b;
  };

  btn('Reply',        true,  () => composeReply(msg));
  btn('Reply All',    false, () => composeReplyAll(msg));
  btn('Draft with AI',false, () => _emAiDraft(msg, threadId));
  btn('Forward',      false, () => composeForward(msg));
  btn('Move to…',false, () => _emMoveModal(msg));

  const isStarred = JSON.parse(msg.flags || '[]').includes('\\Flagged');
  const starBtn = btn(isStarred ? '★ Unstar' : '☆ Star', false, async () => {
    const r = await fetch(`/api/emails/${msg.id}/star`, { method: 'POST' }).then(r => r.json()).catch(() => null);
    if (r?.ok) starBtn.textContent = r.data.starred ? '★ Unstar' : '☆ Star';
  });

  btn('Mark Unread', false, () => _emMarkUnread(msg.id));

  if (msg.folder_role === 'trash') {
    btn('Restore to Inbox', false, () => _emRestore(msg.id));
  } else if (msg.folder_role === 'spam') {
    btn('Not Spam', false, async () => {
      const r = await fetch(`/api/emails/${msg.id}/unspam`, { method: 'POST' }).then(r => r.json());
      if (r.ok) { detClose(); _emMessages = _emMessages.filter(m => m.id !== msg.id); _emTotal = Math.max(0, _emTotal - 1); _emRender(true); toast('Moved to Inbox'); }
      else toast(r.error || 'Failed', 'err');
    });
  } else {
    btn('Spam', false, async () => {
      const r = await fetch(`/api/emails/${msg.id}/spam`, { method: 'POST' }).then(r => r.json());
      if (r.ok) { detClose(); _emMessages = _emMessages.filter(m => m.id !== msg.id); _emTotal = Math.max(0, _emTotal - 1); _emRender(true); toast('Marked as spam'); }
      else toast(r.error || 'Failed', 'err');
    });
  }

  const delBtn = btn(msg.folder_role === 'trash' ? 'Delete Forever' : 'Delete', false, () => _emTrash(msg.id));
  delBtn.classList.add('btn-danger');
}

async function _emToggleThreadMsg(msgId) {
  const card   = document.querySelector(`.th-msg[data-mid="${msgId}"]`);
  const body   = document.getElementById(`th-body-${msgId}`);
  if (!card || !body) return;

  const isExpanded = card.classList.contains('expanded');
  const hdrMain    = card.querySelector('.th-hdr-main');

  if (isExpanded) {
    card.classList.replace('expanded', 'collapsed');
    body.style.display = 'none';
    if (hdrMain && !hdrMain.querySelector('.th-snippet')) {
      const snipEl = document.createElement('span');
      snipEl.className = 'th-snippet';
      snipEl.textContent = card.dataset.snippet || '';
      hdrMain.appendChild(snipEl);
    }
    return;
  }

  // Expand
  card.classList.replace('collapsed', 'expanded');
  body.style.display = '';
  hdrMain?.querySelector('.th-snippet')?.remove();

  if (!body.innerHTML.trim() || body.querySelector('.th-loading')) {
    body.innerHTML = '<div class="th-loading">Loading…</div>';
    try {
      const msg = await apiFetch(`/api/emails/${msgId}`);
      _emRenderThreadBody(msg, body);
      _emRenderThreadFoot(msg, msg.thread_id);
      _emOpenMsg = msg;
      fetch(`/api/emails/${msgId}/mark_read`, { method: 'POST' }).catch(() => {});
      card.classList.remove('unread');
      document.querySelector(`tr[data-msgid="${msgId}"]`)?.classList.remove('unread');
    } catch(e) {
      body.innerHTML = `<div class="state-error">Failed to load: ${esc(e.message)}</div>`;
    }
  }
}

function _emParseAddrs(json_str) {
  try { return JSON.parse(json_str || '[]'); } catch(e) { return []; }
}

function _emFmtSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return ` (${bytes} B)`;
  if (bytes < 1024 * 1024) return ` (${(bytes / 1024).toFixed(0)} KB)`;
  return ` (${(bytes / (1024 * 1024)).toFixed(1)} MB)`;
}

async function _emDownloadAtt(msgId, attId, filename) {
  try {
    const r = await fetch(`/api/emails/${msgId}/attachment/${attId}`);
    if (!r.ok) {
      let msg = `Download failed (HTTP ${r.status})`;
      try { const j = await r.json(); if (j.error) msg = j.error; } catch {}
      toast(msg, 'err');
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch(e) {
    toast('Download failed: ' + e.message, 'err');
  }
}

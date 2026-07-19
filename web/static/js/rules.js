// ═══════════════════════════════════════════════════════════════════════════
// FILTERS MODULE — rules, whitelist, blacklist
// Prefix: _rl
// ═══════════════════════════════════════════════════════════════════════════

let _rlAccounts = [];
let _rlRules    = [];
let _rlSenders  = [];

async function pageFilters() {
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading…</div>';
  try {
    [_rlAccounts, _rlRules, _rlSenders] = await Promise.all([
      apiFetch('/api/accounts'),
      apiFetch('/api/rules'),
      apiFetch('/api/sender_lists'),
    ]);
    _rlRender();
  } catch(e) {
    mc.innerHTML = `<div class="state-error">${esc(e.message)}</div>`;
  }
}

function _rlRender() {
  const mc = document.getElementById('module-content');

  const whitelist = _rlSenders.filter(s => s.list_type === 'whitelist');
  const blacklist = _rlSenders.filter(s => s.list_type === 'blacklist');

  mc.innerHTML = `
    <div style="max-width:820px">

      <div class="rl-section">
        <div class="rl-section-hdr">
          <span class="rl-section-title">&#9878; Filter Rules</span>
          <button class="btn btn-primary btn-sm" onclick="_rlAddRule()">+ Add Rule</button>
        </div>
        ${_rlRules.length ? `
        <table class="rl-table">
          <thead><tr><th>Name</th><th>Account</th><th>If</th><th>Action</th><th style="width:80px"></th></tr></thead>
          <tbody>
            ${_rlRules.map(r => `
            <tr>
              <td>${esc(r.name)}</td>
              <td style="font-size:12px;color:var(--ink3)">${esc(r.account_email || '')}</td>
              <td style="font-size:12px">${esc(r.condition_field)} ${esc(r.condition_op)} <strong>${esc(r.condition_value)}</strong></td>
              <td style="font-size:12px">${_rlActionLabel(r)}</td>
              <td>
                <button class="btn btn-outline btn-sm" onclick="_rlEditRule(${r.id})" style="padding:2px 8px">Edit</button>
                <button class="btn btn-outline btn-sm btn-danger" onclick="_rlDeleteRule(${r.id})" style="padding:2px 8px;margin-left:4px">✕</button>
              </td>
            </tr>`).join('')}
          </tbody>
        </table>` : `<p style="font-size:13px;color:var(--ink3);padding:12px 0">No rules yet. Rules are applied automatically to newly-arrived messages.</p>`}
      </div>

      <div class="rl-section">
        <div class="rl-section-hdr">
          <span class="rl-section-title">&#10003; Whitelist</span>
          <button class="btn btn-primary btn-sm" onclick="_rlAddSender('whitelist')">+ Add</button>
        </div>
        <p style="font-size:12px;color:var(--ink3);margin-bottom:10px">Messages from whitelisted senders always bypass all rules.</p>
        ${_rlSenderTable(whitelist, 'whitelist')}
      </div>

      <div class="rl-section">
        <div class="rl-section-hdr">
          <span class="rl-section-title">&#10007; Blacklist</span>
          <button class="btn btn-primary btn-sm" onclick="_rlAddSender('blacklist')">+ Add</button>
        </div>
        <p style="font-size:12px;color:var(--ink3);margin-bottom:10px">Messages from blacklisted senders are automatically moved to Spam.</p>
        ${_rlSenderTable(blacklist, 'blacklist')}
      </div>

    </div>`;
}

function _rlActionLabel(r) {
  const actions = { mark_read:'Mark Read', star:'Star', move:'Move to folder', trash:'Delete', spam:'Mark as Spam' };
  let label = actions[r.action] || r.action;
  if (r.action === 'move' && r.action_folder_name) label += `: ${r.action_folder_name}`;
  return label;
}

function _rlSenderTable(list, type) {
  if (!list.length) return `<p style="font-size:13px;color:var(--ink3)">None.</p>`;
  return `<table class="rl-table"><thead><tr><th>Email</th><th>Account</th><th style="width:60px"></th></tr></thead><tbody>
    ${list.map(s => {
      const acct = _rlAccounts.find(a => a.id === s.account_id);
      return `<tr>
        <td>${esc(s.email)}</td>
        <td style="font-size:12px;color:var(--ink3)">${esc(acct ? acct.email : '')}</td>
        <td><button class="btn btn-outline btn-sm btn-danger" onclick="_rlDeleteSender(${s.id})" style="padding:2px 8px">✕</button></td>
      </tr>`;
    }).join('')}
  </tbody></table>`;
}

function _rlAddRule() {
  _rlOpenRuleForm(null);
}

async function _rlCreateRuleFromEmail(accountId, fromAddr, fromName, subject) {
  if (!_rlAccounts.length) {
    try { _rlAccounts = await apiFetch('/api/accounts'); } catch(e) {}
  }
  const name = fromAddr ? `From: ${fromAddr}` : (subject ? `Subject: ${subject}` : 'New rule');
  await _rlOpenRuleForm({
    id: null,
    account_id: accountId,
    name,
    condition_field: 'from',
    condition_op: 'contains',
    condition_value: fromAddr || '',
    action: 'mark_read',
    action_folder_id: null,
  });
}

function _rlEditRule(id) {
  _rlOpenRuleForm(_rlRules.find(r => r.id === id));
}

async function _rlOpenRuleForm(rule) {
  let folders = [];
  try { folders = await apiFetch('/api/folders'); } catch(e) {}

  detOpen(rule ? 'Edit Rule' : 'Add Rule');
  document.getElementById('det-body').innerHTML = `
    <div class="form-row">
      <label class="form-label">Rule name</label>
      <input class="form-input" id="rl-name" type="text" value="${esc(rule?.name || '')}" placeholder="e.g. Move newsletters">
    </div>
    <div class="form-row">
      <label class="form-label">Account</label>
      <select class="form-select" id="rl-account">
        ${_rlAccounts.map(a => `<option value="${a.id}"${a.id === (rule?.account_id) ? ' selected' : ''}>${esc(a.name)} &lt;${esc(a.email)}&gt;</option>`).join('')}
      </select>
    </div>
    <div class="form-row">
      <label class="form-label">Condition</label>
      <div style="display:flex;gap:8px">
        <select class="form-select" id="rl-field" style="flex:1">
          ${['from','to','subject','any'].map(f => `<option value="${f}"${f === (rule?.condition_field || 'from') ? ' selected' : ''}>${f === 'any' ? 'Any field' : f.charAt(0).toUpperCase()+f.slice(1)}</option>`).join('')}
        </select>
        <select class="form-select" id="rl-op" style="flex:1">
          ${[['contains','contains'],['not_contains','does not contain'],['equals','equals'],['starts_with','starts with']].map(([v,l]) => `<option value="${v}"${v === (rule?.condition_op || 'contains') ? ' selected' : ''}>${l}</option>`).join('')}
        </select>
        <input class="form-input" id="rl-value" type="text" value="${esc(rule?.condition_value || '')}" placeholder="value" style="flex:2">
      </div>
    </div>
    <div class="form-row">
      <label class="form-label">Action</label>
      <select class="form-select" id="rl-action" onchange="_rlToggleFolderPicker()">
        ${[['mark_read','Mark as read'],['star','Star'],['move','Move to folder…'],['spam','Mark as spam'],['trash','Delete']].map(([v,l]) => `<option value="${v}"${v === (rule?.action || 'mark_read') ? ' selected' : ''}>${l}</option>`).join('')}
      </select>
    </div>
    <div class="form-row" id="rl-folder-row"${(rule?.action !== 'move') ? ' style="display:none"' : ''}>
      <label class="form-label">Destination folder</label>
      <select class="form-select" id="rl-folder">
        <option value="">— select folder —</option>
        ${folders.map(f => `<option value="${f.id}"${f.id === rule?.action_folder_id ? ' selected' : ''}>${esc(f.display_name || f.name)} (${esc(f.account_email || '')})</option>`).join('')}
      </select>
    </div>`;

  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';
  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.textContent = rule ? 'Save' : 'Add Rule';
  saveBtn.onclick = () => _rlSaveRule(rule?.id);
  foot.appendChild(saveBtn);
}

function _rlToggleFolderPicker() {
  const action = document.getElementById('rl-action')?.value;
  const row    = document.getElementById('rl-folder-row');
  if (row) row.style.display = action === 'move' ? '' : 'none';
}

async function _rlSaveRule(existingId) {
  const payload = {
    account_id:      parseInt(document.getElementById('rl-account')?.value || '0'),
    name:            (document.getElementById('rl-name')?.value || '').trim(),
    condition_field: document.getElementById('rl-field')?.value,
    condition_op:    document.getElementById('rl-op')?.value,
    condition_value: (document.getElementById('rl-value')?.value || '').trim(),
    action:          document.getElementById('rl-action')?.value,
    action_folder_id: parseInt(document.getElementById('rl-folder')?.value || '0') || null,
  };
  if (!payload.name)            { toast('Rule name is required', 'err'); return; }
  if (!payload.condition_value) { toast('Condition value is required', 'err'); return; }
  if (payload.action === 'move' && !payload.action_folder_id) { toast('Select a destination folder', 'err'); return; }

  try {
    let r;
    if (existingId) {
      r = await fetch(`/api/rules/${existingId}`, {
        method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
      }).then(r => r.json());
    } else {
      r = await fetch('/api/rules', {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
      }).then(r => r.json());
    }
    if (!r.ok) { toast(r.error || 'Save failed', 'err'); return; }
    toast(existingId ? 'Rule updated' : 'Rule added');
    detClose();
    pageFilters();
  } catch(e) { toast('Save failed: ' + e.message, 'err'); }
}

async function _rlDeleteRule(id) {
  if (!confirm('Delete this rule?')) return;
  const r = await fetch(`/api/rules/${id}`, { method: 'DELETE' }).then(r => r.json());
  if (r.ok) { toast('Rule deleted'); pageFilters(); }
  else toast(r.error || 'Delete failed', 'err');
}

function _rlAddSender(listType) {
  const acctId = _rlAccounts[0]?.id || null;
  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.style.display = 'flex';
  bd.innerHTML = `
    <div class="modal-box" style="width:400px">
      <div class="modal-hdr">
        <span>Add to ${listType === 'whitelist' ? 'Whitelist' : 'Blacklist'}</span>
        <button class="det-close" onclick="this.closest('.modal-bd').remove()">&#x2715;</button>
      </div>
      <div class="modal-body" style="padding:16px">
        <div class="form-row">
          <label class="form-label">Account</label>
          <select class="form-select" id="rl-sl-account">
            ${_rlAccounts.map(a => `<option value="${a.id}">${esc(a.name)} &lt;${esc(a.email)}&gt;</option>`).join('')}
          </select>
        </div>
        <div class="form-row">
          <label class="form-label">Email address</label>
          <input class="form-input" id="rl-sl-email" type="email" placeholder="sender@example.com">
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-outline btn-sm" onclick="this.closest('.modal-bd').remove()">Cancel</button>
        <button class="btn btn-primary btn-sm" id="rl-sl-save">Add</button>
      </div>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener('click', e => { if (e.target === bd) bd.remove(); });
  bd.querySelector('#rl-sl-email').focus();
  bd.querySelector('#rl-sl-save').onclick = async () => {
    const email     = (bd.querySelector('#rl-sl-email').value || '').trim();
    const accountId = parseInt(bd.querySelector('#rl-sl-account').value || '0');
    if (!email)     { toast('Email required', 'err'); return; }
    if (!accountId) { toast('Account required', 'err'); return; }
    const r = await fetch('/api/sender_lists', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: accountId, email, list_type: listType }),
    }).then(r => r.json());
    if (r.ok) { bd.remove(); toast('Added'); pageFilters(); }
    else toast(r.error || 'Failed', 'err');
  };
}

async function _rlDeleteSender(id) {
  const r = await fetch(`/api/sender_lists/${id}`, { method: 'DELETE' }).then(r => r.json());
  if (r.ok) { toast('Removed'); pageFilters(); }
  else toast(r.error || 'Failed', 'err');
}

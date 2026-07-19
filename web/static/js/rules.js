// ═══════════════════════════════════════════════════════════════════════════
// FILTERS MODULE — rules, whitelist, blacklist
// Prefix: _rl
// ═══════════════════════════════════════════════════════════════════════════

let _rlAccounts  = [];
let _rlRules     = [];
let _rlSenders   = [];
let _rlRuleSelId = null;

async function pageFilters() {
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading…</div>';
  try {
    [_rlAccounts, _rlRules, _rlSenders] = await Promise.all([
      apiFetch('/api/accounts'),
      apiFetch('/api/rules'),
      apiFetch('/api/sender_lists'),
    ]);
    _rlRuleSelId = null;
    _rlRender();
  } catch(e) {
    mc.innerHTML = `<div class="state-error">${esc(e.message)}</div>`;
  }
}

function _rlRender() {
  const mc = document.getElementById('module-content');
  const whitelist = _rlSenders.filter(s => s.list_type === 'whitelist');
  const blacklist = _rlSenders.filter(s => s.list_type === 'blacklist');
  const selRule   = _rlRules.find(r => r.id === _rlRuleSelId);

  mc.innerHTML = `
    <div style="max-width:860px">

      <div class="rl-section">
        <div class="rl-section-hdr">
          <span class="rl-section-title">&#9878; Filter Rules</span>
          <div class="rl-toolbar">
            ${selRule ? `
              <button class="btn btn-outline btn-sm" onclick="_rlEditRule(${selRule.id})">&#9998; Edit</button>
              <button class="btn btn-outline btn-sm btn-danger" onclick="_rlDeleteRule(${selRule.id})">&#10005; Delete</button>
            ` : ''}
            <button class="btn btn-outline btn-sm" onclick="_rlRunRules()" title="Apply rules to all inbox messages now">&#9654; Run Now</button>
            <button class="btn btn-primary btn-sm" onclick="_rlAddRule()">+ Add Rule</button>
          </div>
        </div>
        <p class="rl-hint">Rules run in priority order (highest first). First terminal action (move/trash/spam) stops the chain.</p>
        ${_rlRules.length ? `
        <table class="rl-table">
          <thead><tr>
            <th style="width:50px">Priority</th>
            <th>Name</th>
            <th>Account</th>
            <th>Condition</th>
            <th>Action</th>
            <th style="width:80px">Status</th>
          </tr></thead>
          <tbody>
            ${_rlRules.map(r => `
            <tr class="rl-rule-row${r.id === _rlRuleSelId ? ' rl-row-selected' : ''}" onclick="_rlRuleSelect(${r.id})">
              <td style="text-align:center;color:var(--ink3)">${r.priority || 0}</td>
              <td>${esc(r.name)}</td>
              <td class="rl-cell-sm">${esc(r.account_email || '')}</td>
              <td class="rl-cell-sm">${esc(r.condition_field)} <em>${esc(r.condition_op.replace('_',' '))}</em> <strong>${esc(r.condition_value)}</strong></td>
              <td class="rl-cell-sm">${_rlActionLabel(r)}</td>
              <td>
                <span class="rl-badge ${r.active ? 'rl-badge-active' : 'rl-badge-inactive'}"
                      onclick="event.stopPropagation();_rlToggleActive(${r.id},${r.active ? 0 : 1})"
                      title="Click to toggle">
                  ${r.active ? 'Active' : 'Inactive'}
                </span>
              </td>
            </tr>`).join('')}
          </tbody>
        </table>` : `<p class="rl-empty">No rules yet. Rules are applied automatically to newly-arrived messages.</p>`}
      </div>

      <div class="rl-section">
        <div class="rl-section-hdr">
          <span class="rl-section-title">&#10003; Whitelist</span>
          <button class="btn btn-primary btn-sm" onclick="_rlAddSender('whitelist')">+ Add</button>
        </div>
        <p class="rl-hint">Whitelisted senders bypass all rules. Enter a full email address or <code>@domain.com</code> to match all senders from a domain.</p>
        ${_rlSenderTable(whitelist)}
      </div>

      <div class="rl-section">
        <div class="rl-section-hdr">
          <span class="rl-section-title">&#10007; Blacklist</span>
          <button class="btn btn-primary btn-sm" onclick="_rlAddSender('blacklist')">+ Add</button>
        </div>
        <p class="rl-hint">Blacklisted senders are automatically moved to Spam. Supports <code>@domain.com</code> for domain-wide blocking.</p>
        ${_rlSenderTable(blacklist)}
      </div>

    </div>`;
}

function _rlRuleSelect(id) {
  _rlRuleSelId = (_rlRuleSelId === id) ? null : id;
  _rlRender();
}

function _rlActionLabel(r) {
  const actions = { mark_read:'Mark Read', star:'Star', move:'Move to folder', trash:'Delete', spam:'Mark as Spam' };
  let label = actions[r.action] || r.action;
  if (r.action === 'move' && r.action_folder_name) label += `: ${r.action_folder_name}`;
  return label;
}

function _rlSenderTable(list) {
  if (!list.length) return `<p class="rl-empty">None.</p>`;
  return `<table class="rl-table"><thead><tr><th>Email / Domain</th><th>Account</th><th style="width:50px"></th></tr></thead><tbody>
    ${list.map(s => {
      const acct = _rlAccounts.find(a => a.id === s.account_id);
      return `<tr>
        <td>${esc(s.email)}</td>
        <td class="rl-cell-sm">${esc(acct ? acct.email : '')}</td>
        <td><button class="btn btn-outline btn-sm btn-danger" onclick="_rlDeleteSender(${s.id})" style="padding:2px 8px">&#10005;</button></td>
      </tr>`;
    }).join('')}
  </tbody></table>`;
}

async function _rlToggleActive(id, newVal) {
  const r = await fetch(`/api/rules/${id}`, {
    method: 'PUT', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ active: newVal }),
  }).then(r => r.json());
  if (r.ok) {
    const rule = _rlRules.find(x => x.id === id);
    if (rule) rule.active = newVal;
    _rlRender();
  } else {
    toast(r.error || 'Failed', 'err');
  }
}

async function _rlRunRules() {
  const acctId = _rlAccounts.length === 1 ? _rlAccounts[0].id : null;
  try {
    const r = await fetch('/api/rules/run', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(acctId ? { account_id: acctId } : {}),
    }).then(r => r.json());
    if (r.ok) {
      const { processed, matched } = r.data;
      toast(`Rules run: ${matched} match${matched !== 1 ? 'es' : ''} across ${processed} inbox message${processed !== 1 ? 's' : ''}`);
      pageFilters();
    } else {
      toast(r.error || 'Run failed', 'err');
    }
  } catch(e) { toast('Run failed: ' + e.message, 'err'); }
}

function _rlAddRule() {
  _rlOpenRuleForm(null);
}

function _rlEditRule(id) {
  _rlOpenRuleForm(_rlRules.find(r => r.id === id));
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
    active: 1,
    priority: 0,
  });
}

async function _rlOpenRuleForm(rule) {
  let folders = [];
  try { folders = await apiFetch('/api/folders'); } catch(e) {}

  detOpen(rule?.id ? 'Edit Rule' : 'Add Rule');
  document.getElementById('det-body').innerHTML = `
    <div class="form-row">
      <label class="form-label">Rule name</label>
      <input class="form-input" id="rl-name" type="text" value="${esc(rule?.name || '')}" placeholder="e.g. Move newsletters">
    </div>
    <div class="form-row">
      <label class="form-label">Account</label>
      <select class="form-select" id="rl-account">
        ${_rlAccounts.map(a => `<option value="${a.id}"${a.id === rule?.account_id ? ' selected' : ''}>${esc(a.name)} &lt;${esc(a.email)}&gt;</option>`).join('')}
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
    <div class="form-row" id="rl-folder-row"${rule?.action !== 'move' ? ' style="display:none"' : ''}>
      <label class="form-label">Destination folder</label>
      <select class="form-select" id="rl-folder">
        <option value="">— select folder —</option>
        ${folders.map(f => `<option value="${f.id}"${f.id === rule?.action_folder_id ? ' selected' : ''}>${esc(f.display_name || f.name)} (${esc(f.account_email || '')})</option>`).join('')}
      </select>
    </div>
    <div class="form-row" style="display:flex;gap:16px">
      <div style="flex:1">
        <label class="form-label">Priority</label>
        <input class="form-input" id="rl-priority" type="number" value="${rule?.priority ?? 0}" min="0" placeholder="0">
        <p style="font-size:11px;color:var(--ink3);margin:4px 0 0">Higher numbers run first.</p>
      </div>
      <div style="flex:1;display:flex;align-items:center;gap:8px;padding-top:22px">
        <input type="checkbox" id="rl-active" ${(rule?.active ?? 1) ? 'checked' : ''}>
        <label for="rl-active" class="form-label" style="margin:0">Active</label>
      </div>
    </div>`;

  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';
  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.textContent = rule?.id ? 'Save' : 'Add Rule';
  saveBtn.onclick = () => _rlSaveRule(rule?.id || null);
  foot.appendChild(saveBtn);
}

function _rlToggleFolderPicker() {
  const action = document.getElementById('rl-action')?.value;
  const row    = document.getElementById('rl-folder-row');
  if (row) row.style.display = action === 'move' ? '' : 'none';
}

async function _rlSaveRule(existingId) {
  const payload = {
    account_id:       parseInt(document.getElementById('rl-account')?.value || '0'),
    name:             (document.getElementById('rl-name')?.value || '').trim(),
    condition_field:  document.getElementById('rl-field')?.value,
    condition_op:     document.getElementById('rl-op')?.value,
    condition_value:  (document.getElementById('rl-value')?.value || '').trim(),
    action:           document.getElementById('rl-action')?.value,
    action_folder_id: parseInt(document.getElementById('rl-folder')?.value || '0') || null,
    priority:         parseInt(document.getElementById('rl-priority')?.value || '0') || 0,
    active:           document.getElementById('rl-active')?.checked ? 1 : 0,
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
  if (r.ok) { toast('Rule deleted'); _rlRuleSelId = null; pageFilters(); }
  else toast(r.error || 'Delete failed', 'err');
}

function _rlAddSender(listType) {
  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.style.display = 'flex';
  bd.innerHTML = `
    <div class="modal-box" style="width:420px">
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
          <label class="form-label">Email address or domain</label>
          <input class="form-input" id="rl-sl-email" type="text" placeholder="sender@example.com or @example.com">
          <p style="font-size:11px;color:var(--ink3);margin:4px 0 0">Enter an email address for a single sender, or <code>@domain.com</code> to match all senders from a domain.</p>
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
    if (!email)     { toast('Email or domain required', 'err'); return; }
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

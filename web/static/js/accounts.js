// ═══════════════════════════════════════════════════════════════════════════
// ACCOUNTS MODULE — account list + add/edit wizard
// Prefix: _acct
// ═══════════════════════════════════════════════════════════════════════════

const _ACCT_COLOURS = ['#185FA5','#3B6D11','#8a5a00','#A32D2D','#00695c','#7c3aed'];

// Provider presets (IMAP/SMTP defaults)
const _ACCT_PRESETS = {
  gmail: {
    name: 'Gmail',
    imap_host: 'imap.gmail.com', imap_port: 993, imap_ssl: 1,
    smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_ssl: 0,
    hint: 'Use an App Password — Google Account → Security → 2-Step Verification → App passwords',
  },
  outlook: {
    name: 'Outlook / Microsoft 365',
    imap_host: 'outlook.office365.com', imap_port: 993, imap_ssl: 1,
    smtp_host: 'smtp.office365.com', smtp_port: 587, smtp_ssl: 0,
    hint: 'Use an App Password via Microsoft Account → Security → Advanced security options',
  },
  internode: {
    name: 'Internode',
    imap_host: 'mail.internode.on.net', imap_port: 993, imap_ssl: 1,
    smtp_host: 'mail.internode.on.net', smtp_port: 587, smtp_ssl: 0,
    hint: '',
  },
  imap: {
    name: 'Other (IMAP)',
    imap_host: '', imap_port: 993, imap_ssl: 1,
    smtp_host: '', smtp_port: 587, smtp_ssl: 0,
    hint: '',
  },
};

let _acctList = [];
let _acctPreset = null;

async function pageAccounts() {
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading…</div>';
  try {
    _acctList = await apiFetch('/api/accounts');
    _acctRender();
  } catch(e) {
    mc.innerHTML = `<div class="state-error">${esc(e.message)}</div>`;
  }
}

function _acctRender() {
  const mc = document.getElementById('module-content');

  const rows = _acctList.length
    ? _acctList.map((a, i) => {
        const colour = _ACCT_COLOURS[i % _ACCT_COLOURS.length];
        return `<div class="acct-row" onclick="_acctEdit(${a.id})">
          <span class="acct-dot" style="background:${colour}"></span>
          <div class="acct-info">
            <div class="acct-name">${esc(a.name)}</div>
            <div class="acct-email">${esc(a.email)}</div>
          </div>
          <div class="acct-stats">
            ${a.unread_count ? `<span style="color:var(--accent)">${a.unread_count} unread</span> · ` : ''}
            ${a.message_count || 0} messages
            ${a.last_sync ? `<br><span style="color:var(--ink3)">Last sync: ${fmtDate(a.last_sync)}</span>` : ''}
          </div>
        </div>`;
      }).join('')
    : `<div class="em-empty">No accounts configured yet.<br>Add an account to get started.</div>`;

  mc.innerHTML = `
    <div class="acct-list-panel">${rows}</div>
    <button class="btn btn-primary" onclick="_acctAddWizard()">+ Add Account</button>
    <div class="ai-settings-card" id="ai-settings-card" style="margin-top:28px">
      <div class="ai-settings-title">&#10022; AI Settings</div>
      <div class="ai-settings-body">
        <p style="font-size:13px;color:var(--ink2);margin-bottom:14px">
          Dogbox Mailman uses Claude (Anthropic) for email summarisation, triage, and draft assistance.
          Provide your API key to enable these features.
        </p>
        <label class="form-label">Anthropic API Key</label>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="password" id="ai-key-input" class="form-control" placeholder="sk-ant-..." style="flex:1;font-family:monospace">
          <button class="btn btn-primary btn-sm" onclick="_acctSaveAIKey()">Save</button>
        </div>
        <div id="ai-key-status" style="margin-top:8px;font-size:12px;color:var(--ink3)">Loading…</div>
      </div>
    </div>`;
  _acctLoadAIKeyStatus();
}

function _acctAddWizard() {
  detOpen('Add Email Account');
  _acctPreset = null;

  document.getElementById('det-body').innerHTML = `
    <p style="font-size:13px;color:var(--ink2);margin-bottom:16px">
      Choose your email provider to pre-fill connection settings.
    </p>
    <div class="provider-grid">
      ${Object.entries(_ACCT_PRESETS).map(([key, p]) =>
        `<div class="provider-btn" id="prov-${key}" onclick="_acctSelectPreset('${key}')">
          <div class="provider-name">${p.name}</div>
        </div>`
      ).join('')}
    </div>
    <div id="acct-form-container"></div>`;

  document.getElementById('det-foot').innerHTML = '';
}

function _acctSelectPreset(key) {
  _acctPreset = key;
  document.querySelectorAll('.provider-btn').forEach(el => el.classList.remove('selected'));
  const btn = document.getElementById(`prov-${key}`);
  if (btn) btn.classList.add('selected');
  _acctRenderForm(_ACCT_PRESETS[key]);
}

function _acctRenderForm(preset) {
  const container = document.getElementById('acct-form-container');
  if (!container) return;

  container.innerHTML = `
    ${preset.hint ? `<div style="background:var(--amber-dim);border:1px solid var(--amber);border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--amber)">${esc(preset.hint)}</div>` : ''}
    <div class="form-row">
      <label class="form-label">Account name (display)</label>
      <input class="form-input" id="af-name" type="text" placeholder="e.g. Work Gmail" value="${esc(preset.name || '')}">
    </div>
    <div class="form-row">
      <label class="form-label">Email address</label>
      <input class="form-input" id="af-email" type="email" placeholder="you@example.com">
    </div>
    <div class="form-row">
      <label class="form-label">Username (usually same as email)</label>
      <input class="form-input" id="af-username" type="text" placeholder="you@example.com">
    </div>
    <div class="form-row">
      <label class="form-label">Password / App Password</label>
      <input class="form-input" id="af-password" type="password" placeholder="••••••••••••">
    </div>
    <details style="margin-bottom:14px">
      <summary style="cursor:pointer;font-size:12px;color:var(--ink3);user-select:none;margin-bottom:10px">Advanced settings</summary>
      <div style="display:grid;grid-template-columns:1fr 80px 80px;gap:8px;align-items:end;margin-bottom:8px">
        <div class="form-row" style="margin:0">
          <label class="form-label">IMAP Host</label>
          <input class="form-input" id="af-imap-host" type="text" value="${esc(preset.imap_host || '')}">
        </div>
        <div class="form-row" style="margin:0">
          <label class="form-label">Port</label>
          <input class="form-input" id="af-imap-port" type="number" value="${preset.imap_port || 993}">
        </div>
        <div class="form-row" style="margin:0">
          <label class="form-label">SSL</label>
          <select class="form-select" id="af-imap-ssl">
            <option value="1"${preset.imap_ssl ? ' selected' : ''}>Yes</option>
            <option value="0"${!preset.imap_ssl ? ' selected' : ''}>No</option>
          </select>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 80px 80px;gap:8px;align-items:end">
        <div class="form-row" style="margin:0">
          <label class="form-label">SMTP Host</label>
          <input class="form-input" id="af-smtp-host" type="text" value="${esc(preset.smtp_host || '')}">
        </div>
        <div class="form-row" style="margin:0">
          <label class="form-label">Port</label>
          <input class="form-input" id="af-smtp-port" type="number" value="${preset.smtp_port || 587}">
        </div>
        <div class="form-row" style="margin:0">
          <label class="form-label">STARTTLS</label>
          <select class="form-select" id="af-smtp-ssl">
            <option value="0"${!preset.smtp_ssl ? ' selected' : ''}>STARTTLS</option>
            <option value="1"${preset.smtp_ssl ? ' selected' : ''}>SSL/TLS</option>
          </select>
        </div>
      </div>
    </details>
    <div id="acct-test-result" style="margin-bottom:8px"></div>`;

  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';

  const testBtn = document.createElement('button');
  testBtn.className = 'btn btn-outline btn-sm';
  testBtn.textContent = 'Test Connection';
  testBtn.onclick = _acctTestConn;
  foot.appendChild(testBtn);

  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.id = 'acct-save-btn';
  saveBtn.textContent = 'Save Account';
  saveBtn.onclick = _acctSave;
  foot.appendChild(saveBtn);
}

function _acctCollectForm() {
  return {
    name: document.getElementById('af-name')?.value.trim() || '',
    email: document.getElementById('af-email')?.value.trim() || '',
    username: document.getElementById('af-username')?.value.trim() || '',
    password: document.getElementById('af-password')?.value || '',
    provider: _acctPreset || 'imap',
    imap_host: document.getElementById('af-imap-host')?.value.trim() || '',
    imap_port: parseInt(document.getElementById('af-imap-port')?.value || '993'),
    imap_ssl: parseInt(document.getElementById('af-imap-ssl')?.value || '1'),
    smtp_host: document.getElementById('af-smtp-host')?.value.trim() || '',
    smtp_port: parseInt(document.getElementById('af-smtp-port')?.value || '587'),
    smtp_ssl: parseInt(document.getElementById('af-smtp-ssl')?.value || '0'),
  };
}

async function _acctTestConn() {
  const data = _acctCollectForm();
  const resultEl = document.getElementById('acct-test-result');
  if (resultEl) resultEl.innerHTML = '<span style="color:var(--ink3);font-size:12px">Testing…</span>';

  try {
    const r = await fetch('/api/accounts/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const j = await r.json();
    if (resultEl) {
      if (j.ok) {
        resultEl.innerHTML = `<span style="color:var(--green);font-size:12px">✓ ${esc(j.data.message)}</span>`;
      } else {
        resultEl.innerHTML = `<span style="color:var(--red);font-size:12px">✕ ${esc(j.error)}</span>`;
      }
    }
  } catch(e) {
    if (resultEl) resultEl.innerHTML = `<span style="color:var(--red);font-size:12px">✕ ${esc(e.message)}</span>`;
  }
}

async function _acctSave() {
  const data = _acctCollectForm();
  if (!data.name) { toast('Account name is required', 'err'); return; }
  if (!data.email) { toast('Email address is required', 'err'); return; }
  if (!data.imap_host) { toast('IMAP host is required', 'err'); return; }
  if (!data.smtp_host) { toast('SMTP host is required', 'err'); return; }

  const btn = document.getElementById('acct-save-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  try {
    const r = await fetch('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const j = await r.json();
    if (j.ok) {
      toast('Account saved — syncing inbox…');
      detClose();
      pageAccounts();
    } else {
      toast(j.error || 'Save failed', 'err');
      if (btn) { btn.disabled = false; btn.textContent = 'Save Account'; }
    }
  } catch(e) {
    toast('Save failed: ' + e.message, 'err');
    if (btn) { btn.disabled = false; btn.textContent = 'Save Account'; }
  }
}

function _acctEdit(id) {
  const acct = _acctList.find(a => a.id === id);
  if (!acct) return;
  detOpen(`Edit — ${acct.name}`);

  document.getElementById('det-body').innerHTML = `
    <div class="form-row">
      <label class="form-label">Account name</label>
      <input class="form-input" id="af-edit-name" type="text" value="${esc(acct.name)}">
    </div>
    <div class="form-row">
      <label class="form-label">Email address</label>
      <input class="form-input" id="af-edit-email" type="email" value="${esc(acct.email)}">
    </div>
    <div class="form-row">
      <label class="form-label">New password (leave blank to keep current)</label>
      <input class="form-input" id="af-edit-password" type="password" placeholder="••••••••••••">
    </div>`;

  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';

  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.textContent = 'Save Changes';
  saveBtn.onclick = async () => {
    const payload = {
      name: document.getElementById('af-edit-name')?.value.trim() || '',
      email: document.getElementById('af-edit-email')?.value.trim() || '',
    };
    const pw = document.getElementById('af-edit-password')?.value || '';
    if (pw) payload.password = pw;
    const r = await fetch(`/api/accounts/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const j = await r.json();
    if (j.ok) { toast('Account updated'); detClose(); pageAccounts(); }
    else { toast(j.error || 'Update failed', 'err'); }
  };
  foot.appendChild(saveBtn);

  const delBtn = document.createElement('button');
  delBtn.className = 'btn btn-danger btn-sm';
  delBtn.textContent = 'Remove Account';
  delBtn.onclick = async () => {
    if (!confirm(`Remove account "${acct.name}"? This deletes all synced mail.`)) return;
    const r = await fetch(`/api/accounts/${id}`, { method: 'DELETE' });
    const j = await r.json();
    if (j.ok) { toast('Account removed'); detClose(); pageAccounts(); }
    else { toast(j.error || 'Delete failed', 'err'); }
  };
  foot.appendChild(delBtn);
}

async function _acctLoadAIKeyStatus() {
  const el = document.getElementById('ai-key-status');
  if (!el) return;
  try {
    const r = await apiFetch('/api/settings/ai_key');
    if (r.set) {
      el.innerHTML = `<span style="color:var(--green)">&#10003; API key saved (${esc(r.masked)})</span>`;
    } else {
      el.textContent = 'No API key saved.';
    }
  } catch(e) {
    el.textContent = '';
  }
}

async function _acctSaveAIKey() {
  const input = document.getElementById('ai-key-input');
  const key = (input?.value || '').trim();
  if (!key) { toast('Enter an API key', 'err'); return; }
  const r = await fetch('/api/settings/ai_key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  }).then(r => r.json());
  if (r.ok) {
    toast('API key saved');
    input.value = '';
    _acctLoadAIKeyStatus();
  } else {
    toast(r.error || 'Save failed', 'err');
  }
}

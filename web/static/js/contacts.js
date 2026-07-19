// ═══════════════════════════════════════════════════════════════════════════
// CONTACTS MODULE — address book
// Prefix: _cnt
// ═══════════════════════════════════════════════════════════════════════════

let _cntContacts = [];
let _cntSearch   = '';
let _cntSearchTimer = null;

async function pageContacts() {
  _currentModule = 'contacts';
  _setNavActive('contacts');
  document.getElementById('page-title').textContent = 'Contacts';
  detClose();
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading...</div>';
  try {
    await _cntLoad();
  } catch(e) {
    mc.innerHTML = `<div class="state-error">Failed to load: ${esc(e.message)}</div>`;
  }
}

async function _cntLoad() {
  const params = new URLSearchParams();
  if (_cntSearch) params.set('q', _cntSearch);
  _cntContacts = await apiFetch('/api/contacts' + (_cntSearch ? '?' + params : ''));
  _cntRender();
}

function _cntRender() {
  const mc = document.getElementById('module-content');
  const rows = _cntContacts;

  mc.innerHTML = `
    <div class="em-toolbar">
      <input class="em-search" id="cnt-q" placeholder="Search contacts…" value="${esc(_cntSearch)}">
      <button class="btn btn-outline btn-sm" onclick="_cntImportDbox()" id="cnt-import-btn">&#8659; Import from Dogbox</button>
      <button class="btn btn-primary btn-sm" onclick="_cntOpenNew()">+ Add Contact</button>
    </div>
    <div class="em-list-panel">
      <div class="tbl-overflow-x">
        <table class="em-list-table">
          <thead><tr>
            <th>Name</th>
            <th>Email</th>
            <th>Company</th>
            <th>Phone</th>
            <th style="width:70px">Source</th>
            <th style="width:60px"></th>
          </tr></thead>
          <tbody>
            ${rows.length
              ? rows.map(_cntRow).join('')
              : `<tr><td colspan="6" class="em-empty">No contacts yet — add one or import from Dogbox</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
    <div class="mt-8">
      <span class="count-pill">${rows.length} contact${rows.length !== 1 ? 's' : ''}</span>
    </div>`;

  const q = document.getElementById('cnt-q');
  if (q) {
    q.addEventListener('input', e => {
      _cntSearch = e.target.value;
      clearTimeout(_cntSearchTimer);
      _cntSearchTimer = setTimeout(_cntLoad, 300);
    });
    q.addEventListener('keydown', e => {
      if (e.key === 'Escape') { _cntSearch = ''; q.value = ''; _cntLoad(); }
    });
  }
}

function _cntRow(c) {
  const sourceBadge = c.source === 'import_dbox'
    ? `<span class="cnt-badge cnt-badge-dbox">dbox</span>`
    : c.source === 'auto'
      ? `<span class="cnt-badge cnt-badge-auto">auto</span>`
      : '';
  return `<tr class="em-row" onclick="_cntOpenEdit(${c.id})">
    <td class="em-from">${esc(c.name)}</td>
    <td>${esc(c.email)}</td>
    <td>${esc(c.company || '')}</td>
    <td>${esc(c.phone || '')}</td>
    <td>${sourceBadge}</td>
    <td onclick="event.stopPropagation()">
      <button class="btn btn-outline btn-sm btn-danger" style="padding:2px 8px" onclick="_cntDelete(${c.id})">&#10005;</button>
    </td>
  </tr>`;
}

async function _cntOpenNew() {
  detOpen('New Contact');
  document.getElementById('det-body').innerHTML = _cntForm({});
  const foot = document.getElementById('det-foot');
  foot.innerHTML = '';
  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn btn-primary btn-sm';
  saveBtn.textContent = 'Save';
  saveBtn.onclick = () => _cntSave(null, saveBtn);
  foot.appendChild(saveBtn);
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'btn btn-outline btn-sm';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.onclick = detClose;
  foot.appendChild(cancelBtn);
  document.getElementById('cnt-name')?.focus();
}

async function _cntOpenEdit(cid) {
  detOpen('Edit Contact');
  document.getElementById('det-body').innerHTML = '<div class="state-loading">Loading...</div>';
  try {
    const c = await apiFetch(`/api/contacts/${cid}`);
    document.getElementById('det-body').innerHTML = _cntForm(c);
    const foot = document.getElementById('det-foot');
    foot.innerHTML = '';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn btn-primary btn-sm';
    saveBtn.textContent = 'Save';
    saveBtn.onclick = () => _cntSave(cid, saveBtn);
    foot.appendChild(saveBtn);
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-outline btn-sm';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = detClose;
    foot.appendChild(cancelBtn);
  } catch(e) {
    document.getElementById('det-body').innerHTML = `<div class="state-error">${esc(e.message)}</div>`;
  }
}

function _cntForm(c) {
  return `
    <div class="form-group">
      <label class="form-label">Name <span class="req">*</span></label>
      <input type="text" id="cnt-name" class="form-input" value="${esc(c.name || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Email <span class="req">*</span></label>
      <input type="text" id="cnt-email" class="form-input" value="${esc(c.email || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Alt Email</label>
      <input type="text" id="cnt-email-alt" class="form-input" value="${esc(c.email_alt || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Phone</label>
      <input type="text" id="cnt-phone" class="form-input" value="${esc(c.phone || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Company</label>
      <input type="text" id="cnt-company" class="form-input" value="${esc(c.company || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Notes</label>
      <textarea id="cnt-notes" class="form-input" rows="3">${esc(c.notes || '')}</textarea>
    </div>`;
}

async function _cntSave(cid, btn) {
  const name      = document.getElementById('cnt-name')?.value.trim();
  const email     = document.getElementById('cnt-email')?.value.trim();
  const email_alt = document.getElementById('cnt-email-alt')?.value.trim();
  const phone     = document.getElementById('cnt-phone')?.value.trim();
  const company   = document.getElementById('cnt-company')?.value.trim();
  const notes     = document.getElementById('cnt-notes')?.value.trim();

  if (!name)  { toast('Name is required', 'err'); return; }
  if (!email) { toast('Email is required', 'err'); return; }

  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const method = cid ? 'PUT' : 'POST';
    const url    = cid ? `/api/contacts/${cid}` : '/api/contacts';
    const r = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, email_alt, phone, company, notes }),
    }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Save failed', 'err'); btn.disabled = false; btn.textContent = 'Save'; return; }
    detClose();
    await _cntLoad();
    toast(cid ? 'Contact updated' : 'Contact added');
  } catch(e) {
    toast('Save failed: ' + e.message, 'err');
    btn.disabled = false; btn.textContent = 'Save';
  }
}

async function _cntDelete(cid) {
  if (!confirm('Delete this contact?')) return;
  try {
    const r = await fetch(`/api/contacts/${cid}`, { method: 'DELETE' }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Delete failed', 'err'); return; }
    detClose();
    await _cntLoad();
    toast('Contact deleted');
  } catch(e) { toast('Delete failed: ' + e.message, 'err'); }
}

async function _cntImportDbox() {
  const btn = document.getElementById('cnt-import-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Importing…'; }
  try {
    const r = await fetch('/api/contacts/import_dbox', { method: 'POST' }).then(r => r.json());
    if (!r.ok) { toast(r.error || 'Import failed', 'err'); return; }
    await _cntLoad();
    toast(`Imported ${r.data.imported} contact${r.data.imported !== 1 ? 's' : ''} from Dogbox`);
  } catch(e) {
    toast('Import failed: ' + e.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '⇙ Import from Dogbox'; }
  }
}

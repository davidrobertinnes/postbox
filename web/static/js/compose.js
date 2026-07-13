// ═══════════════════════════════════════════════════════════════════════════
// COMPOSE MODULE — new email, reply, reply-all, forward
// Prefix: _cmp
// ═══════════════════════════════════════════════════════════════════════════

let _cmpFiles = [];  // File objects staged for send

function composeNew(accountId = null) {
  _cmpOpen({ title: 'New Message', subject: '', to: '', body: '', accountId });
}

function composeReply(msg, draftBody) {
  const subject   = (msg.subject || '').startsWith('Re:') ? msg.subject : `Re: ${msg.subject}`;
  const quoteDate = fmtDate(msg.date);
  const quoteName = msg.from_name || msg.from_addr || '';
  const quoteBody = (msg.body_text || '').trim().split('\n').map(l => '> ' + l).join('\n');
  const body      = draftBody || `\n\n\nOn ${quoteDate}, ${quoteName} wrote:\n${quoteBody}`;
  _cmpOpen({
    title: 'Reply',
    to: msg.from_addr || '',
    subject, body,
    replyMsgId: msg.message_id,
    references: msg.message_id,
    accountId: msg.account_id,
  });
}

function composeReplyAll(msg) {
  const subject  = (msg.subject || '').startsWith('Re:') ? msg.subject : `Re: ${msg.subject}`;
  const ownEmail = (msg.account_email || '').toLowerCase();
  const _parse   = (json) => { try { return JSON.parse(json || '[]'); } catch(e) { return []; } };
  const ccList   = [..._parse(msg.to_addrs), ..._parse(msg.cc_addrs)]
    .filter(a => (a.addr || '').toLowerCase() !== ownEmail)
    .map(a => a.name ? `${a.name} <${a.addr}>` : a.addr);
  const quoteDate = fmtDate(msg.date);
  const quoteName = msg.from_name || msg.from_addr || '';
  const quoteBody = (msg.body_text || '').trim().split('\n').map(l => '> ' + l).join('\n');
  const body      = `\n\n\nOn ${quoteDate}, ${quoteName} wrote:\n${quoteBody}`;
  _cmpOpen({
    title: 'Reply All',
    to: msg.from_addr || '',
    cc: ccList.join(', '),
    subject, body,
    replyMsgId: msg.message_id,
    references: msg.message_id,
    accountId: msg.account_id,
  });
}

function composeForward(msg) {
  const subject   = (msg.subject || '').startsWith('Fwd:') ? msg.subject : `Fwd: ${msg.subject}`;
  const quoteDate = fmtDate(msg.date);
  const quoteFrom = msg.from_name ? `${msg.from_name} <${msg.from_addr}>` : msg.from_addr;
  const body      = `\n\n\n---------- Forwarded message ----------\nFrom: ${quoteFrom}\nDate: ${quoteDate}\nSubject: ${msg.subject}\n\n${(msg.body_text || '').trim()}`;
  _cmpOpen({ title: 'Forward', to: '', subject, body, accountId: msg.account_id });
}

function _cmpOpen(opts) {
  const existing = document.getElementById('cmp-modal');
  if (existing) existing.remove();
  _cmpFiles = [];

  const hasBcc = !!(opts.bcc);
  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.id = 'cmp-modal';
  bd.style.display = 'flex';

  bd.innerHTML = `<div class="modal-box cmp-box">
    <div class="modal-hdr">
      <div class="modal-title">${esc(opts.title || 'New Message')}</div>
      <button class="cmp-bcc-btn" id="cmp-bcc-btn" onclick="_cmpToggleBcc()"${hasBcc ? ' style="display:none"' : ''}>+ BCC</button>
      <button class="det-close" onclick="_cmpClose()">✕</button>
    </div>
    <div class="modal-body">
      <div class="cmp-field">
        <span class="cmp-label">From</span>
        <select class="cmp-input" id="cmp-account"></select>
      </div>
      <div class="cmp-field">
        <span class="cmp-label">To</span>
        <input class="cmp-input" id="cmp-to" type="text" placeholder="recipient@example.com" value="${esc(opts.to || '')}">
      </div>
      <div class="cmp-field">
        <span class="cmp-label">CC</span>
        <input class="cmp-input" id="cmp-cc" type="text" placeholder="cc@example.com" value="${esc(opts.cc || '')}">
      </div>
      <div class="cmp-field" id="cmp-bcc-field"${hasBcc ? '' : ' style="display:none"'}>
        <span class="cmp-label">BCC</span>
        <input class="cmp-input" id="cmp-bcc" type="text" placeholder="bcc@example.com" value="${esc(opts.bcc || '')}">
      </div>
      <div class="cmp-field">
        <span class="cmp-label">Subject</span>
        <input class="cmp-input" id="cmp-subject" type="text" placeholder="Subject" value="${esc(opts.subject || '')}">
      </div>
      <textarea class="cmp-body" id="cmp-body" placeholder="Write your message…">${esc(opts.body || '')}</textarea>
      <div class="cmp-attach-bar" id="cmp-attach-bar" style="display:none"></div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-outline btn-sm cmp-attach-btn" onclick="document.getElementById('cmp-file-input').click()">&#128206; Attach</button>
      <input type="file" id="cmp-file-input" multiple style="display:none" onchange="_cmpFilesAdded(this)">
      <span style="flex:1"></span>
      <button class="btn btn-outline btn-sm" onclick="_cmpClose()">Cancel</button>
      <button class="btn btn-primary btn-sm" id="cmp-send-btn" onclick="_cmpSend()">Send →</button>
    </div>
  </div>`;

  document.body.appendChild(bd);
  _cmpPopulateAccounts(opts.accountId);

  bd._replyMsgId = opts.replyMsgId || null;
  bd._references = opts.references || null;
  bd._isNew      = !(opts.body);

  if (!opts.to) {
    document.getElementById('cmp-to')?.focus();
  } else {
    const bodyEl = document.getElementById('cmp-body');
    if (bodyEl) { bodyEl.focus(); bodyEl.setSelectionRange(0, 0); }
  }
}

function _cmpClose() {
  document.getElementById('cmp-modal')?.remove();
  _cmpFiles = [];
}

function _cmpToggleBcc() {
  const field = document.getElementById('cmp-bcc-field');
  const btn   = document.getElementById('cmp-bcc-btn');
  if (!field) return;
  field.style.display = '';
  if (btn) btn.style.display = 'none';
  document.getElementById('cmp-bcc')?.focus();
}

function _cmpFilesAdded(input) {
  for (const f of input.files) _cmpFiles.push(f);
  input.value = '';
  _cmpRenderAttachBar();
}

function _cmpRemoveFile(idx) {
  _cmpFiles.splice(idx, 1);
  _cmpRenderAttachBar();
}

function _cmpRenderAttachBar() {
  const bar = document.getElementById('cmp-attach-bar');
  if (!bar) return;
  if (_cmpFiles.length === 0) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = '';
  bar.innerHTML = _cmpFiles.map((f, i) =>
    `<span class="cmp-att-chip">&#128206; ${esc(f.name)}<span class="cmp-att-size">${_emFmtSize(f.size)}</span><button class="cmp-att-remove" onclick="_cmpRemoveFile(${i})" title="Remove">✕</button></span>`
  ).join('');
}

async function _cmpPopulateAccounts(preferredId) {
  try {
    const accounts = await apiFetch('/api/accounts');
    const sel = document.getElementById('cmp-account');
    if (!sel) return;
    sel.innerHTML = accounts.map(a =>
      `<option value="${a.id}"${a.id === preferredId ? ' selected' : ''} data-sig="${esc(a.signature || '')}">${esc(a.name)} &lt;${esc(a.email)}&gt;</option>`
    ).join('');

    const modal = document.getElementById('cmp-modal');
    if (modal && modal._isNew) {
      const _applySignature = (opt) => {
        const sig = (opt?.dataset.sig || '').trim();
        const bodyEl = document.getElementById('cmp-body');
        if (!bodyEl) return;
        const sigPrefix = '\n\n-- \n';
        const sigStart = bodyEl.value.indexOf(sigPrefix);
        if (sig) {
          if (sigStart !== -1) {
            bodyEl.value = bodyEl.value.slice(0, sigStart) + sigPrefix + sig;
          } else if (!bodyEl.value.trim()) {
            bodyEl.value = sigPrefix + sig;
          }
        } else if (sigStart !== -1) {
          bodyEl.value = bodyEl.value.slice(0, sigStart);
        }
      };
      _applySignature(sel.options[sel.selectedIndex]);
      sel.addEventListener('change', () => _applySignature(sel.options[sel.selectedIndex]));
    }
  } catch(e) {}
}

async function _cmpSend() {
  const modal     = document.getElementById('cmp-modal');
  const btn       = document.getElementById('cmp-send-btn');
  const accountId = parseInt(document.getElementById('cmp-account')?.value || '0');
  const to        = (document.getElementById('cmp-to')?.value || '').trim();
  const cc        = (document.getElementById('cmp-cc')?.value || '').trim();
  const bcc       = (document.getElementById('cmp-bcc')?.value || '').trim();
  const subject   = (document.getElementById('cmp-subject')?.value || '').trim();
  const body      = document.getElementById('cmp-body')?.value || '';

  if (!to)        { toast('Recipient (To) is required', 'err'); return; }
  if (!subject)   { toast('Subject is required', 'err'); return; }
  if (!accountId) { toast('Select a sending account', 'err'); return; }

  btn.disabled = true;
  btn.textContent = 'Sending…';

  try {
    const fd = new FormData();
    fd.append('account_id', accountId);
    fd.append('to', to);
    fd.append('subject', subject);
    fd.append('body', body);
    if (cc)  fd.append('cc', cc);
    if (bcc) fd.append('bcc', bcc);
    if (modal._replyMsgId) fd.append('reply_to_msg_id', modal._replyMsgId);
    if (modal._references) fd.append('references', modal._references);
    for (const f of _cmpFiles) fd.append('attachments', f, f.name);

    const r = await fetch('/api/send', { method: 'POST', body: fd });
    const j = await r.json();
    if (j.ok) {
      toast('Message sent');
      _cmpClose();
    } else {
      toast(j.error || 'Send failed', 'err');
      btn.disabled = false;
      btn.textContent = 'Send →';
    }
  } catch(e) {
    toast('Send failed: ' + e.message, 'err');
    btn.disabled = false;
    btn.textContent = 'Send →';
  }
}

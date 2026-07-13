// ═══════════════════════════════════════════════════════════════════════════
// COMPOSE MODULE — new email, reply, reply-all, forward
// Prefix: _cmp
// ═══════════════════════════════════════════════════════════════════════════

function composeNew(accountId = null) {
  _cmpOpen({ title: 'New Message', subject: '', to: '', body: '', replyMsgId: null, references: null, accountId });
}

function composeReply(msg, draftBody) {
  const subject = (msg.subject || '').startsWith('Re:') ? msg.subject : `Re: ${msg.subject}`;
  const quoteDate = fmtDate(msg.date);
  const quoteName = msg.from_name || msg.from_addr || '';
  const quoteBody = (msg.body_text || '').trim().split('\n').map(l => '> ' + l).join('\n');
  const body = draftBody || `\n\n\nOn ${quoteDate}, ${quoteName} wrote:\n${quoteBody}`;
  _cmpOpen({
    title: 'Reply',
    to: msg.from_addr || '',
    subject,
    body,
    replyMsgId: msg.message_id,
    references: msg.message_id,
    accountId: msg.account_id,
  });
}

function composeReplyAll(msg) {
  const subject = (msg.subject || '').startsWith('Re:') ? msg.subject : `Re: ${msg.subject}`;
  const ownEmail = (msg.account_email || '').toLowerCase();

  const _parse = (json) => { try { return JSON.parse(json || '[]'); } catch(e) { return []; } };
  const ccList = [..._parse(msg.to_addrs), ..._parse(msg.cc_addrs)]
    .filter(a => (a.addr || '').toLowerCase() !== ownEmail)
    .map(a => a.name ? `${a.name} <${a.addr}>` : a.addr);

  const quoteDate = fmtDate(msg.date);
  const quoteName = msg.from_name || msg.from_addr || '';
  const quoteBody = (msg.body_text || '').trim().split('\n').map(l => '> ' + l).join('\n');
  const body = `\n\n\nOn ${quoteDate}, ${quoteName} wrote:\n${quoteBody}`;

  _cmpOpen({
    title: 'Reply All',
    to: msg.from_addr || '',
    cc: ccList.join(', '),
    subject,
    body,
    replyMsgId: msg.message_id,
    references: msg.message_id,
    accountId: msg.account_id,
  });
}

function composeForward(msg) {
  const subject = (msg.subject || '').startsWith('Fwd:') ? msg.subject : `Fwd: ${msg.subject}`;
  const quoteDate = fmtDate(msg.date);
  const quoteFrom = msg.from_name ? `${msg.from_name} <${msg.from_addr}>` : msg.from_addr;
  const body = `\n\n\n---------- Forwarded message ----------\nFrom: ${quoteFrom}\nDate: ${quoteDate}\nSubject: ${msg.subject}\n\n${(msg.body_text || '').trim()}`;
  _cmpOpen({
    title: 'Forward',
    to: '',
    subject,
    body,
    accountId: msg.account_id,
  });
}

function _cmpOpen(opts) {
  const existing = document.getElementById('cmp-modal');
  if (existing) existing.remove();

  const hasBcc = !!(opts.bcc);
  const bd = document.createElement('div');
  bd.className = 'modal-bd';
  bd.id = 'cmp-modal';
  bd.style.display = 'flex';

  bd.innerHTML = `<div class="modal-box cmp-box">
    <div class="modal-hdr">
      <div class="modal-title">${esc(opts.title || 'New Message')}</div>
      <button class="cmp-bcc-btn" id="cmp-bcc-btn" onclick="_cmpToggleBcc()" title="Add BCC"${hasBcc ? ' style="display:none"' : ''}>+ BCC</button>
      <button class="det-close" onclick="document.getElementById('cmp-modal').remove()">✕</button>
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
    </div>
    <div class="modal-foot">
      <button class="btn btn-outline btn-sm" onclick="document.getElementById('cmp-modal').remove()">Cancel</button>
      <button class="btn btn-primary btn-sm" id="cmp-send-btn" onclick="_cmpSend()">Send →</button>
    </div>
  </div>`;

  document.body.appendChild(bd);
  _cmpPopulateAccounts(opts.accountId);

  bd._replyMsgId = opts.replyMsgId || null;
  bd._references = opts.references || null;

  // Focus: empty To → focus To; otherwise focus body at top
  if (!opts.to) {
    document.getElementById('cmp-to')?.focus();
  } else {
    const bodyEl = document.getElementById('cmp-body');
    if (bodyEl) { bodyEl.focus(); bodyEl.setSelectionRange(0, 0); }
  }
}

function _cmpToggleBcc() {
  const field = document.getElementById('cmp-bcc-field');
  const btn   = document.getElementById('cmp-bcc-btn');
  if (!field) return;
  field.style.display = '';
  if (btn) btn.style.display = 'none';
  document.getElementById('cmp-bcc')?.focus();
}

async function _cmpPopulateAccounts(preferredId) {
  try {
    const accounts = await apiFetch('/api/accounts');
    const sel = document.getElementById('cmp-account');
    if (!sel) return;
    sel.innerHTML = accounts.map(a =>
      `<option value="${a.id}"${a.id === preferredId ? ' selected' : ''}>${esc(a.name)} &lt;${esc(a.email)}&gt;</option>`
    ).join('');
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
    const payload = {
      account_id: accountId,
      to, subject, body,
      reply_to_msg_id: modal._replyMsgId,
      references: modal._references,
    };
    if (cc)  payload.cc  = cc;
    if (bcc) payload.bcc = bcc;

    const r = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const j = await r.json();
    if (j.ok) {
      toast('Message sent');
      modal.remove();
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

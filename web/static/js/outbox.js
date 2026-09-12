// Outbox — queued and failed messages

async function pageOutbox() {
  const mc = document.getElementById('module-content');
  mc.innerHTML = '<div class="state-loading">Loading…</div>';

  let items;
  try {
    items = await apiFetch('/api/outbox');
  } catch(e) {
    mc.innerHTML = `<div class="state-empty">Failed to load outbox: ${esc(e.message)}</div>`;
    return;
  }

  if (!items.length) {
    mc.innerHTML = '<div class="state-empty">Outbox is empty — all messages sent.</div>';
    return;
  }

  const rows = items.map(it => {
    const statusCls = it.status === 'failed' ? 'obx-status-failed' : 'obx-status-pending';
    const statusLbl = it.status === 'failed' ? 'Failed' : 'Queued';
    const errHtml   = it.error ? `<div class="obx-error">${esc(it.error)}</div>` : '';
    return `<tr data-id="${it.id}">
      <td><span class="obx-status ${statusCls}">${statusLbl}</span></td>
      <td class="obx-to">${esc(it.to_addrs)}</td>
      <td class="obx-subj">${esc(it.subject || '(no subject)')}</td>
      <td class="obx-date">${esc(it.created_at || '')}</td>
      <td class="obx-attempts">${it.attempts || 0}</td>
      <td class="obx-actions">
        <button class="btn btn-sm btn-outline" onclick="_obxRetry(${it.id}, this)">Retry</button>
        <button class="btn btn-sm btn-outline obx-del-btn" onclick="_obxDelete(${it.id}, this)">Delete</button>
      </td>
    </tr>${errHtml ? `<tr class="obx-err-row"><td colspan="6">${errHtml}</td></tr>` : ''}`;
  }).join('');

  mc.innerHTML = `
    <div class="inv-toolbar">
      <div style="flex:1"></div>
      <button class="btn btn-outline btn-sm" onclick="_obxRetryAll(this)">Retry All</button>
    </div>
    <div class="inv-list-panel">
      <div class="tbl-overflow-x">
        <table class="inv-list-table obx-table">
          <thead><tr>
            <th>Status</th><th>To</th><th>Subject</th><th>Queued</th><th>Tries</th><th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
    <div class="count-pill">${items.length} message${items.length !== 1 ? 's' : ''} in outbox</div>`;
}

async function _obxRetry(id, btn) {
  btn.disabled = true;
  btn.textContent = 'Retrying…';
  try {
    const j = await fetch(`/api/outbox/${id}/retry`, { method: 'POST' });
    const d = await j.json();
    if (d.ok && d.data && d.data.sent) {
      toast('Message sent');
      if (typeof _updateOutboxBadge === 'function') _updateOutboxBadge();
      pageOutbox();
    } else {
      toast(d.data?.error || 'Still offline — message remains queued', 'err');
      btn.disabled = false;
      btn.textContent = 'Retry';
    }
  } catch(e) {
    toast('Retry failed: ' + e.message, 'err');
    btn.disabled = false;
    btn.textContent = 'Retry';
  }
}

async function _obxDelete(id, btn) {
  btn.disabled = true;
  try {
    await fetch(`/api/outbox/${id}`, { method: 'DELETE' });
    if (typeof _updateOutboxBadge === 'function') _updateOutboxBadge();
    pageOutbox();
  } catch(e) {
    toast('Delete failed: ' + e.message, 'err');
    btn.disabled = false;
  }
}

async function _obxRetryAll(btn) {
  btn.disabled = true;
  btn.textContent = 'Retrying…';
  try {
    const items = await apiFetch('/api/outbox');
    let sent = 0;
    for (const it of items) {
      const j = await fetch(`/api/outbox/${it.id}/retry`, { method: 'POST' });
      const d = await j.json();
      if (d.ok && d.data && d.data.sent) sent++;
    }
    if (sent) toast(`${sent} message${sent !== 1 ? 's' : ''} sent`);
    else toast('Still offline — messages remain queued');
    if (typeof _updateOutboxBadge === 'function') _updateOutboxBadge();
    pageOutbox();
  } catch(e) {
    toast('Retry all failed: ' + e.message, 'err');
  }
  btn.disabled = false;
  btn.textContent = 'Retry All';
}

function showToast(message, undoUrl, itemId) {
  const toast = document.getElementById('toast');
  const msg = document.getElementById('toast-msg');
  const btn = document.getElementById('toast-undo');
  const countdown = document.getElementById('toast-count');
  let remaining = 5;
  msg.textContent = message;
  toast.classList.add('show');
  countdown.textContent = remaining;
  const timer = setInterval(() => {
    remaining -= 1;
    countdown.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(timer);
      toast.classList.remove('show');
    }
  }, 1000);

  btn.onclick = () => {
    clearInterval(timer);
    const form = document.getElementById('filters');
    const params = form ? new URLSearchParams(new FormData(form)).toString() : '';
    const url = params ? `${undoUrl}?${params}` : undoUrl;
    fetch(url, { method: 'POST' }).then(() => {
      toast.classList.remove('show');
      htmx.trigger(document.body, 'batch-counts-changed');
      if (itemId) { refreshItem(itemId); }
      htmx.trigger(document.body, 'refresh-items');
    });
  };
}

function toggleContrast() {
  document.body.classList.toggle('high-contrast');
}

function markMissing(itemId) {
  const note = prompt('Missing note (optional):', '');
  if (note === null) {
    // User canceled; do not mark missing.
    return;
  }
  const body = new URLSearchParams();
  body.set('note', note);
  const form = document.getElementById('filters');
  const params = form ? new URLSearchParams(new FormData(form)).toString() : '';
  const url = params ? `/items/${itemId}/missing?${params}` : `/items/${itemId}/missing`;
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  }).then(() => {
    htmx.trigger(document.body, 'batch-counts-changed');
    if (itemId) { refreshItem(itemId); }
    htmx.trigger(document.body, 'refresh-items');
  });
}

function toggleImageSize(imgId) {
  const img = document.getElementById(imgId);
  if (!img) return;
  const size = img.dataset.size === 'normal' ? 'large' : 'normal';
  img.dataset.size = size;
  img.src = img.dataset.base + '?size=' + size;
}

function ensureCardModalTarget() {
  let container = document.getElementById('card-modal');
  if (!container) {
    container = document.createElement('div');
    container.id = 'card-modal';
    document.body.appendChild(container);
  }
  return container;
}

function closeCardModal() {
  const container = document.getElementById('card-modal');
  if (container) {
    container.innerHTML = '';
  }
}

document.addEventListener('keydown', (evt) => {
  if (evt.key === 'Escape') {
    closeCardModal();
  }
});

let lastCardItemId = null;
let cardModalRetryInFlight = false;

function openCard(itemId) {
  lastCardItemId = itemId;
  cardModalRetryInFlight = false;
  const container = ensureCardModalTarget();
  container.innerHTML = '';
  htmx.ajax('GET', `/card/modal?item_id=${itemId}`, { target: container, swap: 'innerHTML' });
}

function getUserName() {
  const input = document.getElementById('user-name');
  if (!input) return 'anonymous';
  return input.value.trim() || 'anonymous';
}

function initUserName() {
  const input = document.getElementById('user-name');
  if (!input) return;
  const saved = localStorage.getItem('picker_name');
  input.value = saved || 'anonymous';
  input.addEventListener('input', () => {
    const val = input.value.trim() || 'anonymous';
    localStorage.setItem('picker_name', val);
  });
}

function reserveSet(setCode) {
  const items = document.getElementById('items');
  if (!items) return;
  const batchId = items.dataset.batchId;
  const body = new URLSearchParams();
  body.set('set_code', setCode);
  body.set('reserved_by', getUserName());
  fetch(`/batch/${batchId}/reserve-set`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
}

function applyReservation(setCode, reservedBy) {
  document.querySelectorAll(`.set-group[data-set-code="${setCode}"]`).forEach((group) => {
    const actions = group.querySelector('.set-actions');
    if (!actions) return;
    const existing = actions.querySelector('.reserve-badge');
    if (existing) existing.remove();
    if (reservedBy) {
      const badge = document.createElement('span');
      badge.className = 'reserve-badge';
      badge.textContent = `Reserved by ${reservedBy}`;
      actions.prepend(badge);
    }
  });
}

function toggleSetGroup(setCode) {
  const group = document.querySelector(`.set-group[data-set-code="${setCode}"]`);
  if (!group) return;
  group.classList.toggle('collapsed');
  const key = `set_collapsed_${setCode || 'unknown'}`;
  localStorage.setItem(key, group.classList.contains('collapsed') ? '1' : '0');
}

function applySetCollapseState(root = document) {
  root.querySelectorAll('.set-group').forEach((group) => {
    const setCode = group.dataset.setCode || 'unknown';
    const key = `set_collapsed_${setCode}`;
    if (localStorage.getItem(key) === '1') {
      group.classList.add('collapsed');
    } else {
      group.classList.remove('collapsed');
    }
  });
}

function refreshItem(itemId) {
  const items = document.getElementById('items');
  const form = document.getElementById('filters');
  const params = form ? new URLSearchParams(new FormData(form)).toString() : '';
  const url = `/items/${itemId}/row${params ? `?${params}` : ''}`;
  fetch(url).then(async (resp) => {
    // Re-read the row after the response to avoid races with concurrent updates.
    let row = document.getElementById(`item-${itemId}`);
    if (resp.status === 204) {
      if (row && row.parentNode) row.remove();
      return;
    }
    const html = (await resp.text()).trim();
    if (!html) return;
    row = document.getElementById(`item-${itemId}`);
    if (row && row.parentNode) {
      row.outerHTML = html;
      const updated = document.getElementById(`item-${itemId}`);
      if (updated) {
        htmx.process(updated);
      }
    } else if (items && !document.getElementById(`item-${itemId}`)) {
      // If the row is missing, refresh the full list to preserve sort order.
      htmx.trigger(document.body, 'refresh-items');
    }
  });
}

function initRealtime() {
  const items = document.getElementById('items');
  if (!items) return;
  const batchId = items.dataset.batchId;
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  let retryMs = 1000;

  const connect = () => {
    const ws = new WebSocket(`${wsProto}://${location.host}/ws/batch/${batchId}`);
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'item_update') {
          refreshItem(msg.item_id);
        } else if (msg.type === 'set_reserved') {
          applyReservation(msg.set_code, msg.reserved_by);
        }
      } catch (e) {
        // ignore
      }
    };
    ws.onopen = () => {
      retryMs = 1000;
    };
    ws.onerror = () => {
      ws.close();
    };
    ws.onclose = () => {
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 10000);
    };
  };

  connect();
}

function generateManaPoolPicklist() {
  const btn = document.getElementById('mp-generate-btn');
  const status = document.getElementById('mp-status');
  const spinner = document.getElementById('mp-spinner');
  const details = document.getElementById('mp-details');
  if (!btn || !status || !spinner || !details) return;
  btn.disabled = true;
  spinner.style.display = 'inline-block';
  status.textContent = 'Generating from ManaPool...';
  details.innerHTML = '';

  fetch('/api/batches/generate-from-manapool', { method: 'POST' })
    .then(async (resp) => {
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'ManaPool generation failed');
      }
      return data;
    })
    .then((data) => {
      const parts = [];
      parts.push(`Orders scanned: ${data.orders_scanned}`);
      parts.push(`Line items: ${data.line_items}`);
      parts.push(`Unique cards: ${data.unique_cards}`);
      if (data.recent_warning) parts.push(`Warning: ${data.recent_warning}`);
      status.textContent = parts.join(' | ');
      if (data.batch_id) {
        status.innerHTML = `${parts.join(' | ')} <a href="/batch/${data.batch_id}">Open batch</a>`;
      }
      const errs = data.errors || [];
      const warns = data.warnings || [];
      if (warns.length) {
        details.innerHTML += `<div class="badge">Warnings</div><div>${warns.map(w => `<div>${w}</div>`).join('')}</div>`;
      }
      if (errs.length) {
        details.innerHTML += `<div class="badge">Errors</div><div>${errs.map(e => `<div>${e}</div>`).join('')}</div>`;
      }
    })
    .catch((err) => {
      status.textContent = `Error: ${err.message}`;
    })
    .finally(() => {
      spinner.style.display = 'none';
      btn.disabled = false;
    });
}

let lastScrollY = window.scrollY;
window.addEventListener('scroll', () => {
  const header = document.querySelector('.header');
  if (!header) return;
  const current = window.scrollY;
  if (current > 40 && current > lastScrollY) {
    header.classList.add('header-compact');
  } else {
    header.classList.remove('header-compact');
  }
  lastScrollY = current;
});

htmx.on('batch-counts-changed', () => {
  const el = document.getElementById('batch-counts');
  if (!el) return;
  fetch(el.dataset.url)
    .then((resp) => resp.text())
    .then((html) => {
      const current = document.getElementById('batch-counts');
      if (!current) return;
      current.innerHTML = html;
    });
});

htmx.on('refresh-items', () => {
  const el = document.getElementById('items');
  if (!el) return;
  const form = document.getElementById('filters');
  const params = form ? new URLSearchParams(new FormData(form)).toString() : '';
  const url = params ? `${el.dataset.url}?${params}` : el.dataset.url;
  fetch(url)
    .then((resp) => resp.text())
    .then((html) => {
      const current = document.getElementById('items');
      if (!current) return;
      current.innerHTML = html;
      htmx.process(current);
      applySetCollapseState(current);
    });
});

document.body.addEventListener('htmx:swapError', (evt) => {
  const detail = evt.detail || {};
  const target = detail.target;
  const xhr = detail.xhr;
  const responseUrl = (xhr && xhr.responseURL) || '';
  const targetId = target && target.id;

  const targetMissing = !target || !target.isConnected || (targetId === 'card-modal' && !document.getElementById('card-modal'));
  const isCardModal = responseUrl.includes('/card/modal');
  if (targetMissing && isCardModal && lastCardItemId && !cardModalRetryInFlight) {
    cardModalRetryInFlight = true;
    ensureCardModalTarget().innerHTML = '';
    setTimeout(() => openCard(lastCardItemId), 0);
    return;
  }

  // If the items target was detached mid-swap, refresh the list to recover.
  if (targetMissing && (targetId === 'items' || responseUrl.includes('/batch/'))) {
    htmx.trigger(document.body, 'refresh-items');
    return;
  }

  if (targetId === 'card-modal') {
    ensureCardModalTarget().innerHTML = '';
  }
});

document.addEventListener('DOMContentLoaded', () => {
  initUserName();
  initRealtime();
  applySetCollapseState();
});






















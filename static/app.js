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
let assistedMode = null;
let assistedCurrentItemId = null;
let assistedSkippedItemIds = new Set();

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

function pruneEmptySetGroups(root = document) {
  root.querySelectorAll('.set-group').forEach((group) => {
    const items = group.querySelectorAll('.picklist-row');
    if (!items.length) {
      group.remove();
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
      pruneEmptySetGroups(document);
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
      pruneEmptySetGroups(document);
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

function assistedModeLabel(mode) {
  if (mode === 'bottom_up') return 'Bottom up';
  if (mode === 'middle_out') return 'Middle out';
  return 'Top down';
}

function renderAssistedSnapshot(data) {
  const layout = document.getElementById('assisted-layout');
  const done = document.getElementById('assisted-done');
  if (!layout || !done) return;

  if (data.done) {
    assistedCurrentItemId = null;
    layout.style.display = 'none';
    done.style.display = 'block';
    return;
  }

  done.style.display = 'none';
  layout.style.display = 'grid';
  assistedCurrentItemId = data.item.id;

  const modeLabel = document.getElementById('assisted-mode-label');
  const progress = document.getElementById('assisted-progress');
  const name = document.getElementById('assisted-card-name');
  const subtitle = document.getElementById('assisted-card-subtitle');
  const number = document.getElementById('assisted-card-number');
  const setCode = document.getElementById('assisted-set-code');
  const finish = document.getElementById('assisted-finish');
  const qty = document.getElementById('assisted-qty');
  const image = document.getElementById('assisted-card-image');
  const noImage = document.getElementById('assisted-no-image');
  const pickAll = document.getElementById('assisted-pick-all-btn');

  modeLabel.textContent = `Mode: ${assistedModeLabel(data.mode)}`;
  progress.textContent = `${data.remaining_cards} cards left | ${data.remaining_copies} copies left`;
  name.textContent = data.item.card_name || '';

  const parts = [];
  if (data.item.condition) parts.push(data.item.condition);
  if (data.item.language) parts.push(data.item.language);
  subtitle.textContent = parts.join(' | ');
  subtitle.style.display = subtitle.textContent ? 'block' : 'none';
  number.textContent = data.item.collector_number || 'Unknown';
  setCode.textContent = data.item.set_code || 'Unknown';
  finish.textContent = data.item.printing || 'Normal';

  qty.textContent = `Remaining ${data.item.qty_remaining} of ${data.item.qty_required}`;
  pickAll.style.display = data.item.qty_remaining > 1 ? 'block' : 'none';

  if (data.item.image_url) {
    image.onerror = () => {
      image.style.display = 'none';
      noImage.style.display = 'block';
    };
    image.src = data.item.image_url;
    image.style.display = 'block';
    noImage.style.display = 'none';
  } else {
    image.removeAttribute('src');
    image.style.display = 'none';
    noImage.style.display = 'block';
  }
}

function loadAssistedNext() {
  const root = document.getElementById('assisted-pick-root');
  if (!root || !assistedMode) return;
  const excluded = Array.from(assistedSkippedItemIds).join(',');
  const url = `${root.dataset.nextUrl}?mode=${encodeURIComponent(assistedMode)}&exclude_item_ids=${encodeURIComponent(excluded)}`;
  fetch(url)
    .then((resp) => resp.json())
    .then((data) => renderAssistedSnapshot(data));
}

function selectAssistedMode(mode) {
  assistedMode = mode;
  assistedSkippedItemIds = new Set();
  const chooser = document.getElementById('assisted-mode-chooser');
  if (chooser) chooser.style.display = 'none';
  loadAssistedNext();
}

function assistedSetButtonsDisabled(disabled) {
  ['assisted-picked-btn', 'assisted-pick-all-btn', 'assisted-skip-btn', 'assisted-missing-btn'].forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = disabled;
  });
}

function assistedPerformAction(action) {
  const root = document.getElementById('assisted-pick-root');
  if (!root || !assistedCurrentItemId || !assistedMode) return;
  const body = new URLSearchParams();
  body.set('item_id', String(assistedCurrentItemId));
  body.set('action', action);
  body.set('mode', assistedMode);
  if (action === 'skip') {
    assistedSkippedItemIds.add(assistedCurrentItemId);
  } else {
    assistedSkippedItemIds.delete(assistedCurrentItemId);
  }
  body.set('exclude_item_ids', Array.from(assistedSkippedItemIds).join(','));
  assistedSetButtonsDisabled(true);
  fetch(root.dataset.actionUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  })
    .then((resp) => {
      if (!resp.ok) {
        throw new Error(`Assisted action failed (${resp.status})`);
      }
      return resp.json();
    })
    .then((data) => renderAssistedSnapshot(data))
    .catch(() => loadAssistedNext())
    .finally(() => assistedSetButtonsDisabled(false));
}

function initAssistedPick() {
  const root = document.getElementById('assisted-pick-root');
  if (!root) return;
  const chooser = document.getElementById('assisted-mode-chooser');
  if (chooser) chooser.style.display = 'block';
}

let scrollTicking = false;
window.addEventListener('scroll', () => {
  if (scrollTicking) return;
  scrollTicking = true;
  requestAnimationFrame(() => {
    const header = document.querySelector('.header');
    if (!header) {
      scrollTicking = false;
      return;
    }
    const current = window.scrollY;
    if (current > 80) {
      header.classList.add('header-compact');
    } else {
      header.classList.remove('header-compact');
    }
    scrollTicking = false;
  });
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
      pruneEmptySetGroups(current);
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
  initAssistedPick();
});






















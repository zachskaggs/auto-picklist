/* ── Toast Notifications ──────────────────────────────── */
function showToast(message, undoUrl, itemId) {
  const toast = document.getElementById('toast');
  const msg = document.getElementById('toast-msg');
  const btn = document.getElementById('toast-undo');
  const countdown = document.getElementById('toast-count');
  let remaining = 5;
  msg.textContent = message;
  toast.classList.remove('hiding');
  toast.classList.add('show');
  countdown.textContent = remaining;
  const timer = setInterval(() => {
    remaining -= 1;
    countdown.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(timer);
      hideToast();
    }
  }, 1000);

  btn.onclick = () => {
    clearInterval(timer);
    const form = document.getElementById('filters');
    const params = form ? new URLSearchParams(new FormData(form)).toString() : '';
    const url = params ? `${undoUrl}?${params}` : undoUrl;
    const undoBody = new URLSearchParams();
    undoBody.set('picker_name', getUserName());
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: undoBody.toString() }).then(() => {
      hideToast();
      htmx.trigger(document.body, 'batch-counts-changed');
      if (itemId) { refreshItem(itemId); }
      htmx.trigger(document.body, 'refresh-items');
    });
  };
}

function hideToast() {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.classList.add('hiding');
  toast.addEventListener('animationend', () => {
    toast.classList.remove('show', 'hiding');
  }, { once: true });
}

/* ── High Contrast ────────────────────────────────────── */
function toggleContrast() {
  document.body.classList.toggle('high-contrast');
}

/* ── Mark Missing Modal ───────────────────────────────── */
function markMissing(itemId) {
  const overlay = document.getElementById('missing-modal-overlay');
  const input = document.getElementById('missing-note-input');
  const confirmBtn = document.getElementById('missing-confirm-btn');
  const cancelBtn = document.getElementById('missing-cancel-btn');

  if (!overlay || !input || !confirmBtn || !cancelBtn) {
    // Fallback to prompt if modal not in DOM
    const note = prompt('Missing note (optional):', '');
    if (note === null) return;
    submitMissing(itemId, note);
    return;
  }

  input.value = '';
  overlay.style.display = 'flex';
  input.focus();

  const cleanup = () => {
    overlay.style.display = 'none';
    confirmBtn.onclick = null;
    cancelBtn.onclick = null;
    overlay.onclick = null;
    input.onkeydown = null;
  };

  confirmBtn.onclick = () => {
    cleanup();
    submitMissing(itemId, input.value);
  };

  cancelBtn.onclick = () => {
    cleanup();
  };

  overlay.onclick = (e) => {
    if (e.target === overlay) cleanup();
  };

  input.onkeydown = (e) => {
    if (e.key === 'Enter') {
      cleanup();
      submitMissing(itemId, input.value);
    } else if (e.key === 'Escape') {
      cleanup();
    }
  };
}

function submitMissing(itemId, note) {
  const body = new URLSearchParams();
  body.set('note', note || '');
  body.set('picker_name', getUserName());
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

/* ── Image Operations ─────────────────────────────────── */
function toggleImageSize(imgId) {
  const img = document.getElementById(imgId);
  if (!img) return;
  const size = img.dataset.size === 'normal' ? 'large' : 'normal';
  img.dataset.size = size;
  img.src = img.dataset.base + '?size=' + size;
}

/* ── Card Modal ───────────────────────────────────────── */
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
    // Also close missing modal
    const missingOverlay = document.getElementById('missing-modal-overlay');
    if (missingOverlay) missingOverlay.style.display = 'none';
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

/* ── Picker Name ──────────────────────────────────────── */
function getUserName() {
  const input = document.getElementById('user-name');
  if (!input) return 'anonymous';
  return input.value.trim() || 'anonymous';
}

function syncUserName() {
  const name = getUserName();
  const body = new URLSearchParams();
  body.set('name', name);
  fetch('/api/session/name', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  }).catch(() => {});
}

function initUserName() {
  const input = document.getElementById('user-name');
  if (!input) return;
  const saved = localStorage.getItem('picker_name');
  input.value = saved || 'anonymous';
  syncUserName();
  input.addEventListener('input', () => {
    const val = input.value.trim() || 'anonymous';
    localStorage.setItem('picker_name', val);
    syncPickerNameHidden();
  });
}

function syncPickerNameHidden() {
  const hidden = document.getElementById('picker-name-hidden');
  if (hidden) {
    hidden.value = getUserName();
  }
}

/* ── Set Management ───────────────────────────────────── */
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
  // Update aria-expanded
  const btn = group.querySelector('.collapse-btn');
  if (btn) {
    btn.setAttribute('aria-expanded', !group.classList.contains('collapsed'));
  }
  const key = `set_collapsed_${setCode || 'unknown'}`;
  localStorage.setItem(key, group.classList.contains('collapsed') ? '1' : '0');
}

function applySetCollapseState(root = document) {
  root.querySelectorAll('.set-group').forEach((group) => {
    const setCode = group.dataset.setCode || 'unknown';
    const key = `set_collapsed_${setCode}`;
    const collapsed = localStorage.getItem(key) === '1';
    if (collapsed) {
      group.classList.add('collapsed');
    } else {
      group.classList.remove('collapsed');
    }
    // Set aria-expanded on collapse buttons
    const btn = group.querySelector('.collapse-btn');
    if (btn) {
      btn.setAttribute('aria-expanded', !collapsed);
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

/* ── Item Refresh ─────────────────────────────────────── */
function refreshItem(itemId) {
  const items = document.getElementById('items');
  const form = document.getElementById('filters');
  const params = form ? new URLSearchParams(new FormData(form)).toString() : '';
  const url = `/items/${itemId}/row${params ? `?${params}` : ''}`;
  fetch(url).then(async (resp) => {
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
        // Flash green on pick
        updated.classList.add('just-picked');
        setTimeout(() => updated.classList.remove('just-picked'), 800);
      }
      pruneEmptySetGroups(document);
    } else if (items && !document.getElementById(`item-${itemId}`)) {
      htmx.trigger(document.body, 'refresh-items');
    }
  });
}

/* ── Realtime WebSocket ───────────────────────────────── */
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

/* ── ManaPool ─────────────────────────────────────────── */
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
      parts.push(`Total cards: ${data.total_cards ?? data.line_items}`);
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

/* ── Assisted Pick ────────────────────────────────────── */
function assistedModeLabel(mode) {
  if (mode === 'bottom_up') return 'Bottom up';
  if (mode === 'middle_out') return 'Middle out';
  return 'Top down';
}

const _ENGLISH_LANGS = new Set(['en', 'english']);

function _isNonEnglish(lang) {
  return lang && !_ENGLISH_LANGS.has(lang.toLowerCase());
}

function _loadAssistedImage(img, url, noImage, attempt) {
  attempt = attempt || 0;
  img.onerror = () => {
    img.onerror = null;
    if (attempt < 2) {
      setTimeout(() => _loadAssistedImage(img, url, noImage, attempt + 1), Math.pow(2, attempt) * 600);
    } else {
      img.style.display = 'none';
      noImage.textContent = 'Image failed — tap to retry';
      noImage.style.cursor = 'pointer';
      noImage.onclick = () => {
        noImage.onclick = null;
        noImage.textContent = 'Retrying…';
        noImage.style.cursor = '';
        _loadAssistedImage(img, url, noImage, 0);
      };
      noImage.style.display = 'block';
    }
  };
  const sep = url.includes('?') ? '&' : '?';
  img.src = attempt > 0 ? `${url}${sep}t=${Date.now()}` : url;
  img.style.display = 'block';
  noImage.style.display = 'none';
}

function renderAssistedSnapshot(data) {
  const layout = document.getElementById('assisted-layout');
  const done = document.getElementById('assisted-done');
  if (!layout || !done) return;

  if (data.done) {
    assistedCurrentItemId = null;
    layout.classList.remove('assisted-high-value');
    layout.style.display = 'none';
    done.style.display = 'block';
    const nextSection = document.getElementById('assisted-next-preview');
    if (nextSection) nextSection.style.display = 'none';
    return;
  }

  done.style.display = 'none';
  layout.style.display = 'grid';
  assistedCurrentItemId = data.item.id;

  // Card swap animation
  const detailPane = document.querySelector('.assisted-detail-pane');
  if (detailPane) {
    detailPane.classList.remove('assisted-card-enter');
    void detailPane.offsetWidth; // force reflow
    detailPane.classList.add('assisted-card-enter');
    detailPane.addEventListener('animationend', () => {
      detailPane.classList.remove('assisted-card-enter');
    }, { once: true });
  }

  const modeLabel = document.getElementById('assisted-mode-label');
  const progress = document.getElementById('assisted-progress');
  const name = document.getElementById('assisted-card-name');
  const subtitle = document.getElementById('assisted-card-subtitle');
  const number = document.getElementById('assisted-card-number');
  const setCode = document.getElementById('assisted-set-code');
  const finish = document.getElementById('assisted-finish');
  const price = document.getElementById('assisted-price');
  const qty = document.getElementById('assisted-qty');
  const image = document.getElementById('assisted-card-image');
  const noImage = document.getElementById('assisted-no-image');
  const pickAll = document.getElementById('assisted-pick-all-btn');
  const langAlert = document.getElementById('assisted-lang-alert');

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
  if (typeof data.item.purchase_price === 'number') {
    price.textContent = `Purchase $${data.item.purchase_price.toFixed(2)}`;
    price.style.display = 'block';
  } else {
    price.textContent = '';
    price.style.display = 'none';
  }

  qty.textContent = `Remaining ${data.item.qty_remaining} of ${data.item.qty_required}`;
  qty.classList.toggle('assisted-qty-multi', data.item.qty_required > 1);
  const showPickAll = data.item.qty_remaining > 1;
  pickAll.style.visibility = showPickAll ? 'visible' : 'hidden';
  pickAll.disabled = !showPickAll;
  layout.classList.toggle('assisted-high-value', typeof data.item.purchase_price === 'number' && data.item.purchase_price > 5);

  // Non-English alert banner
  if (langAlert) {
    if (_isNonEnglish(data.item.language)) {
      langAlert.textContent = `\u26A0 Non-English: ${data.item.language}`;
      langAlert.style.display = 'block';
      layout.classList.add('assisted-lang-border');
    } else {
      langAlert.style.display = 'none';
      layout.classList.remove('assisted-lang-border');
    }
  }

  // Image loading with retry
  if (data.item.image_url) {
    _loadAssistedImage(image, data.item.image_url, noImage, 0);
  } else {
    image.removeAttribute('src');
    image.style.display = 'none';
    noImage.textContent = 'No image available';
    noImage.style.cursor = '';
    noImage.onclick = null;
    noImage.style.display = 'block';
  }

  // Coming Next preview (visibility-based to prevent layout shift)
  const nextSection = document.getElementById('assisted-next-preview');
  if (nextSection) {
    if (data.next_item) {
      const nextName = document.getElementById('assisted-next-name');
      const nextSet = document.getElementById('assisted-next-set');
      const nextImg = document.getElementById('assisted-next-image');
      const nextNoImg = document.getElementById('assisted-next-no-image');
      nextName.textContent = data.next_item.card_name || '';
      nextSet.textContent = [data.next_item.set_code, data.next_item.collector_number].filter(Boolean).join(' #');
      if (data.next_item.image_url) {
        nextImg.onerror = () => { nextImg.style.display = 'none'; nextNoImg.style.display = 'block'; };
        nextImg.src = data.next_item.image_url;
        nextImg.style.display = 'block';
        nextNoImg.style.display = 'none';
      } else {
        nextImg.removeAttribute('src');
        nextImg.style.display = 'none';
        nextNoImg.style.display = 'block';
      }
      // Preload next image
      if (data.next_item.image_url) {
        const preload = new Image();
        preload.src = data.next_item.image_url;
      }
      nextSection.style.visibility = 'visible';
    } else {
      nextSection.style.visibility = 'hidden';
    }
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
  body.set('picker_name', getUserName());
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

/* ── Scoreboard ───────────────────────────────────────── */
function loadScoreboard() {
  const el = document.getElementById('scoreboard-body');
  if (!el) return;
  const items = document.getElementById('items');
  const root = document.getElementById('assisted-pick-root');
  const batchId = items ? items.dataset.batchId : (root ? root.dataset.batchId : null);
  if (!batchId) return;
  fetch(`/api/batch/${batchId}/scoreboard`)
    .then((resp) => resp.json())
    .then((data) => {
      const body = document.getElementById('scoreboard-body');
      if (!body) return;
      if (!data.length) {
        body.innerHTML = '<div class="scoreboard-empty">No picks yet</div>';
        return;
      }
      body.innerHTML = data
        .map((p, i) => {
          const rank = i + 1;
          return `<div class="scoreboard-entry"><span class="scoreboard-rank">#${rank}</span> <span class="scoreboard-name">${p.picker_name}</span> <span class="scoreboard-score">${p.picks} picks</span></div>`;
        })
        .join('');
    })
    .catch(() => {});
}

/* ── Assisted Pick Init ───────────────────────────────── */
function initAssistedPick() {
  const root = document.getElementById('assisted-pick-root');
  if (!root) return;
  const chooser = document.getElementById('assisted-mode-chooser');
  if (chooser) chooser.style.display = 'block';
  loadScoreboard();
  setInterval(loadScoreboard, 15000);
}

/* ── Scroll Header Hide ──────────────────────────────── */
let scrollTicking = false;
let lastScrollY = 0;
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
    if (current > 60 && current > lastScrollY) {
      header.classList.add('header-hidden');
    } else {
      header.classList.remove('header-hidden');
    }
    lastScrollY = current;
    scrollTicking = false;
  });
});

/* ── HTMX Progress Bar ───────────────────────────────── */
let htmxActiveRequests = 0;

function showHtmxProgress() {
  let bar = document.getElementById('htmx-progress');
  if (!bar) return;
  bar.style.width = '0%';
  bar.style.display = 'block';
  // Animate to 70% quickly
  requestAnimationFrame(() => {
    bar.style.width = '70%';
  });
}

function hideHtmxProgress() {
  let bar = document.getElementById('htmx-progress');
  if (!bar) return;
  bar.style.width = '100%';
  setTimeout(() => {
    bar.style.display = 'none';
    bar.style.width = '0%';
  }, 300);
}

document.body.addEventListener('htmx:beforeRequest', () => {
  htmxActiveRequests++;
  if (htmxActiveRequests === 1) showHtmxProgress();
});

document.body.addEventListener('htmx:afterRequest', () => {
  htmxActiveRequests = Math.max(0, htmxActiveRequests - 1);
  if (htmxActiveRequests === 0) hideHtmxProgress();
});

/* ── HTMX Events ─────────────────────────────────────── */
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
  loadScoreboard();
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

/* ── HTMX Swap Error Recovery ─────────────────────────── */
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

  if (targetMissing && (targetId === 'items' || responseUrl.includes('/batch/'))) {
    htmx.trigger(document.body, 'refresh-items');
    return;
  }

  if (targetId === 'card-modal') {
    ensureCardModalTarget().innerHTML = '';
  }
});

/* ── Init ─────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initUserName();
  syncPickerNameHidden();
  initRealtime();
  applySetCollapseState();
  initAssistedPick();
  loadScoreboard();
});

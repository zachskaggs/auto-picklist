import os
import csv
import json
import uuid
from io import StringIO
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_302_FOUND, HTTP_204_NO_CONTENT

from .db import init_db, get_conn
from .logic import sort_items, remaining_qty
from . import manapool, scryfall

APP_HOST = os.getenv('APP_HOST', '0.0.0.0')
APP_PORT = int(os.getenv('APP_PORT', '8000'))
SESSION_SECRET = os.getenv('SESSION_SECRET', 'change-me')
SETTINGS_PIN = os.getenv('SETTINGS_PIN', '1234')
BASIC_AUTH_USER = os.getenv('BASIC_AUTH_USER')
BASIC_AUTH_PASS = os.getenv('BASIC_AUTH_PASS')

MANAPOOL_RECENT_MINUTES = int(os.getenv('MANAPOOL_RECENT_MINUTES', '10'))
MANAPOOL_MAX_WORKERS = int(os.getenv('MANAPOOL_MAX_WORKERS', '4'))

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / 'templates'))

app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')


class ConnectionManager:
    def __init__(self):
        self._connections = {}

    async def connect(self, batch_id: int, websocket: WebSocket):
        await websocket.accept()
        self._connections.setdefault(batch_id, set()).add(websocket)

    def disconnect(self, batch_id: int, websocket: WebSocket):
        if batch_id in self._connections:
            self._connections[batch_id].discard(websocket)
            if not self._connections[batch_id]:
                self._connections.pop(batch_id, None)

    async def broadcast(self, batch_id: int, payload: dict):
        sockets = list(self._connections.get(batch_id, []))
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(batch_id, ws)


manager = ConnectionManager()


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _parse_ts(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def _basic_auth(request: Request):
    if not BASIC_AUTH_USER or not BASIC_AUTH_PASS:
        return True
    auth = request.headers.get('Authorization')
    if not auth or not auth.lower().startswith('basic '):
        return False
    import base64
    try:
        userpass = base64.b64decode(auth.split(' ', 1)[1]).decode('utf-8')
        user, pwd = userpass.split(':', 1)
        return user == BASIC_AUTH_USER and pwd == BASIC_AUTH_PASS
    except Exception:
        return False


def require_auth(request: Request):
    if not _basic_auth(request):
        raise HTTPException(status_code=401, detail='Unauthorized')
    return True


def _create_sync_log():
    with get_conn() as conn:
        conn.execute('INSERT INTO manapool_sync_log (started_at, status) VALUES (?, ?)', (_utc_now(), 'running'))
        log_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
        conn.commit()
    return log_id


def _finish_sync_log(log_id, status, summary=None, error=None):
    with get_conn() as conn:
        conn.execute(
            'UPDATE manapool_sync_log SET finished_at = ?, status = ?, summary_json = ?, error_text = ? WHERE id = ?',
            (_utc_now(), status, json.dumps(summary) if summary else None, error, log_id),
        )
        conn.commit()


def _latest_manapool_batch_warning():
    with get_conn() as conn:
        row = conn.execute("SELECT created_at FROM batches WHERE source = 'manapool' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    ts = _parse_ts(row['created_at'])
    if not ts:
        return None
    if datetime.utcnow() - ts < timedelta(minutes=MANAPOOL_RECENT_MINUTES):
        return f"A ManaPool batch was generated at {row['created_at']} (within {MANAPOOL_RECENT_MINUTES} minutes)."
    return None


def _map_finish(finish_id):
    return {
        'NF': 'Normal',
        'FO': 'Foil',
        'EF': 'Etched',
    }.get(finish_id)


def _map_condition(cond_id):
    return {
        'NM': 'NM',
        'LP': 'LP',
        'MP': 'MP',
        'HP': 'HP',
        'DMG': 'DMG',
    }.get(cond_id)


@app.on_event('startup')
def on_startup():
    init_db()


@app.websocket('/ws/batch/{batch_id}')
async def ws_batch(websocket: WebSocket, batch_id: int):
    await manager.connect(batch_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(batch_id, websocket)


@app.get('/', response_class=HTMLResponse)
def batches(request: Request, auth=Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.*, 
              (SELECT COUNT(*) FROM batch_items bi WHERE bi.batch_id = b.id AND bi.qty_picked < bi.qty_required) AS remaining_count
            FROM batches b
            WHERE b.status = 'open'
            ORDER BY b.created_at DESC
            """
        ).fetchall()
        last_log = conn.execute('SELECT * FROM manapool_sync_log ORDER BY started_at DESC LIMIT 1').fetchone()
    last_log_data = None
    if last_log:
        last_log_data = dict(last_log)
        if last_log_data.get('summary_json'):
            try:
                last_log_data['summary'] = json.loads(last_log_data['summary_json'])
            except Exception:
                last_log_data['summary'] = None
    return TEMPLATES.TemplateResponse('batches.html', {'request': request, 'batches': rows, 'last_log': last_log_data})


@app.post('/api/batches/generate-from-manapool')
def generate_from_manapool(request: Request, auth=Depends(require_auth)):
    log_id = _create_sync_log()
    if not manapool.is_configured():
        _finish_sync_log(log_id, 'error', error='ManaPool not configured')
        raise HTTPException(status_code=400, detail='ManaPool not configured')

    warning = _latest_manapool_batch_warning()
    orders, err = manapool.list_unfulfilled_orders()
    if err:
        _finish_sync_log(log_id, 'error', error=err)
        raise HTTPException(status_code=502, detail=err)

    order_ids = [o.get('id') for o in orders if o.get('id')]
    errors = []
    warnings = []
    raw_items = []
    line_items_total = 0

    def _fetch(order_id):
        data, fetch_err = manapool.fetch_order(order_id)
        return order_id, data, fetch_err

    with ThreadPoolExecutor(max_workers=MANAPOOL_MAX_WORKERS) as executor:
        futures = [executor.submit(_fetch, oid) for oid in order_ids]
        for fut in as_completed(futures):
            order_id, data, fetch_err = fut.result()
            if fetch_err:
                errors.append(f"Order {order_id}: {fetch_err}")
                continue
            order = (data or {}).get('order') or {}
            items = order.get('items') or []
            ship_name = (order.get('shipping_address') or {}).get('name')
            with get_conn() as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO manapool_orders_cache (order_id, raw_json, fetched_at) VALUES (?, ?, ?)',
                    (order_id, json.dumps(data), _utc_now()),
                )
                conn.commit()
            order_label = order.get('label')
            for item in items:
                qty = int(item.get('quantity') or 1)
                line_items_total += qty
                product = item.get('product') or {}
                single = product.get('single') or {}
                scryfall_id = single.get('scryfall_id')
                if not scryfall_id:
                    warnings.append(f"Order {order_id}: missing scryfall_id")
                    continue
                order_ref = None
                if ship_name and order_label:
                    order_ref = f"{ship_name}, #{order_label}"
                raw_items.append({
                    'scryfall_id': scryfall_id,
                    'quantity': qty,
                    'single': single,
                    'ship_name': ship_name,
                    'order_ref': order_ref,
                })

    aggregated = {}
    for item in raw_items:
        scryfall_id = item['scryfall_id']
        aggregated.setdefault(scryfall_id, {'quantity': 0, 'single': item.get('single'), 'names': set(), 'refs': set()})
        aggregated[scryfall_id]['quantity'] += item.get('quantity', 1)
        if item.get('ship_name'):
            aggregated[scryfall_id]['names'].add(item['ship_name'])
        if item.get('order_ref'):
            aggregated[scryfall_id]['refs'].add(item['order_ref'])

    batch_name = f"ManaPool Unfulfilled - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    source_payload = {
        'order_ids': order_ids,
        'generated_at': _utc_now(),
        'orders_scanned': len(order_ids),
        'line_items': line_items_total,
        'unique_cards': len(aggregated),
    }

    with get_conn() as conn:
        conn.execute(
            'INSERT INTO batches (name, status, source, created_at, updated_at, source_payload) VALUES (?, ?, ?, ?, ?, ?)',
            (batch_name, 'open', 'manapool', _utc_now(), _utc_now(), json.dumps(source_payload)),
        )
        batch_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']

        for scryfall_id, info in aggregated.items():
            qty_required = info['quantity']
            single = info.get('single') or {}
            card = scryfall.fetch_card_by_id(conn, scryfall_id)
            card_name = None
            set_code = None
            collector_number = None
            if card:
                card_name = card.get('name')
                set_code = card.get('set')
                collector_number = card.get('collector_number')
            if not card_name:
                card_name = single.get('name')
            if not set_code:
                set_code = single.get('set')
            if not collector_number:
                collector_number = single.get('number')

            order_names = ', '.join(sorted(info.get('names') or []))
            order_refs = '; '.join(sorted(info.get('refs') or []))

            conn.execute(
                'INSERT INTO batch_items (batch_id, game, set_code, card_name, collector_number, scryfall_id, qty_required, qty_picked, condition, language, printing, order_names, order_refs, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)',
                (
                    batch_id,
                    'Magic',
                    (set_code or '').lower(),
                    card_name or '',
                    collector_number or None,
                    scryfall_id,
                    qty_required,
                    _map_condition(single.get('condition_id')),
                    single.get('language_id'),
                    _map_finish(single.get('finish_id')),
                    order_names or None,
                    order_refs or None,
                    _utc_now(),
                ),
            )
        conn.commit()

    summary = {
        'batch_id': batch_id,
        'batch_name': batch_name,
        'orders_scanned': len(order_ids),
        'line_items': line_items_total,
        'unique_cards': len(aggregated),
        'warnings': warnings,
        'errors': errors,
        'recent_warning': warning,
    }

    status = 'ok' if not errors else 'partial'
    _finish_sync_log(log_id, status, summary=summary, error='; '.join(errors) if errors else None)

    return JSONResponse(summary)

@app.get('/batch/new', response_class=HTMLResponse)
def batch_new_view(request: Request, auth=Depends(require_auth)):
    return TEMPLATES.TemplateResponse('batch_new.html', {'request': request})


@app.post('/batch/new')
def batch_new(request: Request, name: str = Form(...), source: str = Form('Local'), auth=Depends(require_auth)):
    with get_conn() as conn:
        conn.execute('INSERT INTO batches (name, status, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (name, 'open', source, _utc_now(), _utc_now()))
        batch_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
        conn.commit()
    return RedirectResponse(url=f'/batch/{batch_id}/add-item', status_code=HTTP_302_FOUND)


@app.get('/batch/{batch_id}/add-item', response_class=HTMLResponse)
def batch_add_item_view(request: Request, batch_id: int, auth=Depends(require_auth)):
    raise HTTPException(status_code=404)


@app.post('/batch/{batch_id}/items')
def batch_add_item(request: Request, batch_id: int, auth=Depends(require_auth)):
    raise HTTPException(status_code=404)


@app.get('/batch/{batch_id}', response_class=HTMLResponse)
def picklist(request: Request, batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        batch = conn.execute('SELECT * FROM batches WHERE id = ?', (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(status_code=404)
    batch_data = dict(batch)
    source_orders = []
    if batch_data.get('source_payload'):
        try:
            payload = json.loads(batch_data['source_payload'])
            source_orders = payload.get('order_ids', [])
        except Exception:
            source_orders = []
    return TEMPLATES.TemplateResponse('picklist.html', {'request': request, 'batch': batch, 'source_orders': source_orders})


def _reservation_map(conn, batch_id):
    rows = conn.execute('SELECT set_code, reserved_by FROM set_reservations WHERE batch_id = ?', (batch_id,)).fetchall()
    return {r['set_code']: r['reserved_by'] for r in rows}


def _backfill_order_names(conn, batch_id, order_ids):
    rows = conn.execute(
        'SELECT id, scryfall_id, order_names, order_refs FROM batch_items WHERE batch_id = ? AND ((order_names IS NULL OR order_names = "") OR (order_refs IS NULL OR order_refs = ""))',
        (batch_id,),
    ).fetchall()
    if not rows:
        return
    if not order_ids:
        order_ids = [r['order_id'] for r in conn.execute('SELECT order_id FROM manapool_orders_cache').fetchall()]
    if not order_ids:
        return
    name_map = {}
    ref_map = {}
    for oid in order_ids:
        cache = conn.execute('SELECT raw_json FROM manapool_orders_cache WHERE order_id = ?', (oid,)).fetchone()
        if not cache:
            continue
        try:
            data = json.loads(cache['raw_json'])
        except Exception:
            continue
        order = (data or {}).get('order') or {}
        ship_name = (order.get('shipping_address') or {}).get('name')
        order_label = order.get('label')
        items = order.get('items') or []
        if not ship_name:
            continue
        order_ref = f"{ship_name}, #{order_label}" if order_label else ship_name
        for item in items:
            product = item.get('product') or {}
            single = product.get('single') or {}
            scryfall_id = single.get('scryfall_id')
            if not scryfall_id:
                continue
            name_map.setdefault(scryfall_id, set()).add(ship_name)
            ref_map.setdefault(scryfall_id, set()).add(order_ref)
    for r in rows:
        names = name_map.get(r['scryfall_id'])
        refs = ref_map.get(r['scryfall_id'])
        if names or refs:
            conn.execute(
                'UPDATE batch_items SET order_names = COALESCE(?, order_names), order_refs = COALESCE(?, order_refs) WHERE id = ?',
                (', '.join(sorted(names)) if names else None, '; '.join(sorted(refs)) if refs else None, r['id']),
            )
    conn.commit()


@app.get('/batch/{batch_id}/counts', response_class=HTMLResponse)
def batch_counts(request: Request, batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        total = conn.execute('SELECT COUNT(*) AS c FROM batch_items WHERE batch_id = ?', (batch_id,)).fetchone()['c']
        remaining = conn.execute('SELECT COUNT(*) AS c FROM batch_items WHERE batch_id = ? AND qty_picked < qty_required', (batch_id,)).fetchone()['c']
        missing = conn.execute('SELECT COUNT(*) AS c FROM batch_items WHERE batch_id = ? AND is_missing = 1', (batch_id,)).fetchone()['c']
    return TEMPLATES.TemplateResponse('partials/counts.html', {'request': request, 'total': total, 'remaining': remaining, 'missing': missing})


@app.get('/batch/{batch_id}/items', response_class=HTMLResponse)
def batch_items(request: Request, batch_id: int, game: str = '', q: str = '', show_picked: int = 0, show_missing: int = 0, show_all: int = 0, auth=Depends(require_auth)):
    with get_conn() as conn:
        order_ids = []
        batch = conn.execute('SELECT source_payload FROM batches WHERE id = ?', (batch_id,)).fetchone()
        if batch and batch['source_payload']:
            try:
                payload = json.loads(batch['source_payload'])
                order_ids = payload.get('order_ids', []) or []
            except Exception:
                order_ids = []
        if show_missing:
            # Ensure missing-only rows can show order refs even for older batches.
            _backfill_order_names(conn, batch_id, order_ids)
        params = [batch_id]
        where = ['batch_id = ?']
        if game:
            where.append('game = ?')
            params.append(game)
        if q:
            where.append('card_name LIKE ?')
            params.append(f"%{q}%")
        if not show_all:
            if not show_picked:
                where.append('qty_picked < qty_required')
            if show_missing:
                where.append('is_missing = 1')
        sql = f"SELECT * FROM batch_items WHERE {' AND '.join(where)}"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        reservations = _reservation_map(conn, batch_id)
    rows = sort_items(rows)
    for r in rows:
        r['qty_remaining'] = remaining_qty(r)
        r['reserved_by'] = reservations.get(r['set_code'])
    return TEMPLATES.TemplateResponse('partials/items.html', {'request': request, 'items': rows, 'show_picked': bool(show_picked), 'show_missing': bool(show_missing)})


@app.get('/items/{item_id}/row', response_class=HTMLResponse)
def item_row(request: Request, item_id: int, show_picked: int = 0, show_missing: int = 0, show_all: int = 0, auth=Depends(require_auth)):
    with get_conn() as conn:
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
        if not item:
            return HTMLResponse('', status_code=HTTP_204_NO_CONTENT)
        item = dict(item)
        if not show_all:
            if not show_picked and item['qty_picked'] >= item['qty_required']:
                return HTMLResponse('', status_code=HTTP_204_NO_CONTENT)
            if show_missing and not item['is_missing']:
                return HTMLResponse('', status_code=HTTP_204_NO_CONTENT)
        reservations = _reservation_map(conn, item['batch_id'])
        item['reserved_by'] = reservations.get(item['set_code'])
    item['qty_remaining'] = remaining_qty(item)
    return TEMPLATES.TemplateResponse('partials/item_row.html', {'request': request, 'item': item, 'qty_remaining': item['qty_remaining'], 'show_reserve': True, 'show_missing': bool(show_missing)})


@app.post('/batch/{batch_id}/reserve-set')
async def reserve_set(request: Request, batch_id: int, set_code: str = Form(...), reserved_by: str = Form('anonymous'), auth=Depends(require_auth)):
    set_code = (set_code or '').lower()
    reserved_by = (reserved_by or 'anonymous').strip() or 'anonymous'
    with get_conn() as conn:
        existing = conn.execute('SELECT reserved_by FROM set_reservations WHERE batch_id = ? AND set_code = ?', (batch_id, set_code)).fetchone()
        if existing and existing['reserved_by'] == reserved_by:
            conn.execute('DELETE FROM set_reservations WHERE batch_id = ? AND set_code = ?', (batch_id, set_code))
            conn.commit()
            await manager.broadcast(batch_id, {'type': 'set_reserved', 'set_code': set_code, 'reserved_by': None})
            return JSONResponse({'ok': True, 'reserved_by': None})
        if existing:
            conn.execute('UPDATE set_reservations SET reserved_by = ?, reserved_at = ? WHERE batch_id = ? AND set_code = ?', (reserved_by, _utc_now(), batch_id, set_code))
        else:
            conn.execute('INSERT INTO set_reservations (batch_id, set_code, reserved_by, reserved_at) VALUES (?, ?, ?, ?)', (batch_id, set_code, reserved_by, _utc_now()))
        conn.commit()
    await manager.broadcast(batch_id, {'type': 'set_reserved', 'set_code': set_code, 'reserved_by': reserved_by})
    return JSONResponse({'ok': True, 'reserved_by': reserved_by})

@app.post('/items/{item_id}/pick', response_class=HTMLResponse)
async def pick_item(request: Request, item_id: int, show_picked: int = 0, show_missing: int = 0, show_all: int = 0, auth=Depends(require_auth)):
    session_id = request.session.get('sid') or str(uuid.uuid4())
    request.session['sid'] = session_id
    with get_conn() as conn:
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404)
        qty_remaining = item['qty_required'] - item['qty_picked']
        if qty_remaining <= 0:
            return HTMLResponse('', status_code=200)
        conn.execute('UPDATE batch_items SET qty_picked = qty_picked + 1, updated_at = ? WHERE id = ?', (_utc_now(), item_id))
        conn.execute('INSERT INTO events (type, batch_item_id, qty, timestamp, user_session_id) VALUES (?, ?, ?, ?, ?)', ('pick', item_id, 1, _utc_now(), session_id))
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
    await manager.broadcast(item['batch_id'], {'type': 'item_update', 'item_id': item_id})
    qty_rem = remaining_qty(item)
    if not show_all:
        if not show_picked and qty_rem == 0:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
        if show_missing and not item['is_missing']:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
    resp = TEMPLATES.TemplateResponse('partials/item_row.html', {'request': request, 'item': dict(item), 'qty_remaining': qty_rem, 'show_reserve': True, 'show_missing': bool(show_missing)})
    resp.headers['HX-Trigger'] = 'batch-counts-changed'
    return resp


@app.post('/items/{item_id}/undo', response_class=HTMLResponse)
async def undo_pick(request: Request, item_id: int, show_picked: int = 0, show_missing: int = 0, show_all: int = 0, auth=Depends(require_auth)):
    session_id = request.session.get('sid')
    with get_conn() as conn:
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404)
        if item['qty_picked'] <= 0:
            return HTMLResponse('', status_code=200)
        conn.execute('UPDATE batch_items SET qty_picked = qty_picked - 1, updated_at = ? WHERE id = ?', (_utc_now(), item_id))
        conn.execute('INSERT INTO events (type, batch_item_id, qty, timestamp, user_session_id) VALUES (?, ?, ?, ?, ?)', ('undo', item_id, 1, _utc_now(), session_id))
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
    await manager.broadcast(item['batch_id'], {'type': 'item_update', 'item_id': item_id})
    qty_rem = remaining_qty(item)
    if not show_all:
        if not show_picked and qty_rem == 0:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
        if show_missing and not item['is_missing']:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
    resp = TEMPLATES.TemplateResponse('partials/item_row.html', {'request': request, 'item': dict(item), 'qty_remaining': qty_rem, 'show_reserve': True, 'show_missing': bool(show_missing)})
    resp.headers['HX-Trigger'] = 'batch-counts-changed'
    return resp


@app.post('/items/{item_id}/missing', response_class=HTMLResponse)
async def mark_missing(request: Request, item_id: int, note: str = Form(''), show_picked: int = 0, show_missing: int = 0, show_all: int = 0, auth=Depends(require_auth)):
    session_id = request.session.get('sid')
    with get_conn() as conn:
        conn.execute('UPDATE batch_items SET is_missing = 1, missing_note = ?, updated_at = ? WHERE id = ?', (note, _utc_now(), item_id))
        conn.execute('INSERT INTO events (type, batch_item_id, qty, timestamp, user_session_id) VALUES (?, ?, ?, ?, ?)', ('missing', item_id, 0, _utc_now(), session_id))
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
    await manager.broadcast(item['batch_id'], {'type': 'item_update', 'item_id': item_id})
    qty_rem = remaining_qty(item)
    if not show_all:
        if not show_picked and qty_rem == 0:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
        if show_missing and not item['is_missing']:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
    resp = TEMPLATES.TemplateResponse('partials/item_row.html', {'request': request, 'item': dict(item), 'qty_remaining': qty_rem, 'show_reserve': True, 'show_missing': bool(show_missing)})
    resp.headers['HX-Trigger'] = 'batch-counts-changed'
    return resp


@app.post('/items/{item_id}/unmissing', response_class=HTMLResponse)
async def unmark_missing(request: Request, item_id: int, show_picked: int = 0, show_missing: int = 0, show_all: int = 0, auth=Depends(require_auth)):
    session_id = request.session.get('sid')
    with get_conn() as conn:
        conn.execute('UPDATE batch_items SET is_missing = 0, missing_note = NULL, updated_at = ? WHERE id = ?', (_utc_now(), item_id))
        conn.execute('INSERT INTO events (type, batch_item_id, qty, timestamp, user_session_id) VALUES (?, ?, ?, ?, ?)', ('unmissing', item_id, 0, _utc_now(), session_id))
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
    await manager.broadcast(item['batch_id'], {'type': 'item_update', 'item_id': item_id})
    qty_rem = remaining_qty(item)
    if not show_all:
        if not show_picked and qty_rem == 0:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
        if show_missing and not item['is_missing']:
            resp = HTMLResponse('')
            resp.headers['HX-Trigger'] = 'batch-counts-changed'
            return resp
    resp = TEMPLATES.TemplateResponse('partials/item_row.html', {'request': request, 'item': dict(item), 'qty_remaining': qty_rem, 'show_reserve': True, 'show_missing': bool(show_missing)})
    resp.headers['HX-Trigger'] = 'batch-counts-changed'
    return resp


@app.get('/batch/{batch_id}/missing', response_class=HTMLResponse)
def missing_view(request: Request, batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        batch = conn.execute('SELECT * FROM batches WHERE id = ?', (batch_id,)).fetchone()
        order_ids = []
        if batch and batch['source_payload']:
            try:
                payload = json.loads(batch['source_payload'])
                order_ids = payload.get('order_ids', [])
            except Exception:
                order_ids = []
        _backfill_order_names(conn, batch_id, order_ids)
        rows = conn.execute('SELECT * FROM batch_items WHERE batch_id = ? AND is_missing = 1 ORDER BY game, set_code, card_name', (batch_id,)).fetchall()
    return TEMPLATES.TemplateResponse('missing.html', {'request': request, 'batch': batch, 'items': rows})


@app.get('/batch/{batch_id}/missing.csv')
def missing_export(batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        rows = conn.execute('SELECT * FROM batch_items WHERE batch_id = ? AND is_missing = 1 ORDER BY game, set_code, card_name', (batch_id,)).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['card_name', 'set_code', 'qty_required', 'missing_note'])
    for r in rows:
        writer.writerow([r['card_name'], r['set_code'], r['qty_required'], r['missing_note'] or ''])
    return PlainTextResponse(output.getvalue(), media_type='text/csv')


@app.get('/batch/{batch_id}/packing-slip', response_class=HTMLResponse)
def packing_slip(request: Request, batch_id: int, auth=Depends(require_auth)):
    raise HTTPException(status_code=404)


@app.get('/batch/{batch_id}/events', response_class=HTMLResponse)
def events_view(request: Request, batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        batch = conn.execute('SELECT * FROM batches WHERE id = ?', (batch_id,)).fetchone()
        rows = conn.execute('SELECT e.*, bi.card_name FROM events e JOIN batch_items bi ON bi.id = e.batch_item_id WHERE bi.batch_id = ? ORDER BY e.timestamp DESC', (batch_id,)).fetchall()
    return TEMPLATES.TemplateResponse('events.html', {'request': request, 'batch': batch, 'events': rows})


@app.get('/batch/{batch_id}/summary', response_class=HTMLResponse)
def batch_summary(request: Request, batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        batch = conn.execute('SELECT * FROM batches WHERE id = ?', (batch_id,)).fetchone()
        total = conn.execute('SELECT COUNT(*) AS c FROM batch_items WHERE batch_id = ?', (batch_id,)).fetchone()['c']
        picked = conn.execute('SELECT COUNT(*) AS c FROM batch_items WHERE batch_id = ? AND qty_picked >= qty_required', (batch_id,)).fetchone()['c']
        missing = conn.execute('SELECT COUNT(*) AS c FROM batch_items WHERE batch_id = ? AND is_missing = 1', (batch_id,)).fetchone()['c']
        rows = conn.execute('SELECT * FROM batch_items WHERE batch_id = ? AND is_missing = 1 ORDER BY game, set_code, card_name', (batch_id,)).fetchall()
    return TEMPLATES.TemplateResponse('batch_summary.html', {'request': request, 'batch': batch, 'total': total, 'picked': picked, 'missing': missing, 'items': rows})


@app.post('/batch/{batch_id}/close')
def close_batch(request: Request, batch_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        conn.execute('UPDATE batches SET status = ?, updated_at = ? WHERE id = ?', ('closed', _utc_now(), batch_id))
        conn.commit()
    return RedirectResponse(url=f'/batch/{batch_id}/summary', status_code=HTTP_302_FOUND)


@app.get('/card/modal', response_class=HTMLResponse)
def card_modal(request: Request, item_id: int, auth=Depends(require_auth)):
    with get_conn() as conn:
        item = conn.execute('SELECT * FROM batch_items WHERE id = ?', (item_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404)
        item = dict(item)
        card, strategy = scryfall.resolve_card(conn, item)
        image_path = scryfall.ensure_image_cached(card) if card else None
        if card:
            scryfall.ensure_image_cached(card, size='large')
    return TEMPLATES.TemplateResponse('partials/card_modal.html', {'request': request, 'item': item, 'card': card, 'strategy': strategy, 'image_path': image_path})


@app.get('/card/image/{card_id}')
def card_image(card_id: str, size: str = 'normal', auth=Depends(require_auth)):
    path = Path('data/cache/images') / f"{card_id}_{size}.jpg"
    if path.exists():
        return FileResponse(str(path))
    with get_conn() as conn:
        card = scryfall.fetch_card_by_id(conn, card_id)
        if card:
            scryfall.ensure_image_cached(card, size=size)
    if path.exists():
        return FileResponse(str(path))
    raise HTTPException(status_code=404)


@app.get('/cards/search', response_class=HTMLResponse)
def card_search(request: Request, name: str, item_id: int = 0, auth=Depends(require_auth)):
    cards = scryfall.search_cards(name)
    return TEMPLATES.TemplateResponse('partials/card_search.html', {'request': request, 'cards': cards, 'name': name, 'item_id': item_id})

@app.post('/items/{item_id}/link_scryfall')
def link_scryfall(item_id: int, scryfall_id: str = Form(...), auth=Depends(require_auth)):
    with get_conn() as conn:
        conn.execute('UPDATE batch_items SET scryfall_id = ?, updated_at = ? WHERE id = ?', (scryfall_id, _utc_now(), item_id))
        conn.commit()
    return JSONResponse({'ok': True})


@app.get('/import', response_class=HTMLResponse)
def import_view(request: Request, auth=Depends(require_auth)):
    return TEMPLATES.TemplateResponse('import.html', {'request': request})


@app.post('/import')
def import_csv(request: Request, file: UploadFile = File(...), auth=Depends(require_auth)):
    content = file.file.read().decode('utf-8')
    reader = csv.DictReader(StringIO(content))
    with get_conn() as conn:
        batch_map = {}
        for row in reader:
            batch_name = row.get('batch_name') or 'Unnamed Batch'
            if batch_name not in batch_map:
                conn.execute('INSERT INTO batches (name, status, created_at, updated_at, source) VALUES (?, ?, ?, ?, ?)', (batch_name, 'open', _utc_now(), _utc_now(), row.get('source')))
                batch_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
                batch_map[batch_name] = batch_id
            batch_id = batch_map[batch_name]
            conn.execute(
                'INSERT INTO batch_items (batch_id, game, set_code, card_name, collector_number, qty_required, qty_picked, condition, language, printing, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)',
                (
                    batch_id,
                    row.get('game') or '',
                    (row.get('set_code') or '').lower(),
                    row.get('card_name') or '',
                    row.get('collector_number') or None,
                    int(row.get('qty_required') or 0),
                    row.get('condition') or None,
                    row.get('language') or None,
                    row.get('printing') or None,
                    _utc_now(),
                ),
            )
        conn.commit()
    return RedirectResponse(url='/', status_code=HTTP_302_FOUND)


@app.get('/settings', response_class=HTMLResponse)
def settings(request: Request, auth=Depends(require_auth)):
    raise HTTPException(status_code=404)


@app.post('/settings/login')
def settings_login(request: Request, pin: str = Form(...), auth=Depends(require_auth)):
    raise HTTPException(status_code=404)


@app.post('/bins')
def add_bin(request: Request, game: str = Form(...), set_code: str = Form(...), location: str = Form(...), note: str = Form(''), auth=Depends(require_auth)):
    raise HTTPException(status_code=404)


@app.get('/bins', response_class=HTMLResponse)
def get_bins(request: Request, game: str, set_code: str, auth=Depends(require_auth)):
    raise HTTPException(status_code=404)



@app.get('/health', response_class=HTMLResponse)
def health_view(request: Request, auth=Depends(require_auth)):
    batch_orders = []
    with get_conn() as conn:
        cache_count = conn.execute('SELECT COUNT(*) AS c FROM manapool_orders_cache').fetchone()['c']
        last = conn.execute('SELECT started_at, status FROM manapool_sync_log ORDER BY started_at DESC LIMIT 1').fetchone()
        batches = conn.execute("SELECT id, name, source_payload FROM batches WHERE source = 'manapool' ORDER BY created_at DESC").fetchall()
        cache_rows = conn.execute('SELECT order_id, raw_json FROM manapool_orders_cache').fetchall()
    label_by_id = {}
    for r in cache_rows:
        try:
            data = json.loads(r['raw_json'])
            label = ((data or {}).get('order') or {}).get('label')
            if label:
                label_by_id[r['order_id']] = label
        except Exception:
            continue
    for b in batches:
        order_ids = []
        if b['source_payload']:
            try:
                payload = json.loads(b['source_payload'])
                order_ids = payload.get('order_ids', []) or []
            except Exception:
                order_ids = []
        order_numbers = []
        for oid in order_ids:
            label = label_by_id.get(oid)
            order_numbers.append(f"#{label}" if label else oid)
        batch_orders.append({'id': b['id'], 'name': b['name'], 'order_numbers': ', '.join(order_numbers) if order_numbers else 'None'})
    last_sync = f"{last['started_at']} ({last['status']})" if last else 'None'
    return TEMPLATES.TemplateResponse('health.html', {
        'request': request,
        'db_path': os.getenv('DB_PATH', 'data/app.db'),
        'manapool_configured': manapool.is_configured(),
        'cache_count': cache_count,
        'last_sync': last_sync,
        'batch_orders': batch_orders,
    })




















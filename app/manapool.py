import os

from .env import load_optional_dotenv

load_optional_dotenv()
import time
import logging
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger('manapool')

BASE_URL = os.getenv('MANAPOOL_BASE_URL', 'https://manapool.com/api/v1')
EMAIL = os.getenv('MANAPOOL_EMAIL')
ACCESS_TOKEN = os.getenv('MANAPOOL_ACCESS_TOKEN')

MAX_RETRIES = int(os.getenv('MANAPOOL_MAX_RETRIES', '3'))
TIMEOUT_SECONDS = int(os.getenv('MANAPOOL_TIMEOUT_SECONDS', '20'))

# When 0 (default), inventory writes are dry-run: the intended change is logged
# and returned but NOT sent to ManaPool. Set to 1 to perform real delists.
INVENTORY_WRITE = (os.getenv('MANAPOOL_INVENTORY_WRITE', '0').strip().lower() in ('1', 'true', 'yes'))
SESSION = requests.Session()
SESSION.mount('https://', HTTPAdapter(pool_connections=20, pool_maxsize=20))
SESSION.mount('http://', HTTPAdapter(pool_connections=20, pool_maxsize=20))


def is_configured():
    return bool(EMAIL and ACCESS_TOKEN)


def _headers():
    return {
        'X-ManaPool-Email': EMAIL or '',
        'X-ManaPool-Access-Token': ACCESS_TOKEN or '',
        'Content-Type': 'application/json',
    }


def _request(method, path, params=None, json_body=None):
    last_err = None
    url = f"{BASE_URL}{path}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.request(method, url, params=params, json=json_body, headers=_headers(), timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_err = str(exc)
            time.sleep(0.5 * (2 ** attempt))
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(0.5 * (2 ** attempt))
            continue
        return resp, None
    return None, last_err or 'ManaPool request failed'


def list_unfulfilled_orders(limit=100):
    orders = []
    offset = 0
    while True:
        params = {
            'is_fulfilled': 'false',
            'limit': limit,
            'offset': offset,
        }
        resp, err = _request('GET', '/seller/orders', params=params)
        if err:
            return None, err
        if resp.status_code != 200:
            return None, f"ManaPool error: {resp.status_code}"
        data = resp.json()
        batch = data.get('orders', [])
        orders.extend(batch)
        if not batch or len(batch) < limit:
            break
        offset += limit
    return orders, None


def fetch_order(order_id):
    resp, err = _request('GET', f"/seller/orders/{order_id}")
    if err:
        return None, err
    if resp.status_code != 200:
        return None, f"ManaPool error: {resp.status_code}"
    return resp.json(), None


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def list_inventory(limit=500):
    """Page through GET /seller/inventory and return all inventory items."""
    items = []
    offset = 0
    while True:
        params = {'limit': limit, 'offset': offset}
        resp, err = _request('GET', '/seller/inventory', params=params)
        if err:
            return None, err
        if resp.status_code != 200:
            return None, f"ManaPool error: {resp.status_code}"
        data = resp.json()
        batch = data.get('inventory', []) or []
        items.extend(batch)
        pagination = data.get('pagination') or {}
        total = pagination.get('total')
        offset += len(batch)
        if not batch:
            break
        if total is not None and offset >= total:
            break
        if len(batch) < limit:
            break
    return items, None


def refresh_inventory_cache(conn):
    """Fetch the seller inventory and replace the manapool_inventory cache.

    Returns (summary_dict, error).
    """
    items, err = list_inventory()
    if err:
        return None, err
    rows = []
    singles = 0
    for it in items:
        product = it.get('product') or {}
        single = product.get('single') or {}
        # Only singles carry a scryfall_id we can match against CardKingdom.
        if not single:
            continue
        singles += 1
        rows.append((
            it.get('id'),
            single.get('scryfall_id'),
            product.get('tcgplayer_sku'),
            single.get('name'),
            (single.get('set') or '').lower() or None,
            single.get('number'),
            single.get('condition_id'),
            single.get('finish_id'),
            single.get('language_id'),
            it.get('price_cents'),
            it.get('quantity'),
            _utc_now(),
        ))
    conn.execute('DELETE FROM manapool_inventory')
    if rows:
        conn.executemany(
            'INSERT OR REPLACE INTO manapool_inventory '
            '(inventory_id, scryfall_id, tcgplayer_sku, name, set_code, collector_number, '
            'condition_id, finish_id, language_id, price_cents, quantity, fetched_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            rows,
        )
    conn.commit()
    return {
        'items': len(items),
        'singles': singles,
        'rows': len(rows),
        'fetched_at': _utc_now(),
        'write_enabled': INVENTORY_WRITE,
    }, None


def set_inventory_quantity(scryfall_id, condition_id, finish_id, language_id,
                           new_quantity, price_cents):
    """Set the quantity for a specific inventory variant (delist when 0).

    Gated by MANAPOOL_INVENTORY_WRITE. When disabled, returns a dry-run result
    without contacting ManaPool. Identifies the listing by scryfall_id plus the
    condition/finish/language variant. Returns (result_dict, error).
    """
    params = {}
    if language_id:
        params['language_id'] = language_id
    if finish_id:
        params['finish_id'] = finish_id
    if condition_id:
        params['condition_id'] = condition_id

    action = 'delete' if new_quantity is not None and new_quantity <= 0 else 'update'
    intent = {
        'action': action,
        'scryfall_id': scryfall_id,
        'variant': dict(params),
        'new_quantity': new_quantity,
        'dry_run': not INVENTORY_WRITE,
    }

    if not INVENTORY_WRITE:
        log.info('DRY-RUN ManaPool inventory %s: %s', action, intent)
        return intent, None

    if not is_configured():
        return None, 'ManaPool not configured'

    path = f"/seller/inventory/scryfall_id/{scryfall_id}"
    if action == 'delete':
        resp, err = _request('DELETE', path, params=params)
    else:
        body = {'quantity': int(new_quantity)}
        if price_cents is not None:
            body['price_cents'] = int(price_cents)
        resp, err = _request('PUT', path, params=params, json_body=body)
    if err:
        return None, err
    if resp.status_code not in (200, 201, 204):
        return None, f"ManaPool error: {resp.status_code} {resp.text[:200]}"
    intent['status_code'] = resp.status_code
    return intent, None

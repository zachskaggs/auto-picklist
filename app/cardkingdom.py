import os

from .env import load_optional_dotenv

load_optional_dotenv()
import time
import requests
from requests.adapters import HTTPAdapter
from datetime import datetime

BASE_URL = os.getenv('CARDKINGDOM_BASE_URL', 'https://api.cardkingdom.com')
PRICELIST_PATH = os.getenv('CARDKINGDOM_PRICELIST_PATH', '/api/v2/pricelist')

MAX_RETRIES = int(os.getenv('CARDKINGDOM_MAX_RETRIES', '3'))
TIMEOUT_SECONDS = int(os.getenv('CARDKINGDOM_TIMEOUT_SECONDS', '120'))

SESSION = requests.Session()
SESSION.mount('https://', HTTPAdapter(pool_connections=4, pool_maxsize=4))
SESSION.mount('http://', HTTPAdapter(pool_connections=4, pool_maxsize=4))


def is_configured():
    # The CardKingdom pricelist is a public, unauthenticated endpoint.
    return True


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _to_float(value):
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        if value is None or value == '':
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_foil(value):
    """CardKingdom returns is_foil as the string "true"/"false" (sometimes 1/0)."""
    if isinstance(value, bool):
        return 1 if value else 0
    s = str(value).strip().lower()
    return 1 if s in ('true', '1', 'yes', 'foil') else 0


def fetch_pricelist():
    """Download the full CardKingdom pricelist. Returns (payload_dict, error)."""
    url = f"{BASE_URL}{PRICELIST_PATH}"
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = SESSION.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_err = str(exc)
            time.sleep(0.5 * (2 ** attempt))
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"CardKingdom error: {resp.status_code}"
            time.sleep(0.5 * (2 ** attempt))
            continue
        if resp.status_code != 200:
            return None, f"CardKingdom error: {resp.status_code}"
        try:
            return resp.json(), None
        except ValueError as exc:
            return None, f"CardKingdom response not JSON: {exc}"
    return None, last_err or 'CardKingdom request failed'


def normalize_rows(data):
    """Normalize raw pricelist entries into dedup'd buylist rows.

    Keeps only rows with price_buy > 0, deduplicates on (scryfall_id, is_foil)
    keeping the highest price_buy. Returns a list of dict rows.
    """
    best = {}
    for entry in data or []:
        scryfall_id = entry.get('scryfall_id')
        if not scryfall_id:
            continue
        price_buy = _to_float(entry.get('price_buy'))
        if price_buy is None or price_buy <= 0:
            continue
        is_foil = _to_foil(entry.get('is_foil'))
        key = (scryfall_id, is_foil)
        existing = best.get(key)
        if existing and existing['price_buy'] >= price_buy:
            continue
        best[key] = {
            'scryfall_id': scryfall_id,
            'is_foil': is_foil,
            'name': entry.get('name'),
            'edition': entry.get('edition'),
            'sku': entry.get('sku'),
            'url': entry.get('url'),
            'price_buy': price_buy,
            'qty_buying': _to_int(entry.get('qty_buying')),
        }
    return list(best.values())


def refresh_buylist_cache(conn):
    """Fetch the CardKingdom pricelist and replace the ck_buylist cache.

    Returns (summary_dict, error).
    """
    payload, err = fetch_pricelist()
    if err:
        return None, err
    meta = (payload or {}).get('meta') or {}
    rows = normalize_rows((payload or {}).get('data') or [])
    insert_rows = [
        (
            r['scryfall_id'], r['is_foil'], r['name'], r['edition'],
            r['sku'], r['url'], r['price_buy'], r['qty_buying'],
        )
        for r in rows
    ]
    conn.execute('DELETE FROM ck_buylist')
    if insert_rows:
        conn.executemany(
            'INSERT OR REPLACE INTO ck_buylist '
            '(scryfall_id, is_foil, name, edition, sku, url, price_buy, qty_buying) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            insert_rows,
        )
    conn.commit()
    return {
        'rows': len(insert_rows),
        'created_at': meta.get('created_at'),
        'fetched_at': _utc_now(),
    }, None

import os
import time
import requests

BASE_URL = os.getenv('MANAPOOL_BASE_URL', 'https://manapool.com/api/v1')
EMAIL = os.getenv('MANAPOOL_EMAIL')
ACCESS_TOKEN = os.getenv('MANAPOOL_ACCESS_TOKEN')

MAX_RETRIES = int(os.getenv('MANAPOOL_MAX_RETRIES', '3'))
TIMEOUT_SECONDS = int(os.getenv('MANAPOOL_TIMEOUT_SECONDS', '20'))


def is_configured():
    return bool(EMAIL and ACCESS_TOKEN)


def _headers():
    return {
        'X-ManaPool-Email': EMAIL or '',
        'X-ManaPool-Access-Token': ACCESS_TOKEN or '',
        'Content-Type': 'application/json',
    }


def _request(method, path, params=None):
    last_err = None
    url = f"{BASE_URL}{path}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.request(method, url, params=params, headers=_headers(), timeout=TIMEOUT_SECONDS)
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

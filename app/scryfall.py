import os

from .env import load_optional_dotenv

load_optional_dotenv()
import json
from pathlib import Path
import requests
from datetime import datetime

BASE_URL = os.getenv('SCRYFALL_BASE_URL', 'https://api.scryfall.com')
IMAGE_SIZE = os.getenv('SCRYFALL_IMAGE_SIZE', 'normal')
CACHE_DIR = Path('data/cache/images')


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _get(conn, sql, args=()):
    cur = conn.execute(sql, args)
    return cur.fetchone()


def _save_card_cache(conn, card):
    if not card or 'id' not in card:
        return
    conn.execute(
        'INSERT OR REPLACE INTO card_cache (scryfall_id, card_name, set_code, collector_number, data_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
        (
            card.get('id'),
            card.get('name'),
            card.get('set'),
            card.get('collector_number'),
            json.dumps(card),
            _utc_now(),
        ),
    )
    conn.commit()


def _load_card_cache(conn, scryfall_id):
    row = _get(conn, 'SELECT data_json FROM card_cache WHERE scryfall_id = ?', (scryfall_id,))
    if not row:
        return None
    return json.loads(row['data_json'])


def fetch_card_by_id(conn, scryfall_id):
    cached = _load_card_cache(conn, scryfall_id)
    if cached:
        return cached
    try:
        resp = requests.get(f"{BASE_URL}/cards/{scryfall_id}", timeout=15)
        if resp.status_code == 200:
            card = resp.json()
            _save_card_cache(conn, card)
            return card
    except requests.RequestException:
        return None
    return None


def fetch_card_by_set(conn, set_code, collector_number):
    try:
        resp = requests.get(f"{BASE_URL}/cards/{set_code}/{collector_number}", timeout=15)
        if resp.status_code == 200:
            card = resp.json()
            _save_card_cache(conn, card)
            return card
    except requests.RequestException:
        return None
    return None


def fetch_card_fuzzy(conn, name):
    try:
        resp = requests.get(f"{BASE_URL}/cards/named", params={'fuzzy': name}, timeout=15)
        if resp.status_code == 200:
            card = resp.json()
            _save_card_cache(conn, card)
            return card
    except requests.RequestException:
        return None
    return None


def search_cards(name, limit=10):
    try:
        resp = requests.get(f"{BASE_URL}/cards/search", params={'q': name, 'order': 'released'}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('data', [])[:limit]
    except requests.RequestException:
        return []
    return []


def resolve_card(conn, item):
    if item.get('scryfall_id'):
        return fetch_card_by_id(conn, item['scryfall_id']), 'id'
    if item.get('set_code') and item.get('collector_number'):
        card = fetch_card_by_set(conn, item['set_code'], item['collector_number'])
        if card:
            return card, 'set'
    if item.get('card_name'):
        card = fetch_card_fuzzy(conn, item['card_name'])
        if card:
            return card, 'fuzzy'
    return None, None


def _image_url(card, size):
    if not card:
        return None
    if card.get('image_uris'):
        return card['image_uris'].get(size)
    faces = card.get('card_faces') or []
    if faces:
        return faces[0].get('image_uris', {}).get(size)
    return None


def ensure_image_cached(card, size=IMAGE_SIZE):
    url = _image_url(card, size)
    if not url:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{card['id']}_{size}.jpg"
    if path.exists():
        return path
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200:
            path.write_bytes(resp.content)
            return path
    except requests.RequestException:
        return None
    return None

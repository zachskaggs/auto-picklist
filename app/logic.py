from datetime import datetime, timedelta


def game_sort_key(game):
    if not game:
        return (2, '')
    g = game.lower()
    if g.startswith('magic'):
        return (0, game)
    return (1, game)


def sort_items(items):
    def _key(r):
        set_code = (r.get('set_code') or '').strip()
        set_missing = 1 if not set_code else 0
        return (game_sort_key(r.get('game')), set_missing, set_code, r.get('card_name') or '')
    return sorted(items, key=_key)


def remaining_qty(item):
    return max(0, int(item['qty_required']) - int(item['qty_picked']))


def is_missing(item):
    return bool(item.get('is_missing'))


def aggregate_by_scryfall(items):
    aggregated = {}
    for item in items:
        scryfall_id = item.get('scryfall_id')
        if not scryfall_id:
            continue
        qty = int(item.get('quantity') or 1)
        aggregated[scryfall_id] = aggregated.get(scryfall_id, 0) + qty
    return aggregated


def compute_undo_deadline(now=None, seconds=5):
    now = now or datetime.utcnow()
    return now + timedelta(seconds=seconds)

from datetime import datetime
from app.logic import sort_items, remaining_qty, compute_undo_deadline, is_missing, aggregate_by_scryfall


def test_sort_items():
    items = [
        {'game': 'Pokemon', 'set_code': 'sv1', 'card_name': 'Zard'},
        {'game': 'Magic', 'set_code': '', 'card_name': 'Omega'},
        {'game': 'Magic', 'set_code': 'woe', 'card_name': 'Alpha'},
        {'game': 'Magic', 'set_code': 'woe', 'card_name': 'Beta'},
    ]
    out = sort_items(items)
    assert out[0]['card_name'] == 'Alpha'
    assert out[1]['card_name'] == 'Beta'
    assert out[-1]['card_name'] == 'Omega'


def test_remaining_qty():
    item = {'qty_required': 3, 'qty_picked': 1}
    assert remaining_qty(item) == 2


def test_missing_flag():
    assert is_missing({'is_missing': 1}) is True
    assert is_missing({'is_missing': 0}) is False


def test_aggregate_by_scryfall():
    items = [
        {'scryfall_id': 'a', 'quantity': 1},
        {'scryfall_id': 'b', 'quantity': 2},
        {'scryfall_id': 'a', 'quantity': 3},
    ]
    out = aggregate_by_scryfall(items)
    assert out['a'] == 4
    assert out['b'] == 2


def test_undo_deadline():
    now = datetime(2024, 1, 1, 0, 0, 0)
    deadline = compute_undo_deadline(now, 5)
    assert (deadline - now).total_seconds() == 5

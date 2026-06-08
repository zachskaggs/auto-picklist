"""Pure report computation: match ManaPool inventory against CardKingdom buylist."""

FOIL_FINISHES = ('FO', 'EF')


def finish_to_foil(finish_id):
    """ManaPool finish_id -> CardKingdom is_foil (1/0)."""
    return 1 if (finish_id or '').upper() in FOIL_FINISHES else 0


def _row_value(r):
    return r['value']


def _row_ratio(r):
    return r['ratio'] if r['ratio'] is not None else -1


def compute_report(conn, min_ratio=0.75, sort_by='value', only_buying=True):
    """Join cached ManaPool inventory with cached CardKingdom buylist.

    Returns a list of dict rows, each describing one ManaPool listing matched to
    a CardKingdom buy price. Sorted by total sellable value (default) or ratio.
    """
    sql = (
        'SELECT mi.inventory_id, mi.scryfall_id, mi.tcgplayer_sku, mi.name, '
        '       mi.set_code, mi.collector_number, mi.condition_id, mi.finish_id, '
        '       mi.language_id, mi.price_cents, mi.quantity, '
        '       cb.is_foil, cb.price_buy, cb.qty_buying, cb.url AS ck_url, '
        '       cb.name AS ck_name, cb.edition AS ck_edition '
        'FROM manapool_inventory mi '
        'JOIN ck_buylist cb '
        '  ON cb.scryfall_id = mi.scryfall_id '
        ' AND cb.is_foil = (CASE WHEN UPPER(COALESCE(mi.finish_id, \'\')) IN (\'FO\', \'EF\') THEN 1 ELSE 0 END)'
    )
    out = []
    for row in conn.execute(sql).fetchall():
        r = dict(row)
        price_cents = r.get('price_cents')
        mp_price = (price_cents / 100.0) if price_cents else None
        ck_price = r.get('price_buy') or 0.0
        qty = int(r.get('quantity') or 0)
        qty_buying = int(r.get('qty_buying') or 0)

        if only_buying and qty_buying <= 0:
            continue

        ratio = (ck_price / mp_price) if (mp_price and mp_price > 0) else None
        sell_qty = min(qty, qty_buying) if qty_buying > 0 else qty
        value = ck_price * sell_qty
        condition_id = (r.get('condition_id') or '').upper()

        out.append({
            'inventory_id': r.get('inventory_id'),
            'scryfall_id': r.get('scryfall_id'),
            'tcgplayer_sku': r.get('tcgplayer_sku'),
            'card_name': r.get('name'),
            'set_code': r.get('set_code'),
            'collector_number': r.get('collector_number'),
            'condition_id': condition_id,
            'finish_id': r.get('finish_id'),
            'language_id': r.get('language_id'),
            'is_foil': int(r.get('is_foil') or 0),
            'mp_price': round(mp_price, 2) if mp_price is not None else None,
            'quantity': qty,
            'ck_price': round(ck_price, 2),
            'qty_buying': qty_buying,
            'ratio': round(ratio, 4) if ratio is not None else None,
            'sell_qty': sell_qty,
            'value': round(value, 2),
            'is_nm': condition_id == 'NM',
            'meets': (ratio is not None and ratio >= min_ratio),
            'ck_url': r.get('ck_url'),
            'ck_name': r.get('ck_name'),
            'ck_edition': r.get('ck_edition'),
        })

    if (sort_by or '').lower() == 'ratio':
        out.sort(key=_row_ratio, reverse=True)
    else:
        out.sort(key=_row_value, reverse=True)
    return out


def build_ck_sell_csv(items):
    """Build CardKingdom sell-import CSV text from picked batch items.

    CardKingdom's importer reads the first four columns positionally as
    Title, Edition, Foil, Quantity (no header row). Edition must be CK's set
    NAME. Foil is 'true'/'false'. Rows with quantity <= 0 are skipped.

    `items` is an iterable of mappings with keys: ck_name/card_name,
    ck_edition/set_code, is_foil, qty (or qty_picked).
    """
    import csv
    from io import StringIO

    out = StringIO()
    writer = csv.writer(out)
    for it in items:
        qty = it.get('qty')
        if qty is None:
            qty = it.get('qty_picked')
        qty = int(qty or 0)
        if qty <= 0:
            continue
        title = it.get('ck_name') or it.get('card_name') or ''
        edition = it.get('ck_edition') or it.get('set_code') or ''
        foil = 'true' if (it.get('is_foil') in (1, True, '1', 'true')) else 'false'
        writer.writerow([title, edition, foil, qty])
    return out.getvalue()

import sqlite3

from app.cardkingdom import normalize_rows
from app.buylist import compute_report, finish_to_foil, build_ck_sell_csv


def _conn():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(
        '''
        CREATE TABLE ck_buylist (
          scryfall_id TEXT NOT NULL, is_foil INTEGER NOT NULL,
          name TEXT, edition TEXT, sku TEXT, url TEXT,
          price_buy REAL NOT NULL, qty_buying INTEGER NOT NULL,
          PRIMARY KEY (scryfall_id, is_foil)
        );
        CREATE TABLE manapool_inventory (
          inventory_id TEXT PRIMARY KEY, scryfall_id TEXT, tcgplayer_sku INTEGER,
          name TEXT, set_code TEXT, collector_number TEXT,
          condition_id TEXT, finish_id TEXT, language_id TEXT,
          price_cents INTEGER, quantity INTEGER, fetched_at TEXT
        );
        '''
    )
    return conn


def test_finish_to_foil():
    assert finish_to_foil('FO') == 1
    assert finish_to_foil('EF') == 1
    assert finish_to_foil('NF') == 0
    assert finish_to_foil(None) == 0


def test_normalize_rows_dedup_and_types():
    data = [
        {'scryfall_id': 'a', 'is_foil': 'false', 'price_buy': '1.50', 'qty_buying': '3', 'name': 'X'},
        {'scryfall_id': 'a', 'is_foil': 'false', 'price_buy': '2.00', 'qty_buying': '1', 'name': 'X'},  # higher -> wins
        {'scryfall_id': 'a', 'is_foil': 'true', 'price_buy': '5.00', 'qty_buying': '2', 'name': 'X'},
        {'scryfall_id': 'b', 'is_foil': 'false', 'price_buy': '0', 'qty_buying': '0'},  # dropped (price 0)
        {'scryfall_id': '', 'is_foil': 'false', 'price_buy': '9'},  # dropped (no id)
    ]
    rows = {(r['scryfall_id'], r['is_foil']): r for r in normalize_rows(data)}
    assert rows[('a', 0)]['price_buy'] == 2.00
    assert rows[('a', 0)]['qty_buying'] == 1
    assert rows[('a', 1)]['price_buy'] == 5.00
    assert ('b', 0) not in rows
    assert len(rows) == 2


def test_compute_report_ratio_value_and_threshold():
    conn = _conn()
    conn.execute("INSERT INTO ck_buylist VALUES ('a',0,'X','S','sku','u',8.0,5)")
    conn.execute("INSERT INTO ck_buylist VALUES ('b',1,'Y','S','sku','u',2.0,1)")
    # non-foil card, listed at $10, NM, have 3
    conn.execute("INSERT INTO manapool_inventory VALUES ('i1','a',null,'X','s','1','NM','NF','EN',1000,3,'t')")
    # foil card, listed at $5, LP, have 4 (CK only wants 1)
    conn.execute("INSERT INTO manapool_inventory VALUES ('i2','b',null,'Y','s','2','LP','FO','EN',500,4,'t')")
    conn.commit()

    rows = compute_report(conn, min_ratio=0.75, sort_by='value')
    by_id = {r['inventory_id']: r for r in rows}

    a = by_id['i1']
    assert a['ratio'] == 0.8           # 8 / 10
    assert a['meets'] is True          # 0.8 >= 0.75
    assert a['sell_qty'] == 3          # min(have 3, buying 5)
    assert a['value'] == 24.0          # 8 * 3
    assert a['is_nm'] is True

    b = by_id['i2']
    assert b['ratio'] == 0.4           # 2 / 5
    assert b['meets'] is False
    assert b['sell_qty'] == 1          # min(have 4, buying 1)
    assert b['value'] == 2.0
    assert b['is_nm'] is False         # LP -> flagged non-NM
    assert b['is_foil'] == 1

    # default sort is by value desc
    assert rows[0]['inventory_id'] == 'i1'


def test_compute_report_excludes_zero_quantity():
    conn = _conn()
    conn.execute("INSERT INTO ck_buylist VALUES ('a',0,'Have','S','sku','u',5.0,9)")
    conn.execute("INSERT INTO ck_buylist VALUES ('b',0,'OutOfStock','S','sku','u',9.0,9)")
    conn.execute("INSERT INTO manapool_inventory VALUES ('i1','a',null,'Have','s','1','NM','NF','EN',500,2,'t')")
    conn.execute("INSERT INTO manapool_inventory VALUES ('i2','b',null,'OutOfStock','s','2','NM','NF','EN',900,0,'t')")
    conn.commit()
    rows = compute_report(conn)
    assert [r['inventory_id'] for r in rows] == ['i1']  # zero-quantity i2 excluded


def test_compute_report_min_price_filter():
    conn = _conn()
    conn.execute("INSERT INTO ck_buylist VALUES ('a',0,'Cheap','S','sku','u',0.25,5)")
    conn.execute("INSERT INTO ck_buylist VALUES ('b',0,'Pricey','S','sku','u',3.00,5)")
    conn.execute("INSERT INTO manapool_inventory VALUES ('i1','a',null,'Cheap','s','1','NM','NF','EN',100,2,'t')")
    conn.execute("INSERT INTO manapool_inventory VALUES ('i2','b',null,'Pricey','s','2','NM','NF','EN',400,2,'t')")
    conn.commit()
    # No price floor -> both
    assert len(compute_report(conn, min_price=0)) == 2
    # $1 floor drops the $0.25 buylist card
    rows = compute_report(conn, min_price=1.0)
    assert [r['inventory_id'] for r in rows] == ['i2']


def test_compute_report_only_buying_filter():
    conn = _conn()
    conn.execute("INSERT INTO ck_buylist VALUES ('a',0,'X','S','sku','u',8.0,0)")  # not buying
    conn.execute("INSERT INTO manapool_inventory VALUES ('i1','a',null,'X','s','1','NM','NF','EN',1000,3,'t')")
    conn.commit()
    assert compute_report(conn, only_buying=True) == []
    assert len(compute_report(conn, only_buying=False)) == 1


def test_build_ck_sell_csv_format():
    items = [
        {'ck_name': 'Wrath of God', 'ck_edition': 'Portal', 'is_foil': 0, 'qty': 10},
        {'ck_name': 'Entomb', 'ck_edition': 'Odyssey', 'is_foil': 1, 'qty': 4},
        {'ck_name': 'Skip Me', 'ck_edition': 'X', 'is_foil': 0, 'qty': 0},  # qty 0 dropped
        # falls back to card_name/set_code + qty_picked when ck_* / qty missing
        {'card_name': 'Sol Ring', 'set_code': 'cmm', 'is_foil': 0, 'qty_picked': 2},
    ]
    csv_text = build_ck_sell_csv(items)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert lines[0] == 'Wrath of God,Portal,false,10'
    assert lines[1] == 'Entomb,Odyssey,true,4'
    assert lines[2] == 'Sol Ring,cmm,false,2'
    assert len(lines) == 3  # zero-qty row skipped, no header row


def test_build_ck_sell_csv_quotes_commas():
    items = [{'ck_name': 'Fire // Ice', 'ck_edition': 'Apocalypse, Promo', 'is_foil': 0, 'qty': 1}]
    csv_text = build_ck_sell_csv(items).strip()
    # csv module quotes the edition containing a comma
    assert csv_text == 'Fire // Ice,"Apocalypse, Promo",false,1'


def test_compute_report_foil_must_match():
    conn = _conn()
    # CK only has a NON-foil buy price for this card
    conn.execute("INSERT INTO ck_buylist VALUES ('a',0,'X','S','sku','u',8.0,5)")
    # but the inventory copy is FOIL -> should NOT match the non-foil buy price
    conn.execute("INSERT INTO manapool_inventory VALUES ('i1','a',null,'X','s','1','NM','FO','EN',1000,3,'t')")
    conn.commit()
    assert compute_report(conn) == []

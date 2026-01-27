from app.db import get_conn
from datetime import datetime


def _utc_now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def main():
    with get_conn() as conn:
        conn.execute('INSERT INTO batches (name, status, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', ('Demo Batch', 'open', 'Local', _utc_now(), _utc_now()))
        batch_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
        items = [
            ('Magic', 'woe', 'The Goose Mother', '113', 2, 'NM', 'EN', 'Normal'),
            ('Magic', 'woe', 'Beseech the Mirror', '82', 1, 'NM', 'EN', 'Foil'),
            ('Pokemon', 'sv1', 'Miraidon ex', '81', 1, 'NM', 'EN', 'Normal'),
        ]
        for game, set_code, name, num, qty, cond, lang, printing in items:
            conn.execute(
                'INSERT INTO batch_items (batch_id, game, set_code, card_name, collector_number, qty_required, qty_picked, condition, language, printing, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)',
                (batch_id, game, set_code, name, num, qty, cond, lang, printing, _utc_now()),
            )
        conn.commit()


if __name__ == '__main__':
    main()
    print('Seeded demo batch')

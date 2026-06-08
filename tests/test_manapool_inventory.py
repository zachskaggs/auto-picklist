from app import manapool


def _make_fake_pager(total_items, report_total=True):
    """Return a fake _fetch_inventory_page over `total_items` synthetic items."""
    data = [{'id': f'i{i}'} for i in range(total_items)]

    def _fake(limit, offset):
        batch = data[offset:offset + limit]
        total = total_items if report_total else None
        return batch, total, None

    return data, _fake


def test_list_inventory_parallel_collects_all(monkeypatch):
    data, fake = _make_fake_pager(2350)  # 5 pages at limit 500
    monkeypatch.setattr(manapool, '_fetch_inventory_page', fake)
    items, err = manapool.list_inventory(limit=500)
    assert err is None
    assert sorted(i['id'] for i in items) == sorted(i['id'] for i in data)
    assert len(items) == 2350


def test_list_inventory_exact_multiple(monkeypatch):
    data, fake = _make_fake_pager(1000)  # exactly 2 full pages
    monkeypatch.setattr(manapool, '_fetch_inventory_page', fake)
    items, err = manapool.list_inventory(limit=500)
    assert err is None
    assert len(items) == 1000


def test_list_inventory_single_page(monkeypatch):
    data, fake = _make_fake_pager(120)
    monkeypatch.setattr(manapool, '_fetch_inventory_page', fake)
    items, err = manapool.list_inventory(limit=500)
    assert err is None
    assert len(items) == 120


def test_list_inventory_serial_fallback_no_total(monkeypatch):
    # API doesn't report a total -> must page serially until a short page.
    data, fake = _make_fake_pager(1300, report_total=False)
    monkeypatch.setattr(manapool, '_fetch_inventory_page', fake)
    items, err = manapool.list_inventory(limit=500)
    assert err is None
    assert len(items) == 1300


def test_list_inventory_propagates_error(monkeypatch):
    def _fake(limit, offset):
        if offset == 0:
            return [{'id': 'a'}], 1500, None
        return None, None, 'ManaPool error: 500'

    monkeypatch.setattr(manapool, '_fetch_inventory_page', _fake)
    items, err = manapool.list_inventory(limit=500)
    assert items is None
    assert 'ManaPool error' in err

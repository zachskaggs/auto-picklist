# Raspberry Pi Touchscreen Picklist App

Local-first touchscreen web app for picking TCG orders on a Raspberry Pi. It keeps batches in SQLite, shows big tap targets, generates picklists from ManaPool, and pulls card images from Scryfall with local caching.

## Tech stack
- **FastAPI + Jinja2 + HTMX + Alpine** for a lightweight UI that runs well on a Pi.
- **SQLite** for local storage.

## Docker (single-image, bundled SQLite)
This image includes the SQLite DB inside the container filesystem. Demo data is pre-seeded at build time.

Build:
```bash
docker build -t picklist:local .
```

Run:
```bash
docker run --rm -p 8000:8000 \
  -e SESSION_SECRET=change-me \
  -e SETTINGS_PIN=1234 \
  -e MANAPOOL_EMAIL=you@example.com \
  -e MANAPOOL_ACCESS_TOKEN=mpat_xxx \
  picklist:local
```

Note: If you want to reset the bundled DB, rebuild the image.

## Setup (Raspberry Pi)
1. Install Python 3.11+ and git.
2. Clone this repo and enter it.
3. Create a venv and install dependencies:
   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in values.
5. Initialize the database:
   ```bash
   python scripts/init_db.py
   ```
6. Seed demo data (optional):
   ```bash
   python scripts/seed_demo.py
   ```
7. Run the app:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
8. Open in the Pi browser and enable full-screen/kiosk.

### Kiosk mode suggestion (Chromium)
```bash
chromium-browser --kiosk --incognito http://localhost:8000
```

### Simple systemd service
Create `/etc/systemd/system/picklist.service`:
```
[Unit]
Description=Picklist App
After=network.target

[Service]
WorkingDirectory=/home/pi/auto-picklist
EnvironmentFile=/home/pi/auto-picklist/.env
ExecStart=/home/pi/auto-picklist/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable picklist
sudo systemctl start picklist
```

## Environment variables
- `DB_PATH`: SQLite path (default `data/app.db`)
- `SESSION_SECRET`: session signing secret
- `SETTINGS_PIN`: PIN for settings screen
- `BASIC_AUTH_USER` / `BASIC_AUTH_PASS`: optional HTTP Basic Auth for LAN
- `MANAPOOL_RECENT_MINUTES`: warn if a ManaPool batch was generated within this window (default 10)
- `MANAPOOL_MAX_WORKERS`: max concurrent ManaPool detail requests (default 4)

### ManaPool API (verified against OpenAPI)
Base URL: `https://manapool.com/api/v1`
Required headers:
- `X-ManaPool-Email`
- `X-ManaPool-Access-Token`

Endpoints used:
- `GET /seller/orders?is_fulfilled=false&limit=...&offset=...`
- `GET /seller/orders/{id}`

Item parsing:
- `order.items[].product.single.scryfall_id` is the Scryfall ID.
- If missing, the item is skipped and recorded as a warning.

## ManaPool Generate Picklist
From the **Open Batches** screen, tap **Generate Picklist from ManaPool (Unfulfilled)**. The app will:
1. Fetch all unfulfilled orders from ManaPool (pagination via `limit` + `offset`).
2. Fetch each order’s details.
3. Aggregate items by Scryfall ID and sum quantities.
4. Create a new local batch named: `ManaPool Unfulfilled - YYYY-MM-DD HH:MM`.
5. Populate card name, set code, and collector number via Scryfall (fallbacks to ManaPool product fields when needed).

A summary appears on screen with:
- orders scanned
- line items aggregated
- unique cards
- warnings/errors

## Troubleshooting
- **Invalid token / auth**: verify `MANAPOOL_EMAIL` and `MANAPOOL_ACCESS_TOKEN`.
- **No orders**: confirm there are unfulfilled orders in ManaPool or remove any filters.
- **Missing images**: Scryfall may be unreachable; picklist still works.
- **API errors**: the generator retries 429/5xx with backoff; see the last sync panel for errors.

## CSV import
Go to **Import** from the main screen or POST to `/import` with a CSV file.

Required columns:
- `batch_name`
- `game`
- `set_code`
- `card_name`
- `qty_required`

Optional columns:
- `collector_number`
- `condition`
- `language`
- `printing`

Example: `data/sample_import.csv`

## Manual batch creation
Use **New Batch** on the main screen, then add items from the batch page (**Add items**).

## Features
- Open batches list with counts and sources
- Picklist view sorted by game -> set code -> card name
- Pick/Undo with 5-second timer
- Missing flag with optional notes and export view
- Card images from Scryfall with local cache
- Multi-bin locations per set code
- Packing slip view
- Batch close with summary and missing export
- Audit log of pick/missing events

## Tests
```bash
pytest
```

## Minimal API/Route list
- `GET /` open batches
- `POST /api/batches/generate-from-manapool` generate ManaPool batch
- `GET /batch/new` / `POST /batch/new` create batch
- `GET /batch/{id}` picklist
- `GET /batch/{id}/items` list items (filters)
- `POST /batch/{id}/items` add item
- `POST /items/{id}/pick` pick item
- `POST /items/{id}/undo` undo pick
- `POST /items/{id}/missing` mark missing
- `POST /items/{id}/unmissing` clear missing
- `GET /batch/{id}/missing` missing view
- `GET /batch/{id}/missing.csv` export missing
- `GET /batch/{id}/packing-slip` packing slip
- `GET /batch/{id}/events` audit log
- `POST /batch/{id}/close` close batch
- `GET /batch/{id}/summary` close summary
- `GET /card/modal` image viewer modal
- `GET /cards/search` search cards by name
- `POST /items/{id}/link_scryfall` link a chosen card
- `GET /import` CSV import screen
- `POST /import` import CSV
- `GET /settings` settings (PIN gate)

## Notes
- Scryfall is used only for card lookups and images. If offline, the app keeps working; images show as unavailable.
- Images are cached on disk under `data/cache/images/`.


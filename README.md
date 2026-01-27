# Auto Picklist (Docker-First)

Local-first touchscreen picklist app for TCG orders. It generates batches from ManaPool, caches card data/images from Scryfall, and keeps all state in a bundled SQLite database inside the Docker image.

This repo is documented for Docker deployment only.

## Quick start (Docker)

1) Create a `.env` file (or edit the existing one):

```env
HOST_PORT=8000
SESSION_SECRET=change-me
SETTINGS_PIN=1234
MANAPOOL_EMAIL=you@example.com
MANAPOOL_ACCESS_TOKEN=mpat_xxx
# Optional:
# MANAPOOL_BASE_URL=https://manapool.com/api/v1
# MANAPOOL_RECENT_MINUTES=10
# MANAPOOL_MAX_WORKERS=4
# BASIC_AUTH_USER=
# BASIC_AUTH_PASS=
```

2) Build the image:

```bash
docker build -t picklist:local .
```

3) Run with Docker Compose (recommended):

```bash
docker compose up --build
```

4) Or run directly with Docker:

```bash
docker run --rm -p ${HOST_PORT:-8000}:8000 --env-file .env picklist:local
```

Open: http://localhost:8000

Notes:
- The SQLite DB is intentionally bundled inside the image.
- To reset data, rebuild the image.

## Portainer (Git stack)

Portainer Git stacks cannot read your local `.env` on disk. Use one of these:

Option A (recommended):
- Set variables in the **Environment variables** section of the stack UI.
- Use `stack.env.example` as a template.

Option B:
- Upload an `.env` file inside the stack UI (Portainer will use it for `${VAR}` substitution).

After setting variables, re-deploy the stack. Check `/health` for **ManaPool Configured: Yes**.

## How picklist generation works (ManaPool)

From the Open Batches screen, click **Generate Picklist from ManaPool (Unfulfilled)**.

The server will:
- Fetch unfulfilled orders from ManaPool.
- Fetch each order’s details.
- Aggregate all items by Scryfall ID and sum quantities.
- Enrich set/name/collector number from Scryfall.
- Create a new local batch named like: `ManaPool Unfulfilled - YYYY-MM-DD HH:MM`.

## Environment variables

Required:
- `MANAPOOL_EMAIL`
- `MANAPOOL_ACCESS_TOKEN`
- `SESSION_SECRET`

Common optional:
- `HOST_PORT` (host port for docker compose; default `8000`)
- `MANAPOOL_BASE_URL` (default `https://manapool.com/api/v1`)
- `MANAPOOL_RECENT_MINUTES` (warn on rapid re-generation; default `10`)
- `MANAPOOL_MAX_WORKERS` (detail fetch concurrency; default `4`)
- `BASIC_AUTH_USER` / `BASIC_AUTH_PASS` (LAN protection)

## Health check

A simple health view is available at:
- `/health`

It shows DB path, ManaPool configuration status, cached order counts, last sync status, and ManaPool order numbers by batch (when available).

## Troubleshooting

- ManaPool auth errors: verify `MANAPOOL_EMAIL` and `MANAPOOL_ACCESS_TOKEN`.
- No orders found: confirm there are unfulfilled orders in ManaPool.
- Missing images: Scryfall may be unreachable; picking still works.
- Weird UI behavior after updates: rebuild the image and hard refresh the browser (Ctrl+F5).

## Tests (optional, local dev)

```bash
pytest
```

## Minimal route list

Primary:
- `GET /` open batches
- `POST /api/batches/generate-from-manapool` generate a batch
- `GET /batch/{id}` picklist
- `GET /batch/{id}/items` list items with filters
- `POST /items/{id}/pick` pick
- `POST /items/{id}/undo` undo pick
- `POST /items/{id}/missing` mark missing
- `POST /items/{id}/unmissing` clear missing
- `GET /batch/{id}/missing` missing view
- `GET /batch/{id}/missing.csv` missing export
- `GET /batch/{id}/events` audit log
- `POST /batch/{id}/close` close batch
- `GET /batch/{id}/summary` close summary
- `GET /card/modal` card image modal
- `GET /cards/search` search alternatives
- `POST /items/{id}/link_scryfall` link chosen card
- `GET /import` CSV import UI
- `POST /import` CSV import
- `GET /health` health view

## Security notes

- Secrets live in `.env` and should not be committed.
- If you expose this on your LAN, consider setting `BASIC_AUTH_USER` and `BASIC_AUTH_PASS`.

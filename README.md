# mutual-funds-personal

A local, private mutual-fund portfolio tracker for Indian investors. Pulls your CAS (Consolidated Account Statement) from CAMS by email, parses it, and serves a Streamlit dashboard with holdings, gains, allocation, and tax info — entirely on your machine, no data ever leaves.

## What you get

- Auto-fetch the latest encrypted CAS PDF from your Gmail
- Holdings, current value, and unrealised gains using live NAV
- Realised gain breakdown (short-term / long-term)
- Allocation donuts by AMC, category, and fund
- Per-folio holder names, scheme detail panels
- Multi-account support (e.g. you + spouse)

## Setup

Requires Python 3.10+, a Gmail account, and a Gmail [App Password](https://myaccount.google.com/apppasswords).

```bash
git clone https://github.com/<you>/mutual-funds-personal.git
cd mutual-funds-personal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium       # ~150 MB; needed for the CAS request flow
cp config.example.yaml config.yaml
# edit config.yaml — set admin_email to your Gmail
```

## Running

Two processes — the FastAPI **auth gateway** in front of the Streamlit **dashboard**:

```bash
# terminal 1: dashboard (only reachable through the gateway)
streamlit run ui/app.py

# terminal 2: auth gateway (bind 0.0.0.0 if you want LAN access)
uvicorn auth_server.main:app --host 0.0.0.0 --port 8000
```

Port + XSRF/CORS settings are baked into `.streamlit/config.toml` so the run command stays simple.

Open **http://localhost:8000** in your browser. On first launch you'll be guided through admin signup → Gmail App Password + PDF password setup → first CAS fetch.

> Note: you never visit `:8501` directly. The dashboard reads its session from a header that the gateway injects on every proxied request; direct access shows an error.

## How it works

| Layer | What it does |
|---|---|
| `auth_server/`           | FastAPI auth gateway: login, signup, setup, migration. HTTP-only signed cookies. Reverse-proxies authenticated requests to Streamlit |
| `ui/app.py`              | Streamlit dashboard — no auth UI, reads user identity from the gateway's signed header |
| `ingest/cams_request.py` | Fills the CAMS Mailback form via Playwright |
| `ingest/gmail_fetch.py`  | Watches Gmail for the encrypted CAS reply |
| `analytics/`             | Parses the PDF, computes positions, NAV, gains, tax buckets |

All artefacts (PDFs, parsed data, SQLite cache) stay in `data/` and `debug/` — both gitignored.

## License

Copyright © 2026 Kesha Shah. **All rights reserved.** See [LICENSE](LICENSE).

This source is publicly visible for inspection and personal use only. You may clone this repository and run the application for your own personal, non-commercial use. You may **not** copy, modify, redistribute, fork, or use any portion of this code in another project or product without prior written permission. This code may not be used to train AI/ML models.

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
cp config.example.yaml config.yaml
# edit config.yaml — fill in your email, app password, and a PDF password of your choice
streamlit run ui/app.py
```

Open http://localhost:8501. The first run requests a CAS via the CAMS Mailback form, waits for the email, decrypts the PDF, and builds your portfolio.

## How it works

| Layer | What it does |
|---|---|
| `ingest/cams_request.py` | Fills the CAMS Mailback form via Playwright |
| `ingest/gmail_fetch.py`  | Watches Gmail for the encrypted CAS reply |
| `analytics/`             | Parses the PDF, computes positions, NAV, gains, tax buckets |
| `ui/app.py`              | Streamlit dashboard |

All artefacts (PDFs, parsed data, SQLite cache) stay in `data/` and `debug/` — both gitignored.

## License

[AGPL-3.0](LICENSE). You may read, run, modify, and self-host this code. If you redistribute it or run a modified version as a network service, your version must also be released under AGPL-3.0.

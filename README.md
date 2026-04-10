# Capitol_Trades_API

A lightweight Python API for exposing recent Capitol Trades disclosures as JSON.

## Available endpoints
- `GET /health` — service health check
- `GET /trades?page=1&limit=20` — normalized recent trade disclosures
- `GET /politicians?pages=2&limit=10` — summary of recent politician activity
- `GET /sectors?pages=2&limit=10` — simple sector breakdown inferred from recent trades
- `GET /news?page=1&limit=10` — headline-style feed generated from the latest disclosures

## Run locally
```bash
python run.py
```

Then open `http://127.0.0.1:8000/health` or another route above.


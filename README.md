# TorqueTrack Diesel — backend (Django + DRF)

Strangler-migration target for the existing Next.js app (frozen, untouched at
the repo root). See `config/settings/{base,dev,prod}.py` for environment
wiring.

`apps/` holds 11 working apps covering the catalog, cart, checkout, quotes,
shipping, tax, VIN, fitment, customers, auth and backoffice, plus
`integrations`, still an empty placeholder. The customer-portal API and
production hardening are not done yet, so this is not a drop-in replacement
for the Next.js app.

## Local dev (Docker)

```bash
docker compose up --build
```

Django serves on `http://localhost:8010`, Postgres on `localhost:5435`.

## Local dev (virtualenv, no Docker)

```bash
python -m venv .venv
.venv/Scripts/activate   # or: source .venv/bin/activate
pip install -r requirements/dev.txt
pytest
```

## Tests

```bash
pytest
```

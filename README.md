# TorqueTrack Diesel — backend (Django + DRF)

Strangler-migration target for the existing Next.js app (frozen, untouched at
the repo root). See `docs/migration/` for the full migration design and
`config/settings/{base,dev,prod}.py` for environment wiring. `apps/` currently
holds empty app skeletons (Phase 1); models/views/serializers land per app in
later phases.

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

# CHANGELOG

## Unreleased

### Added
- Project documentation: `AGENTS.md`, `README_AI.md`, `docs/`
- Modular Python package `gamenet/` (server, shared, placeholders for operator/client)
- FastAPI server with health endpoint
- SQLite migration system and migration `001_initial.sql`
- Customer create/search/get API with bcrypt PIN hashing
- Test suite (`tests/test_health.py`, `tests/test_customers.py`)

### Fixed
- Replaced unmaintained `passlib` with direct `bcrypt` for PIN/password hashing (passlib 1.7.4 crashes with bcrypt >= 4.1, which broke customer creation with HTTP 500)
- Pinned all dependencies in `requirements.txt` (`==`) so fresh installs are reproducible
- Replaced deprecated `@app.on_event("startup")` with `lifespan` handler
- Added `tests/test_security.py` (hash roundtrip, unicode/long PINs, invalid hashes, salting)

No production functionality should be considered complete solely because these documents exist.
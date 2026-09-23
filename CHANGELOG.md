# CHANGELOG

## Unreleased

### Added
- Project documentation: `AGENTS.md`, `README_AI.md`, `docs/`
- Modular Python package `gamenet/` (server, shared, placeholders for operator/client)
- FastAPI server with health endpoint
- SQLite migration system and migration `001_initial.sql`
- Customer create/search/get API with bcrypt PIN hashing
- Test suite (`tests/test_health.py`, `tests/test_customers.py`)
- Operator authentication: migration `002_auth.sql` (permissions, role_permissions, auth_sessions, login lockout columns) with seeded roles/permissions
- Auth API (`/auth/login`, `/auth/logout`, `/auth/me`) with opaque revocable tokens, brute-force lockout, and login auditing
- Server-side permission enforcement (`require_permission`) — customer endpoints now require `customer.create`/`customer.view`
- Append-only audit writer (`audit_service.log_audit`) wired into auth + customer creation
- Admin CLI: `python -m gamenet.server.cli create-admin`
- Auth test suite (`tests/test_auth.py`, 10 tests)
- Request-ID idempotency: migration `003_idempotency.sql`, `idempotency.idempotent_call`, `X-Request-ID` support on customer creation (replay returns stored response, payload change rejected)
- Atomic transaction helper `db.run_in_transaction` + SQLite `busy_timeout` for concurrent writers

### Fixed
- Replaced unmaintained `passlib` with direct `bcrypt` for PIN/password hashing (passlib 1.7.4 crashes with bcrypt >= 4.1, which broke customer creation with HTTP 500)
- Pinned all dependencies in `requirements.txt` (`==`) so fresh installs are reproducible
- Replaced deprecated `@app.on_event("startup")` with `lifespan` handler
- Added `tests/test_security.py` (hash roundtrip, unicode/long PINs, invalid hashes, salting)

No production functionality should be considered complete solely because these documents exist.
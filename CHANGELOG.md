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
- Price engine: migration `004_pricing.sql`, FLAT/PER_HOUR/MULTIPLIER rules with scope/window/PC-class matching, quote API with price snapshots, settings API (admin-only writes, audited)
- Sales + payments: migration `005_sales_payments.sql` (sales/items/payments/transactions/events/sequences), traceable SALE-/PAY- IDs, server-priced TIME items, discounts with operator limits, payment state machine enforced server-side, provider interface (manual + deterministic mock), UNKNOWN handling with reconcile + unknown-queue, idempotent sale/payment/confirm endpoints
- Credit + VIP + packages: migration `006_ledgers.sql`, append-only balance/entitlement ledgers, packages/VIP catalog APIs, activation on sale confirm (payment first), BALANCE payments, earliest-expiry-first consumption, VIP renewal modes + lazy lifecycle refresh, balance adjustments with permission + audit
- Sessions + PCs: migration `007_sessions.sql` (sessions/events/consumptions/PC history, partial unique indexes for one-active rules, `session.operate` permission), full lifecycle (create/authorize/start/pause/resume/end/cancel/transfer) with server-time accounting, timeline API, PC register/maintenance/retire + device secret rotation
- Ops + integrity: migration `008_ops.sql`, tamper-evident audit hash chain + verify API, audit reads, safe mode (middleware blocks mutations, auto-enabled on integrity failure), reconciliation engine (7 check groups) with run history, startup recovery checks
- Agent channel core: migration `009_comms.sql` (agent tokens, command queue), device auth with revocable tokens, heartbeat with piggybacked commands + lease grant, in-memory presence registry with periodic DB flush, ACK flow, command expiry, operator queue/list APIs (remote.execute), agent channel stays live in safe mode
- WebSocket gateway: agent socket endpoint with query-token auth, HELLO/HEARTBEAT/ACK/PING protocol, instant command push on queue (offline PCs fall back to heartbeat pickup), presence snapshot API with socket state
- Lease + reconnect: session lifecycle emits LOCK/UNLOCK commands (start/pause/resume/end/cancel/transfer), lease monitor auto-pauses expired sessions with LINK_LOST + LOCK (idempotent per outage, daemon thread in lifespan), heartbeat carries live-session sync for reconnecting agents, manual resume flow delivers UNLOCK
- Client agent: stdlib-only headless agent (config, REST transport, OS platform layer with Windows/POSIX/Mock, heartbeat loop with backoff + re-auth, command dispatch with pending-ACK retry queue, crash-safe state.json, boot-locked with unlock-only-via-command rule, session-sync reconciliation)
- Shifts + cash drawer: migration `010_shifts.sql` (one open shift enforced, cash movements, sale.shift_id, `shift.manage` permission), drawer math (float + cash + IN − OUT), variance-requires-note close, audited open/close/movements
- Refunds: migration `011_refunds.sql`, full/partial refunds (CASH via open-shift drawer OUT movement, BALANCE via credit-back), proportional TIME/PACKAGE revoke of remaining-only, strict RECHARGE clawback, VIP cancel on full refund with chain promotion, `sales.refund` guarded, sale detail carries refunds + refunded_total
- Inventory: migration `012_inventory.sql` (items + append-only stock ledger), receive/adjust/archive flows, FOOD sale items priced from catalog with draft-time and confirm-time stock gates, stock decremented at activation, no auto-restock on food refunds, stock-vs-ledger reconciliation check
- Capacity: migration `013_capacity.sql` (reservations + queue + session groups), reservation booking with overlap detection + cancel/no-show/seat-into-session, FIFO queue with priority + opt-in VIP boost + expiry, group sessions with shared end-all (separate payments preserved)
- Quick wins: customer PIN login with lockout + token sessions (`/customers/login|me|logout`), session extend markers (Spec 77), one-tap quick-customer/quick-sale with idempotency, stdlib operator shell (`python -m gamenet.operator_app`)
- Reports: sales summary (gross/discounts/refunds/net, by method + operator), shift report, per-PC utilization, inventory valuation + low stock, audited CSV export (sales/shifts/sessions/inventory)
- Alerts: rule evaluation (server disk, PC offline, stuck shifts, login spikes, low stock) with dedupe + auto-resolve, ack/resolve inbox, Telegram notifications for new warnings
- PC health: heartbeat samples incl. temperature stored in `pc_health` history, per-PC health endpoint, admin diagnostics bundle (disk/db/fleet/sessions/alerts); remote commands verified end-to-end (queue + WS/REST delivery + agent execution + ACK)
- Backup/restore: online SQLite backups with SHA-256 manifests, verify + guarded restore (confirmation echo, integrity gate, safety copy), systemd unit, install script, API-driven backup script

### Fixed
- Replaced unmaintained `passlib` with direct `bcrypt` for PIN/password hashing (passlib 1.7.4 crashes with bcrypt >= 4.1, which broke customer creation with HTTP 500)
- Pinned all dependencies in `requirements.txt` (`==`) so fresh installs are reproducible
- Replaced deprecated `@app.on_event("startup")` with `lifespan` handler
- Added `tests/test_security.py` (hash roundtrip, unicode/long PINs, invalid hashes, salting)

No production functionality should be considered complete solely because these documents exist.
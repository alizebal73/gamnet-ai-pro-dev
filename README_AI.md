# GameNet Pro — AI Developer Guide

## What This Project Is

A LAN-based game-net management system with three logical applications:

| Component | Role |
|-----------|------|
| **GameNet Server** | Source of truth — Windows service, FastAPI, SQLite |
| **Client Agent + UI** | One per gaming PC — heartbeat, lock, session display |
| **Operator App** | Staff sales, customers, shift, cash |

## Core Data Model

```text
CUSTOMER → ENTITLEMENT/CREDIT → SESSION → PC
CUSTOMER → SALE → PAYMENT → ENTITLEMENT
```

## Current Phase

**Phase 0 + Phase 1 (in progress):** repository foundation, server scaffold, database migrations, customer API.

## Run Server (development)

```powershell
cd "E:\نرمافزار ai گیمنت\GameNetPro"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m gamenet.server.main
```

Health check: `GET http://127.0.0.1:8765/api/v1/health`

## First Run — Create Owner Account

```powershell
copy .env.example .env
python -m gamenet.server.cli create-admin --username admin
python -m gamenet.server.main
```

Login: `POST /api/v1/auth/login` with `{"username": "...", "password": "..."}`.
Use the returned token as `Authorization: Bearer <token>` on protected routes.

## Implementation Rules

- Business logic in `gamenet/server/services/`, not in API routes.
- All money as **integer** minor units (no float).
- All timestamps stored as **UTC ISO-8601**.
- Passwords/PINs: **hashed** (bcrypt), never Fernet-as-password-storage.
- Every schema change: new file in `database/migrations/`.

## Test

```powershell
pytest tests/ -v
```

## Do Not

- Let clients open SQLite directly.
- Auto-resume sessions after reconnect (unless explicitly configured).
- Hard-code prices — use Price Engine / settings.
- Delete financial records — use status flags.

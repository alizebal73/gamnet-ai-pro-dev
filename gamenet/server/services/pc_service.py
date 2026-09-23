import sqlite3

from gamenet.server.repositories.pc_repository import PcRepository
from gamenet.server.repositories.session_repository import SessionRepository
from gamenet.server.security.tokens import generate_token, hash_token
from gamenet.server.services.errors import InvalidState, NotFound

# Operator/admin-driven targets (heartbeat-driven ONLINE/BUSY/PAUSED arrive
# with P2; they are never set manually).
MANUAL_PC_STATUSES = {"OFFLINE", "MAINTENANCE", "RETIRED"}


class PcService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._pcs = PcRepository(conn)
        self._sessions = SessionRepository(conn)

    def register(self, *, device_code: str, display_name: str) -> dict:
        device_code = (device_code or "").strip()
        display_name = (display_name or "").strip()
        if not device_code:
            raise ValueError("device_code is required")
        if not display_name:
            raise ValueError("display_name is required")
        if self._pcs.get_by_device_code(device_code) is not None:
            raise InvalidState(f"device_code '{device_code}' already registered")
        return self._pcs.create(device_code=device_code, display_name=display_name)

    def set_status(
        self,
        pc_id: str,
        status: str,
        *,
        reason: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        pc = self._pcs.get(pc_id)
        if pc is None:
            raise NotFound("PC not found")
        if status not in MANUAL_PC_STATUSES:
            raise ValueError(
                f"status '{status}' is heartbeat-driven; manual targets: "
                f"{sorted(MANUAL_PC_STATUSES)}"
            )
        if pc["status"] == "RETIRED":
            raise InvalidState("Retired PCs cannot change status")
        if status in ("RETIRED", "MAINTENANCE"):
            busy = self._sessions.active_for_pc(pc_id)
            if busy is not None:
                raise InvalidState(
                    f"PC has an active session {busy['id']}; end or transfer it first"
                )
        updated = self._pcs.set_status(pc_id, status)
        self._pcs.add_history(
            pc_id=pc_id, from_status=pc["status"], to_status=status,
            reason=reason, actor_user_id=actor_user_id,
        )
        return updated

    def rename(self, pc_id: str, display_name: str) -> dict:
        pc = self._pcs.get(pc_id)
        if pc is None:
            raise NotFound("PC not found")
        if not (display_name or "").strip():
            raise ValueError("display_name is required")
        return self._pcs.set_display_name(pc_id, display_name.strip())

    def rotate_secret(self, pc_id: str) -> dict:
        """Issue a new device secret (shown once; only its hash is stored)."""
        pc = self._pcs.get(pc_id)
        if pc is None:
            raise NotFound("PC not found")
        secret = generate_token()
        self._pcs.set_device_secret(pc_id, hash_token(secret))
        return {"pc_id": pc_id, "secret": secret}

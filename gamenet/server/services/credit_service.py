"""Gaming credit (entitlements + consumption ledger).

Master Spec 25-39, 291-294:
- Credit belongs to the customer, never to a PC.
- Consumption is ledger-based and prioritized (earliest expiry first).
- VIP has its own PENDING -> ACTIVE -> EXPIRED lifecycle with renewal
  rules (Spec 114); expiry/activation refresh is lazy (no worker yet).
"""

import sqlite3
from datetime import UTC, datetime, timedelta

from gamenet.server.db import to_utc_iso, utc_now_iso
from gamenet.server.repositories.customer_repository import CustomerRepository
from gamenet.server.repositories.entitlement_repository import EntitlementRepository
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.shared.enums import EntitlementKind, EntitlementStatus

TIME_KINDS = [
    EntitlementKind.TIME_CREDIT.value,
    EntitlementKind.PACKAGE_CREDIT.value,
]


class CreditService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._ents = EntitlementRepository(conn)
        self._customers = CustomerRepository(conn)
        self._settings = SettingsRepository(conn)

    # ---- grants ----

    def grant_time_credit(
        self,
        *,
        customer_id: str,
        seconds: int,
        sale_id: str,
        sale_item_id: str,
        validity_days: int | None = None,
        kind: str = EntitlementKind.TIME_CREDIT.value,
        ref_id: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        now = utc_now_iso()
        expires_at = None
        if validity_days:
            expires_at = to_utc_iso(
                datetime.now(UTC) + timedelta(days=validity_days)
            )
        ent = self._ents.create(
            entitlement_id=next_number(self._conn, name="ent", prefix="ENT"),
            customer_id=customer_id, kind=kind,
            status=EntitlementStatus.ACTIVE.value, granted_sec=seconds,
            starts_at=now, expires_at=expires_at, sale_id=sale_id,
            sale_item_id=sale_item_id, ref_id=ref_id,
        )
        self._ents.append_ledger(
            entitlement_id=ent["id"], delta_sec=seconds, kind="GRANT",
            ref_type="sale_item", ref_id=sale_item_id, created_by=created_by,
        )
        return self._ents.get(ent["id"])

    def grant_vip(
        self,
        *,
        customer_id: str,
        duration_days: int,
        discount_pct: int,
        sale_id: str,
        sale_item_id: str,
        ref_id: str | None = None,
    ) -> dict:
        self.refresh_vip_states(customer_id)
        now_dt = datetime.now(UTC)
        mode = self._settings.get("vip_renewal_mode", "AFTER_EXPIRY")
        active = self.active_vip(customer_id)
        if active is None:
            starts_at = to_utc_iso(now_dt)
            status = EntitlementStatus.ACTIVE.value
        elif mode == "NOW":
            self._ents.set_status(active["id"], EntitlementStatus.CANCELLED.value)
            starts_at = to_utc_iso(now_dt)
            status = EntitlementStatus.ACTIVE.value
        else:  # AFTER_EXPIRY: queue behind the current VIP.
            starts_at = active["expires_at"]
            status = EntitlementStatus.PENDING.value
        starts_dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        ent = self._ents.create(
            entitlement_id=next_number(self._conn, name="ent", prefix="ENT"),
            customer_id=customer_id, kind=EntitlementKind.VIP.value,
            status=status, starts_at=starts_at,
            expires_at=to_utc_iso(starts_dt + timedelta(days=duration_days)),
            discount_pct=discount_pct, sale_id=sale_id,
            sale_item_id=sale_item_id, ref_id=ref_id,
        )
        return self._ents.get(ent["id"])

    # ---- consumption (used by sessions in P1-6) ----

    def remaining_sec(self, customer_id: str) -> int:
        now = utc_now_iso()
        total = 0
        for ent in self._ents.list_for_customer(
            customer_id, kinds=TIME_KINDS,
            statuses=[EntitlementStatus.ACTIVE.value],
        ):
            if ent["expires_at"] and ent["expires_at"] <= now:
                continue
            total += max(0, (ent["granted_sec"] or 0) - (ent["consumed_sec"] or 0))
        return total

    def consume(
        self,
        *,
        customer_id: str,
        seconds: int,
        ref_type: str,
        ref_id: str,
    ) -> list[dict]:
        """Consume seconds across entitlements (earliest expiry first).

        Returns per-entitlement breakdown. Raises InvalidState when credit
        is insufficient (no negative credit, Spec 165).
        """
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        now = utc_now_iso()
        candidates = [
            e for e in self._ents.list_for_customer(
                customer_id, kinds=TIME_KINDS,
                statuses=[EntitlementStatus.ACTIVE.value],
            )
            if not (e["expires_at"] and e["expires_at"] <= now)
            and (e["granted_sec"] or 0) - (e["consumed_sec"] or 0) > 0
        ]
        # Earliest expiry first; never-expiring last; then oldest grant.
        candidates.sort(key=lambda e: (
            e["expires_at"] or "9999", e["created_at"],
        ))
        available = sum(
            (e["granted_sec"] or 0) - (e["consumed_sec"] or 0) for e in candidates
        )
        if available < seconds:
            raise InvalidState(
                f"Insufficient credit ({available}s < {seconds}s)"
            )
        breakdown = []
        left = seconds
        for ent in candidates:
            if left <= 0:
                break
            ent_left = (ent["granted_sec"] or 0) - (ent["consumed_sec"] or 0)
            take = min(ent_left, left)
            updated = self._ents.add_consumed(ent["id"], take)
            self._ents.append_ledger(
                entitlement_id=ent["id"], delta_sec=-take, kind="CONSUME",
                ref_type=ref_type, ref_id=ref_id,
            )
            breakdown.append({
                "entitlement_id": ent["id"],
                "consumed_sec": take,
                "remaining_sec": (updated["granted_sec"] or 0) - (updated["consumed_sec"] or 0),
            })
            left -= take
        return breakdown

    # ---- VIP lifecycle ----

    def active_vip(self, customer_id: str) -> dict | None:
        vips = self._ents.list_for_customer(
            customer_id, kinds=[EntitlementKind.VIP.value],
            statuses=[EntitlementStatus.ACTIVE.value],
        )
        return vips[0] if vips else None

    def refresh_vip_states(self, customer_id: str) -> dict:
        """Expire overdue VIPs and activate due queued ones. Idempotent."""
        now = utc_now_iso()
        expired, activated = [], []
        for vip in self._ents.list_for_customer(
            customer_id, kinds=[EntitlementKind.VIP.value],
            statuses=[EntitlementStatus.ACTIVE.value],
        ):
            if vip["expires_at"] and vip["expires_at"] <= now:
                self._ents.set_status(vip["id"], EntitlementStatus.EXPIRED.value)
                expired.append(vip["id"])
        if self.active_vip(customer_id) is None:
            queued = sorted(
                self._ents.list_for_customer(
                    customer_id, kinds=[EntitlementKind.VIP.value],
                    statuses=[EntitlementStatus.PENDING.value],
                ),
                key=lambda v: v["starts_at"],
            )
            for vip in queued:
                if vip["starts_at"] <= now and (
                    not vip["expires_at"] or vip["expires_at"] > now
                ):
                    self._ents.set_status(vip["id"], EntitlementStatus.ACTIVE.value)
                    activated.append(vip["id"])
                    break
        return {"expired": expired, "activated": activated}

    # ---- reads ----

    def credit_summary(self, customer_id: str) -> dict:
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFound("Customer not found")
        now = utc_now_iso()
        ents = self._ents.list_for_customer(customer_id)
        items = []
        for ent in ents:
            effective = ent["status"]
            if (
                effective == EntitlementStatus.ACTIVE.value
                and ent["expires_at"] and ent["expires_at"] <= now
            ):
                effective = EntitlementStatus.EXPIRED.value  # derived, not stored
            granted = ent["granted_sec"] or 0
            consumed = ent["consumed_sec"] or 0
            items.append({
                **ent,
                "effective_status": effective,
                "remaining_sec": max(0, granted - consumed)
                if ent["kind"] in TIME_KINDS else None,
            })
        return {
            "customer_id": customer_id,
            "total_remaining_sec": self.remaining_sec(customer_id),
            "active_vip": self.active_vip(customer_id),
            "entitlements": items,
        }

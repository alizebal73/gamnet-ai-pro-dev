"""Price engine (Master Spec 70-71).

Rules (lower ``priority`` wins):
- FLAT: fixed price for an exact duration (bundles like 30min / 2h / 4h).
- PER_HOUR: hourly rate, pro-rata per second, rounded UP to minor units.
- MULTIPLIER: single best-priority percentage applied last (off-peak,
  weekend, events). No stacking.

Matchers: scope (weekday/weekend from server-local date), time window in
server-local minutes (overnight windows supported), pc_class (NULL = any).

Money is always integer minor units (Master Spec 150). Every quote returns
a snapshot dict capturing inputs + applied rules, so historical sales never
change when prices change (Master Spec 71).
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from gamenet.server.db import utc_now_iso
from gamenet.server.repositories.pricing_repository import PricingRepository
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.shared.enums import PricingKind, PricingScope


@dataclass
class QuoteResult:
    total: int
    currency_unit: str
    base_total: int
    base_rule_id: str | None
    multiplier_pct: int | None
    multiplier_rule_id: str | None
    snapshot: dict[str, Any] = field(default_factory=dict)


class PricingService:
    def __init__(self, conn: sqlite3.Connection):
        self._rules = PricingRepository(conn)
        self._settings = SettingsRepository(conn)

    # ---- settings helpers ----

    def weekend_days(self) -> set[int]:
        raw = self._settings.get("weekend_days", "3,4") or ""
        days = set()
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit() and int(part) <= 6:
                days.add(int(part))
        return days

    def currency_unit(self) -> str:
        return self._settings.get("base_currency_unit", "RIAL") or "RIAL"

    def fallback_hourly_rate(self) -> int:
        return self._settings.get_int("price_per_hour", 0)

    # ---- quote ----

    def quote(
        self,
        *,
        duration_sec: int,
        pc_class: str | None = None,
        at: datetime | None = None,
    ) -> QuoteResult:
        if duration_sec <= 0:
            raise ValueError("duration_sec must be positive")

        local = self._as_local(at)
        scope = (
            PricingScope.WEEKEND.value
            if local.weekday() in self.weekend_days()
            else PricingScope.WEEKDAY.value
        )
        minute = local.hour * 60 + local.minute

        rules = self._rules.list_rules(active_only=True)

        flat = self._pick(
            [r for r in rules if r["kind"] == PricingKind.FLAT.value
             and r["duration_sec"] == duration_sec],
            scope, minute, pc_class,
        )
        if flat is not None:
            base_total = int(flat["price"])
            base_rule_id: str | None = flat["id"]
            base_detail = {"kind": "FLAT", "price": int(flat["price"])}
        else:
            hourly = self._pick(
                [r for r in rules if r["kind"] == PricingKind.PER_HOUR.value],
                scope, minute, pc_class,
            )
            if hourly is not None:
                rate = int(hourly["price"])
                base_rule_id = hourly["id"]
            else:
                rate = self.fallback_hourly_rate()
                base_rule_id = None
            base_total = (rate * duration_sec + 3599) // 3600
            base_detail = {"kind": "PER_HOUR", "rate_per_hour": rate}

        mult = self._pick(
            [r for r in rules if r["kind"] == PricingKind.MULTIPLIER.value],
            scope, minute, pc_class,
        )
        if mult is not None:
            factor = int(mult["factor_pct"])
            total = (base_total * factor + 50) // 100
            multiplier_rule_id: str | None = mult["id"]
        else:
            factor = None
            total = base_total
            multiplier_rule_id = None

        snapshot = {
            "duration_sec": duration_sec,
            "pc_class": pc_class,
            "at_local": local.isoformat(timespec="minutes"),
            "scope": scope,
            "currency_unit": self.currency_unit(),
            "base": {**base_detail, "total": base_total, "rule_id": base_rule_id},
            "multiplier": (
                {"factor_pct": factor, "rule_id": multiplier_rule_id}
                if factor is not None else None
            ),
            "total": total,
            "computed_at": utc_now_iso(),
        }
        return QuoteResult(
            total=total,
            currency_unit=self.currency_unit(),
            base_total=base_total,
            base_rule_id=base_rule_id,
            multiplier_pct=factor,
            multiplier_rule_id=multiplier_rule_id,
            snapshot=snapshot,
        )

    @staticmethod
    def _as_local(at: datetime | None) -> datetime:
        local_tz = datetime.now().astimezone().tzinfo
        if at is None:
            return datetime.now().astimezone()
        if at.tzinfo is None:
            return at.replace(tzinfo=local_tz)
        return at.astimezone(local_tz)

    @staticmethod
    def _matches(rule: dict, scope: str, minute: int, pc_class: str | None) -> bool:
        if rule["scope"] != PricingScope.ANY.value and rule["scope"] != scope:
            return False
        ws, we = rule["window_start_min"], rule["window_end_min"]
        if ws is not None and we is not None:
            if ws > we:  # overnight window, e.g. 22:00-06:00
                if not (minute >= ws or minute < we):
                    return False
            elif not (ws <= minute < we):
                return False
        if rule["pc_class"] is not None and rule["pc_class"] != pc_class:
            return False
        return True

    @classmethod
    def _pick(
        cls, candidates: list[dict], scope: str, minute: int, pc_class: str | None
    ) -> dict | None:
        matched = [r for r in candidates if cls._matches(r, scope, minute, pc_class)]
        if not matched:
            return None
        matched.sort(key=lambda r: (r["priority"], r["price"] if r["price"] is not None else 0))
        return matched[0]

    # ---- rule CRUD ----

    def create_rule(self, **fields) -> dict:
        self._validate_rule_fields(fields, partial=False)
        return self._rules.create(**fields)

    def update_rule(self, rule_id: str, fields: dict) -> dict | None:
        existing = self._rules.get_by_id(rule_id)
        if existing is None:
            return None
        merged = {**existing, **fields}
        self._validate_rule_fields(merged, partial=True)
        allowed = {
            "name", "kind", "duration_sec", "price", "factor_pct", "pc_class",
            "scope", "window_start_min", "window_end_min", "priority", "active",
        }
        return self._rules.update(rule_id, {k: v for k, v in fields.items() if k in allowed})

    def get_rule(self, rule_id: str) -> dict | None:
        return self._rules.get_by_id(rule_id)

    def list_rules(self, active_only: bool = True) -> list[dict]:
        return self._rules.list_rules(active_only=active_only)

    @staticmethod
    def _validate_rule_fields(fields: dict, partial: bool) -> None:
        kind = fields.get("kind")
        if kind is None:
            if not partial:
                raise ValueError("kind is required")
            return
        if kind == PricingKind.FLAT.value:
            if not fields.get("duration_sec") or fields["duration_sec"] <= 0:
                raise ValueError("FLAT rules require a positive duration_sec")
            if fields.get("price") is None or fields["price"] < 0:
                raise ValueError("FLAT rules require a non-negative price")
            if fields.get("factor_pct") is not None:
                raise ValueError("FLAT rules must not set factor_pct")
        elif kind == PricingKind.PER_HOUR.value:
            if fields.get("price") is None or fields["price"] < 0:
                raise ValueError("PER_HOUR rules require a non-negative price")
            if fields.get("duration_sec") is not None:
                raise ValueError("PER_HOUR rules must not set duration_sec")
            if fields.get("factor_pct") is not None:
                raise ValueError("PER_HOUR rules must not set factor_pct")
        elif kind == PricingKind.MULTIPLIER.value:
            factor = fields.get("factor_pct")
            if factor is None or not 1 <= factor <= 1000:
                raise ValueError("MULTIPLIER rules require factor_pct 1..1000")
            if fields.get("price") is not None:
                raise ValueError("MULTIPLIER rules must not set price")
            if fields.get("duration_sec") is not None:
                raise ValueError("MULTIPLIER rules must not set duration_sec")
        else:
            raise ValueError(f"unknown kind: {kind}")

        ws, we = fields.get("window_start_min"), fields.get("window_end_min")
        if (ws is None) != (we is None):
            raise ValueError("window_start_min and window_end_min must be set together")
        for bound in (ws, we):
            if bound is not None and not 0 <= bound <= 1439:
                raise ValueError("window bounds must be 0..1439 minutes")

        scope = fields.get("scope", PricingScope.ANY.value)
        if scope not in {s.value for s in PricingScope}:
            raise ValueError(f"unknown scope: {scope}")

        if fields.get("name") is not None and not str(fields["name"]).strip():
            raise ValueError("name must not be empty")

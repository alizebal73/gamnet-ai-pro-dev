"""Operational reports + CSV export (P4-1)."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    InventoryReportResponse,
    SalesSummaryResponse,
    ShiftReportResponse,
    UtilizationResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.report_service import ReportService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/reports", tags=["reports"])


def _windowed(fn, from_date, to_date):
    try:
        return fn(from_date, to_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/sales-summary", response_model=SalesSummaryResponse)
def sales_summary(
    from_date: str | None = None,
    to_date: str | None = None,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)),
) -> SalesSummaryResponse:
    with get_connection() as conn:
        return SalesSummaryResponse(
            **_windowed(ReportService(conn).sales_summary, from_date,
                        to_date))


@router.get("/shifts", response_model=ShiftReportResponse)
def shift_report(
    from_date: str | None = None,
    to_date: str | None = None,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)),
) -> ShiftReportResponse:
    with get_connection() as conn:
        return ShiftReportResponse(
            **_windowed(ReportService(conn).shift_report, from_date,
                        to_date))


@router.get("/utilization", response_model=UtilizationResponse)
def utilization(
    from_date: str | None = None,
    to_date: str | None = None,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> UtilizationResponse:
    with get_connection() as conn:
        return UtilizationResponse(
            **_windowed(ReportService(conn).utilization, from_date,
                        to_date))


@router.get("/inventory", response_model=InventoryReportResponse)
def inventory_report(
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> InventoryReportResponse:
    with get_connection() as conn:
        return InventoryReportResponse(
            **ReportService(conn).inventory_report())


@router.get("/export")
def export(
    type: str,
    from_date: str | None = None,
    to_date: str | None = None,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)),
):
    with get_connection() as conn:
        try:
            filename, csv_text = ReportService(conn).export_csv(
                type, from_date, to_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        log_audit(
            conn, action="REPORT_EXPORT", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="report",
            entity_id=type,
            reason=f"from={from_date} to={to_date}",
        )
        return Response(
            content=csv_text, media_type="text/csv",
            headers={"Content-Disposition":
                     f"attachment; filename={filename}"},
        )

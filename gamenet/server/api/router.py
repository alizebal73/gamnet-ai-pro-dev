from fastapi import APIRouter

from gamenet.server.api import (
    admin,
    agent,
    agent_ws,
    auth,
    catalog,
    credit,
    customers,
    health,
    payments,
    pcs,
    pricing,
    refunds,
    sales,
    sessions,
    shifts,
    settings,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(admin.router)
api_router.include_router(agent.router)
api_router.include_router(agent_ws.router)
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(pricing.router)
api_router.include_router(settings.router)
api_router.include_router(sales.router)
api_router.include_router(payments.router)
api_router.include_router(catalog.router)
api_router.include_router(credit.router)
api_router.include_router(sessions.router)
api_router.include_router(shifts.router)
api_router.include_router(refunds.router)
api_router.include_router(pcs.router)

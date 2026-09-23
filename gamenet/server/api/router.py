from fastapi import APIRouter

from gamenet.server.api import auth, customers, health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(customers.router)

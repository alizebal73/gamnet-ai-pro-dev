"""Agent channel endpoints (device auth + heartbeat + ACK)."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    AgentAuthRequest,
    AgentAuthResponse,
    CommandAckRequest,
    CommandResponse,
    HeartbeatRequest,
    HeartbeatResponse,
)
from gamenet.server.repositories.agent_repository import AgentTokenRepository
from gamenet.server.services.agent_service import AgentAuthError, AgentService
from gamenet.server.services.errors import NotFound

router = APIRouter(prefix="/agent", tags=["agent"])

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AgentContext:
    pc_id: str
    token_id: str
    agent_version: str | None


def get_agent_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AgentContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    with get_connection() as conn:
        row = AgentTokenRepository(conn).find_valid(credentials.credentials)
    if row is None:
        raise HTTPException(
            status_code=401, detail="Invalid or expired agent token"
        )
    return AgentContext(pc_id=row["pc_id"], token_id=row["id"],
                        agent_version=row.get("agent_version"))


@router.post("/auth", response_model=AgentAuthResponse)
def agent_auth(payload: AgentAuthRequest) -> AgentAuthResponse:
    with get_connection() as conn:
        try:
            result = AgentService(conn).authenticate(
                device_code=payload.device_code, secret=payload.secret,
                agent_version=payload.agent_version,
            )
        except AgentAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        return AgentAuthResponse(**result)


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    payload: HeartbeatRequest,
    request: Request,
    agent: AgentContext = Depends(get_agent_context),
) -> HeartbeatResponse:
    with get_connection() as conn:
        result = AgentService(conn).heartbeat(
            {"pc_id": agent.pc_id, "agent_version": agent.agent_version},
            payload=payload.model_dump(exclude_none=True),
            ip=request.client.host if request.client else None,
        )
        return HeartbeatResponse(**result)


@router.post("/commands/{command_id}/ack", response_model=CommandResponse)
def ack_command(
    command_id: str,
    payload: CommandAckRequest,
    agent: AgentContext = Depends(get_agent_context),
) -> CommandResponse:
    with get_connection() as conn:
        try:
            cmd = AgentService(conn).ack(
                {"pc_id": agent.pc_id}, command_id,
                payload.ok, payload.result,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return CommandResponse.from_row(cmd)

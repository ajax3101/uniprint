from __future__ import annotations

import os
from ipaddress import ip_address
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_session
from .models import User


@dataclass(frozen=True)
class Actor:
    id: str
    roles: frozenset[str]


def current_actor(
    request: Request,
    x_dev_user_id: str | None = Header(default=None),
    x_dev_roles: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Actor:
    """Temporary local-only identity adapter; production IdP integration is not configured."""
    if os.environ.get("UNIPRINT_AUTH_MODE") != "development":
        raise HTTPException(status_code=503, detail="Identity provider is not configured")
    remote_host = request.client.host if request.client is not None else ""
    try:
        if not ip_address(remote_host).is_loopback:
            raise HTTPException(status_code=403, detail="Development authentication is restricted to loopback")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Development authentication is restricted to loopback") from exc
    if not x_dev_user_id:
        raise HTTPException(status_code=401, detail="Development actor header is required")
    user = session.get(User, x_dev_user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="User is unknown or inactive")
    roles = frozenset(role.strip() for role in (x_dev_roles or "employee").split(",") if role.strip())
    return Actor(id=x_dev_user_id, roles=roles)


def require_role(actor: Actor, *allowed: str) -> None:
    if not actor.roles.intersection(allowed):
        raise HTTPException(status_code=403, detail="Insufficient role")

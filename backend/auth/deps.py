"""
Auth enforcement + per-tenant ownership guard (review finding B1).

The project already ships JWT issuance (backend/api/auth.py) but no router
required it, leaving every business endpoint open and cross-tenant accessible.

This dependency closes that gap. It is FLAG-GATED so it doesn't break the current
no-login frontend during development:

    REQUIRE_AUTH=false (default)  -> no-op, endpoints stay open (dev/demo)
    REQUIRE_AUTH=true             -> valid bearer token required, AND if the path
                                     contains a business_id it must match the
                                     token's business_id (unless the token is admin)

Turn REQUIRE_AUTH=true in production (see DEPLOYMENT.md hardening checklist) once
the frontend attaches the bearer token.
"""
from __future__ import annotations
import os
from fastapi import Request, HTTPException, Depends
from backend.api.auth import get_current_user


def _required() -> bool:
    return os.getenv("REQUIRE_AUTH", "false").lower() == "true"


def require_auth(request: Request, user: dict = Depends(get_current_user)) -> dict:
    """
    Auth + ownership dependency. Attach to protected routers via
    `APIRouter(dependencies=[Depends(require_auth)])` or `include_router(..., dependencies=[...])`.
    """
    if not _required():
        return user or {}

    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Per-tenant ownership guard: if the route targets a specific business,
    # the caller's token must be scoped to that business.
    path_bid = request.path_params.get("business_id")
    token_bid = user.get("business_id")
    if path_bid and token_bid and str(path_bid) != str(token_bid) and not user.get("admin"):
        raise HTTPException(status_code=403, detail="Not authorized for this business")

    return user

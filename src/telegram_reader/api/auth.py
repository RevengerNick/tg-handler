from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class AuthContext:
    owner_id: str


def _same(left: str, right: str) -> bool:
    return bool(left and right and hmac.compare_digest(left.encode(), right.encode()))


async def require_reader_auth(request: Request) -> AuthContext:
    settings = request.app.state.telegram_reader.settings
    if not settings.auth_configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Reader API authentication is not configured")
    authorization = request.headers.get("Authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not _same(bearer.strip(), settings.api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    cf_id = request.headers.get("CF-Access-Client-Id", "")
    cf_secret = request.headers.get("CF-Access-Client-Secret", "")
    if settings.require_cf_access and not (
        _same(cf_id, settings.cf_client_id) and _same(cf_secret, settings.cf_client_secret)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    identity = f"{cf_id if settings.require_cf_access else 'local'}:{bearer}"
    owner_id = hashlib.sha256(identity.encode()).hexdigest()
    return AuthContext(owner_id=owner_id)

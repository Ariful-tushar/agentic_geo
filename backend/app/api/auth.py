"""Admin check (SPEC 9): write endpoints need the header `X-Admin-Token` = ADMIN_PASSWORD.

Read endpoints are public. The comparison takes the same time whatever the guess.
"""

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import get_settings

Token = Annotated[str | None, Header(alias="X-Admin-Token")]


def is_admin(token: str | None) -> bool:
    password = get_settings().admin_password
    if not token or not password:  # an empty ADMIN_PASSWORD means nobody is admin
        return False
    return hmac.compare_digest(token.encode(), password.encode())


async def require_admin(x_admin_token: Token = None) -> None:
    if not is_admin(x_admin_token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Admin token required (header X-Admin-Token)"
        )


async def optional_admin(x_admin_token: Token = None) -> bool:
    """True when a valid admin token was sent; used to show a bit more to the admin."""
    return is_admin(x_admin_token)

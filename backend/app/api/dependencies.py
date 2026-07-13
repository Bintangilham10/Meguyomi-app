from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import get_settings


class AuthenticationRequired(Exception):
    pass


def require_authenticated_user(request: Request) -> str:
    username = request.session.get("username")
    configured_username = get_settings().admin_username
    if not isinstance(username, str) or not compare_digest(
        username, configured_username
    ):
        raise AuthenticationRequired
    return username


AuthenticatedUser = Annotated[str, Depends(require_authenticated_user)]

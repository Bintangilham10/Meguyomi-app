from hmac import compare_digest

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.rate_limit import LoginRateLimiter
from app.schemas.auth import ErrorResponse, LoginRequest, UserResponse
from app.services.auth import authenticate_admin


settings = get_settings()
login_limiter = LoginRateLimiter(
    max_failures=settings.login_max_failures,
    window_seconds=settings.login_window_seconds,
)
router = APIRouter(prefix="/auth", tags=["auth"])


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@router.post(
    "/login",
    response_model=UserResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
def login(payload: LoginRequest, request: Request) -> UserResponse | JSONResponse:
    current_settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    limiter_key = f"{client_host}:{payload.username.casefold()}"

    if login_limiter.is_blocked(limiter_key):
        return error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "RATE_LIMITED",
            "Terlalu banyak percobaan login. Coba lagi nanti.",
        )

    if not authenticate_admin(payload.username, payload.password, current_settings):
        login_limiter.record_failure(limiter_key)
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_CREDENTIALS",
            "Username atau password salah.",
        )

    login_limiter.clear(limiter_key)
    request.session.clear()
    request.session["username"] = current_settings.admin_username
    return UserResponse(username=current_settings.admin_username)


@router.get(
    "/me",
    response_model=UserResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
def me(request: Request) -> UserResponse | JSONResponse:
    current_settings = get_settings()
    username = request.session.get("username")
    if not isinstance(username, str) or not compare_session_user(
        username, current_settings.admin_username
    ):
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "NOT_AUTHENTICATED",
            "Sesi login tidak valid.",
        )
    return UserResponse(username=username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def compare_session_user(session_username: str, configured_username: str) -> bool:
    return compare_digest(session_username, configured_username)

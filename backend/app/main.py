from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.core.config import get_settings


settings = get_settings()
if settings.app_env == "production" and (
    not settings.admin_password_hash
    or settings.session_secret == "development-only-session-secret-change-me"
):
    raise RuntimeError("Production authentication secrets are not configured.")

app = FastAPI(title="Meguyomi API", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="meguyomi_session",
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.app_env == "production",
)
app.include_router(auth_router)
app.include_router(health_router)

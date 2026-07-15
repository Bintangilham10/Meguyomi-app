from celery import Celery

from app.core.config import get_settings


settings = get_settings()
celery_app = Celery(
    "meguyomi",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Jakarta",
    enable_utc=True,
    imports=("app.tasks.preparation",),
)

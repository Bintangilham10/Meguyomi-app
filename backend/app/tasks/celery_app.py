from celery import Celery
from celery.schedules import crontab

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
    imports=(
        "app.tasks.preparation",
        "app.tasks.translation",
        "app.tasks.maintenance",
    ),
    beat_schedule={
        "cleanup-translation-checkpoints": {
            "task": "meguyomi.cleanup_translation_checkpoints",
            "schedule": crontab(hour=3, minute=0),
        }
    },
)

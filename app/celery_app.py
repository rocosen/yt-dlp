from celery import Celery
from app.config import settings

# Create Celery app
celery_app = Celery(
    "video_download_service",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task time limit (1 hour default)
    task_time_limit=settings.download_timeout,
    task_soft_time_limit=settings.download_timeout - 60,

    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Result backend settings
    result_expires=86400,  # 24 hours

    # Prefetch multiplier (1 for long-running tasks)
    worker_prefetch_multiplier=1,
)

# Note: For high concurrency (100+), use gevent pool:
# celery -A app.celery_app worker --pool=gevent --concurrency=100
# Requires: pip install gevent

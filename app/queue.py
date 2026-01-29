# app/queue.py
from celery import Celery
from app.config import settings

# Celery app is the “queue client” used by API and worker
celery_app = Celery(
    "ticket_enricher",
    broker=settings.redis_url,   # Redis broker for messages
    backend=settings.redis_url,  # Redis backend for task results (optional)
)

# Configure Celery to accept JSON payloads (safe/standard)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

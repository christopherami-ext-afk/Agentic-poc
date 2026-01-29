# app/worker.py
import asyncio
from app.queue import celery_app
from app.job_store import JobStore
from app.pipeline import run_pipeline
from app.config import settings

# JobStore is shared by tasks (SQLite file on disk)
store = JobStore(settings.job_db_path)


@celery_app.task(
    name="run_job",
    autoretry_for=(Exception,),      # automatically retry on exceptions
    retry_backoff=True,              # exponential backoff
    retry_kwargs={"max_retries": 2},  # keep retries low for POC; raise later for prod
)
def run_job(job_id: str, issue_key: str):
    """
    Celery executes sync functions, but our pipeline is async.
    So we run the async pipeline using asyncio.run().
    """
    try:
        return asyncio.run(run_pipeline(job_id, issue_key, store))
    except Exception as e:
        # Persist failure state for visibility
        store.set_status(job_id, "FAILED", error=str(e))
        store.audit(job_id, "FAILED", "Pipeline failed", {"error": str(e)})
        raise

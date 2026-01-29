# app/main.py
import uuid
from fastapi import FastAPI, Request, HTTPException

from app.job_store_postgres import JobStorePostgres
from app.queue import celery_app
from app.job_store import JobStore
from app.security import verify_webhook
from app.config import settings

app = FastAPI(title="Ticket Enricher Agentic v2")

store = JobStore(settings.job_db_path)
storePostgres = JobStorePostgres(settings.dsn)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/webhooks/jira")
async def jira_webhook(req: Request):
    print(">>> webhook hit")  # TEMP
    body = await req.body()
    #verify_webhook(req.headers, body)

    payload = await req.json()
    issue = payload.get("issue", {})
    issue_key = issue.get("key")
    if not issue_key:
        raise HTTPException(status_code=400, detail="No issue key found")

    job_id = str(uuid.uuid4())
    store.create_job(job_id, issue_key)
    store.audit(job_id, "QUEUED", "Created job from Jira webhook")

    # enqueue: worker will execute pipeline
    celery_app.send_task("run_job", args=[job_id, issue_key])

    return {"ok": True, "job_id": job_id, "issue_key": issue_key}

@app.post("/enrich/{issue_key}")
async def manual_enrich(issue_key: str):
    print(">>> manual hit")  # TEMP
    job_id = str(uuid.uuid4())
    store.create_job(job_id, issue_key)
    store.audit(job_id, "QUEUED", "Created job from manual request")
    celery_app.send_task("run_job", args=[job_id, issue_key])
    return {"ok": True, "job_id": job_id, "issue_key": issue_key}

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    audit = store.get_audit(job_id)
    return {"job": job, "audit": audit}

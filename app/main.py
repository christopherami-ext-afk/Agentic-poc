from fastapi import FastAPI, Request, HTTPException
from app.agentic_flow import run_agentic_enrichment

app = FastAPI(title="Ticket Enricher Agentic POC")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/webhooks/jira")
async def jira_webhook(req: Request):
    payload = await req.json()

    # Jira webhook payload varies; issue key typically here:
    issue = payload.get("issue", {})
    issue_key = issue.get("key")
    if not issue_key:
        raise HTTPException(status_code=400, detail="No issue key found")

    # OPTIONAL: only act on assignee change
    # For POC we run enrichment for any issue update event
    result = await run_agentic_enrichment(issue_key)
    return {"ok": True, "result": result}

@app.post("/enrich/{issue_key}")
async def manual_enrich(issue_key: str):
    return await run_agentic_enrichment(issue_key)

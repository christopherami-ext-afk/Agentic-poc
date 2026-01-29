# app/security.py
from fastapi import HTTPException
from app.config import settings

def verify_webhook(headers, body: bytes) -> None:
    """
    Simple shared-secret validation.
    Jira Automation can send header: X-Webhook-Secret
    """
    expected = settings.webhook_secret
    if not expected:
        return  # if not configured, skip (POC)

    got = headers.get("x-webhook-secret") or headers.get("X-Webhook-Secret")
    if got != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

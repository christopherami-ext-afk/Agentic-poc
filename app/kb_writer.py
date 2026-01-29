# app/kb_writer.py
import os
from typing import Dict, Any
from app.config import settings


def ensure_kb_dir() -> str:
    # Create KB directory if missing
    kb = settings.kb_dir
    os.makedirs(kb, exist_ok=True)
    return kb


def write_ticket_pack(issue_key: str, title: str, payload: Dict[str, Any]) -> str:
    """
    Writes a canonical Ticket Knowledge Pack file.
    This is the *source* for RAG later (RAG can be empty at start).
    """
    kb = ensure_kb_dir()

    # Store each ticket as kb_data/tickets/KAN-123.md
    tickets_dir = os.path.join(kb, "tickets")
    os.makedirs(tickets_dir, exist_ok=True)

    path = os.path.join(tickets_dir, f"{issue_key}.md")

    # Keep the content deterministic and standard (front matter + sections)
    md = []
    md.append("---")
    md.append("type: ticket_knowledge_pack")
    md.append(f"jira_key: {issue_key}")
    md.append(f"title: {title}")
    md.append("---")
    md.append("")
    md.append("# Runtime Output Snapshot")
    md.append("")
    md.append("## Enrichment JSON")
    md.append("```json")
    md.append(payload.get("enrichment_json_pretty", "{}"))
    md.append("```")
    md.append("")
    md.append("## DEV_GUIDE.md (generated)")
    md.append(payload.get("dev_guide_md", ""))
    md.append("")
    md.append("## References")
    md.append("### Similar Jira issues")
    for s in payload.get("similar", []):
        md.append(f"- {s}")
    md.append("")
    md.append("### Confluence references")
    for c in payload.get("confluence_refs", []):
        md.append(f"- {c.get('title')} ({c.get('url', '')})")
    md.append("")
    md.append("### Repo analysis (impacted evidence)")
    md.append("```json")
    md.append(payload.get("repo_analysis_pretty", "{}"))
    md.append("```")
    md.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    return path

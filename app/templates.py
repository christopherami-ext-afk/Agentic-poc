# app/templates.py
import json

def build_prompt(ticket_key: str,
                 title: str,
                 description: str,
                 similar_issues: list[str],
                 confluence_pages: list[dict],
                 repo_analysis: dict,
                 kb_exact: dict | None,
                 rag_chunks: list[dict]) -> str:
    """
    build_prompt gathers all context into a single structured prompt.
    The key industrial rule: "Do not invent impacted classes — use repo_analysis evidence."
    """

    conf_text = "\n".join([
        f"- {p.get('title')} (id={p.get('id')})\n  excerpt: {str(p.get('excerpt',''))[:800]}"
        for p in confluence_pages
    ]) or "(none)"

    repo_text = json.dumps(repo_analysis, indent=2)[:12000]

    kb_text = json.dumps(kb_exact, indent=2)[:4000] if kb_exact else "(no existing ticket pack found)"

    rag_text = "\n".join([
        f"[{c.get('source','kb')}] {c.get('title','')}\n{str(c.get('text',''))[:800]}"
        for c in rag_chunks
    ]) or "(RAG empty)"

    return f"""
You are a senior Semarchy-style Java/Spring Boot backend engineer assistant.

You MUST output 2 parts:
1) Strict JSON object with keys:
   - short_summary
   - acceptance_criteria (array)
   - impacted_areas (array of packages/files/modules)
   - implementation_plan (array)
   - test_plan (array)
   - risks (array)
   - confidence (0..1)

2) Then output EXACT line:
---DEV_GUIDE---
Then markdown for DEV_GUIDE.md including:
- Ticket link placeholder
- Proposed approach
- Impacted modules/classes/files (use repo_analysis evidence)
- Suggested code changes (pseudo + minimal snippets grounded in snippets)
- Tests: unit + integration (name concrete test classes)
- References: similar Jira + Confluence
- QA checklist: verify + rollback + monitoring

Ticket:
Key: {ticket_key}
Title: {title}
Description:
{description}

Similar Jira issues:
{chr(10).join(similar_issues)}

Confluence context:
{conf_text}

Repo analysis (SOURCE OF TRUTH for impacted classes/files/tests):
{repo_text}

Existing Knowledge Pack (exact lookup by key):
{kb_text}

RAG retrieved chunks (may be empty initially):
{rag_text}

Rules:
- Do NOT invent class names or file paths; if missing, propose discovery steps.
- If RAG empty, rely on Jira + Confluence + Repo analysis.
- Keep output useful for a Java/Spring Boot developer.
""".strip()

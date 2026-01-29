# app/pipeline.py
import asyncio
import json
import time
from typing import Dict, Any, List

from app.config import settings
from app.job_store import JobStore
from app.jira_client import JiraClient
from app.confluence_client import ConfluenceClient
from app.repo_analyzer import analyze_repo_for_ticket
from app.templates import build_prompt
from app.llm_ollama import ollama_generate
from app.github_git import safe_branch_name, create_branch_and_commit
from app.github_client import GitHubClient
from app.kb_writer import write_ticket_pack


def _safe_json_parse(s: str) -> Dict[str, Any]:
    # Parse LLM JSON safely; if it fails, store raw data
    try:
        return json.loads(s.strip())
    except Exception:
        return {"parse_error": "invalid_json_from_llm", "raw": s[:8000]}


async def run_pipeline(job_id: str, issue_key: str, store: JobStore) -> Dict[str, Any]:
    """
    Runs the full workflow:
      Jira -> similar -> Confluence -> Repo analysis -> KB lookup -> RAG (optional)
      -> LLM -> local git branch commit -> GitHub issue + PR -> Jira comment -> write Ticket Pack
    """

    # ---------- INIT ----------
    store.set_status(job_id, "RUNNING")
    store.audit(job_id, "START", "Job started", {"issue_key": issue_key})

    jira = JiraClient()
    conf = ConfluenceClient()
    gh = GitHubClient()

    # ---------- STAGE: Jira fetch ----------
    issue = await jira.get_issue(issue_key)
    fields = issue.get("fields", {})

    title = fields.get("summary", "") or ""
    desc_obj = fields.get("description")

    description = ""
    if isinstance(desc_obj, dict):
        description = str(desc_obj)[:6000]
    elif isinstance(desc_obj, str):
        description = desc_obj[:6000]

    store.audit(job_id, "JIRA_FETCH", "Fetched Jira issue", {"title": title})

    # ---------- STAGE: Similar Jira issues ----------
    keywords = " ".join(title.split()[:6])
    jql = f'project = { "KAN" } AND text ~ "{keywords}" ORDER BY updated DESC'
    search = await jira.jql_search(jql, max_results=5)
    issues = search.get("issues", [])
    similar = [
        f'{i.get("key")} - {i.get("fields", {}).get("summary","")}'
        for i in issues
        if i.get("key") != issue_key
    ]
    store.audit(job_id, "JIRA_SIMILAR", "Similar Jira issues found", {"count": len(similar)})

    # ---------- STAGE: Confluence ----------
    conf_pages = await conf.search_pages(f"{issue_key} {title}", limit=5)
    conf_details: List[Dict[str, Any]] = []
    for p in conf_pages:
        if p.get("id"):
            conf_details.append(await conf.get_page_excerpt(p["id"], max_chars=1500))

    # Reduce to references list for later writing
    confluence_refs = []
    for p in conf_details:
        links = p.get("links", {})
        webui = links.get("webui", "")
        confluence_refs.append({
            "title": p.get("title"),
            "url": f"{conf.base_url}/wiki{webui}" if webui else ""
        })

    store.audit(job_id, "CONF", "Confluence context retrieved", {"pages": len(conf_details)})

    # ---------- STAGE: Repo Analysis Agent ----------
    repo_analysis = await analyze_repo_for_ticket(title, description)
    store.audit(job_id, "REPO_ANALYSIS", "Repo analysis completed", {
        "impacted_files": len(repo_analysis.get("impacted_files", [])),
        "test_targets": len(repo_analysis.get("test_targets", [])),
        "error": repo_analysis.get("error"),
    })

    # ---------- STAGE: KB exact lookup (Ticket Pack by Jira key) ----------
    kb_exact = store.get_ticket_pack(issue_key)  # metadata only; content file path later
    store.audit(job_id, "KB_LOOKUP", "KB exact lookup done", {"found": bool(kb_exact)})

    # ---------- STAGE: RAG retrieve (optional; starts empty) ----------
    rag_chunks: List[Dict[str, Any]] = []
    # For now we keep it empty, and we explicitly audit it:
    store.audit(job_id, "RAG", "RAG retrieval skipped/empty (bootstrap phase)", {"chunks": 0})

    # ---------- STAGE: LLM enrichment ----------
    prompt_t0 = time.monotonic()
    store.audit(job_id, "PROMPT", "Building LLM prompt", {})
    prompt = build_prompt(
        ticket_key=issue_key,
        title=title,
        description=description,
        similar_issues=similar,
        confluence_pages=conf_details,
        repo_analysis=repo_analysis,
        kb_exact=kb_exact,
        rag_chunks=rag_chunks,
    )

    print('==== LLM PROMPT ====', prompt)  # TEMP
    store.audit(job_id, f"PROMPT:{prompt}", "LLM prompt built", {
        "chars": len(prompt),
        "secs": round(time.monotonic() - prompt_t0, 3),
    })

    llm_t0 = time.monotonic()
    store.audit(job_id, "LLM", "Calling Ollama", {
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "timeout_seconds": settings.ollama_timeout_seconds,
    })

    try:
        # Add a small buffer to the overall await budget.
        await_budget = float(settings.ollama_timeout_seconds) + 5.0
        llm_out = await asyncio.wait_for(ollama_generate(prompt), timeout=await_budget)
    except asyncio.TimeoutError:
        store.audit(job_id, "LLM", "Ollama call timed out", {
            "timeout_seconds": float(settings.ollama_timeout_seconds),
            "elapsed_seconds": round(time.monotonic() - llm_t0, 3),
        })
        store.set_status(job_id, "FAILED")
        store.set_result(job_id, {
            "issue_key": issue_key,
            "title": title,
            "error": "ollama_timeout",
        })
        return store.get_result(job_id) or {"error": "ollama_timeout"}
    except Exception as e:
        store.audit(job_id, "LLM", "Ollama call failed", {
            "error": str(e)[:2000],
            "elapsed_seconds": round(time.monotonic() - llm_t0, 3),
        })
        store.set_status(job_id, "FAILED")
        store.set_result(job_id, {
            "issue_key": issue_key,
            "title": title,
            "error": "ollama_error",
            "detail": str(e)[:4000],
        })
        return store.get_result(job_id) or {"error": "ollama_error"}

    store.audit(job_id, "LLM", "LLM generated output", {
        "chars": len(llm_out),
        "elapsed_seconds": round(time.monotonic() - llm_t0, 3),
    })

    # Split output into JSON + DEV_GUIDE
    if "---DEV_GUIDE---" in llm_out:
        json_part, md_part = llm_out.split("---DEV_GUIDE---", 1)
    else:
        json_part, md_part = llm_out, ""

    enrichment = _safe_json_parse(json_part)
    dev_guide_md = md_part.strip() or f"# DEV GUIDE for {issue_key}\n\n(LLM did not return guide)\n"

    # ---------- STAGE: Local Git (branch + DEV_GUIDE commit) ----------
    branch = safe_branch_name(issue_key, title)
    created_branch = create_branch_and_commit(branch, "DEV_GUIDE.md", dev_guide_md)
    store.audit(job_id, "GIT", "Branch created and DEV_GUIDE committed", {"branch": created_branch})

    # ---------- STAGE: GitHub issue + PR ----------
    gh_issue = None
    pr = None
    if (settings.github_token and settings.repo_url):
        gh_issue = await gh.create_issue(
            title=f"{issue_key}: {title}",
            body=f"Auto-enriched from Jira {issue_key}\n\n"
                 f"## Summary\n{enrichment.get('short_summary','')}\n\n"
                 f"## Acceptance criteria\n" + "\n".join([f"- {x}" for x in enrichment.get("acceptance_criteria", [])]) + "\n\n"
                 f"## Repo impacted evidence\n```json\n{json.dumps(repo_analysis, indent=2)[:12000]}\n```\n"
        )
        store.audit(job_id, "GITHUB_ISSUE", "GitHub issue created", {"url": gh_issue.get("html_url")})

        # PR requires branch to exist on remote; your create_branch_and_commit() tries push.
        pr = await gh.create_pr(
            head=created_branch,
            base=settings.git_default_branch,
            title=f"{issue_key}: {title} (DEV_GUIDE)",
            body=f"Generated DEV_GUIDE.md + enrichment context.\n\nGitHub issue: {gh_issue.get('html_url') if gh_issue else ''}",
        )
        store.audit(job_id, "GITHUB_PR", "PR created (or existed)", {"url": pr.get("html_url")})

    # ---------- STAGE: Jira comment back ----------
    comment_lines = [
        "[AI Enrichment]",
        f"- Branch: {created_branch}",
        "- DEV_GUIDE.md committed",
    ]
    if gh_issue and gh_issue.get("html_url"):
        comment_lines.append(f"- GitHub Issue: {gh_issue.get('html_url')}")
    if pr and pr.get("html_url"):
        comment_lines.append(f"- PR: {pr.get('html_url')}")

    await jira.add_comment(issue_key, "\n".join(comment_lines))
    store.audit(job_id, "JIRA_COMMENT", "Comment posted to Jira", {"issue_key": issue_key})

    # ---------- STAGE: Save Ticket Knowledge Pack (KB grows) ----------
    enrichment_json_pretty = json.dumps(enrichment, indent=2)[:20000]
    repo_analysis_pretty = json.dumps(repo_analysis, indent=2)[:20000]

    pack_path = write_ticket_pack(issue_key, title, {
        "enrichment_json_pretty": enrichment_json_pretty,
        "dev_guide_md": dev_guide_md,
        "similar": similar,
        "confluence_refs": confluence_refs,
        "repo_analysis_pretty": repo_analysis_pretty,
    })

    store.upsert_ticket_pack(issue_key, title, "ENRICHED", pack_path)
    store.audit(job_id, "KB_WRITE", "Ticket Knowledge Pack written", {"path": pack_path})

    # ---------- DONE ----------
    result = {
        "issue_key": issue_key,
        "title": title,
        "branch": created_branch,
        "github_issue_url": gh_issue.get("html_url") if gh_issue else None,
        "pr_url": pr.get("html_url") if pr else None,
        "similar": similar,
        "confluence_refs": confluence_refs,
        "repo_analysis": repo_analysis,
        "enrichment": enrichment,
        "dev_guide_path": "DEV_GUIDE.md",
        "ticket_pack_path": pack_path,
    }

    store.set_result(job_id, result)
    store.audit(job_id, "DONE", "Pipeline completed successfully")
    return result

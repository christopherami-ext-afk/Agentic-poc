from app.jira_client import JiraClient
from app.llm_ollama import ollama_generate
from app.templates import build_prompt
from app.github_git import safe_branch_name, create_branch_and_commit

async def run_agentic_enrichment(issue_key: str) -> dict:
    jira = JiraClient()
    issue = await jira.get_issue(issue_key)

    fields = issue.get("fields", {})
    title = fields.get("summary", "") or ""
    description = ""

    # Jira Cloud description is rich text; keep it simple for POC
    desc_obj = fields.get("description")
    if isinstance(desc_obj, dict):
        description = str(desc_obj)[:6000]
    elif isinstance(desc_obj, str):
        description = desc_obj[:6000]

    # Tool 1: find similar issues (simple keyword JQL)
    keywords = " ".join([w for w in title.split()[:6]])
    jql = f'project = { "KAN" } AND text ~ "{keywords}" ORDER BY updated DESC'
    search = await jira.jql_search(jql, max_results=5)
    issues = search.get("issues", [])
    similar = [f'{i.get("key")} - {i.get("fields", {}).get("summary","")}' for i in issues if i.get("key") != issue_key]

    prompt = build_prompt(issue_key, title, description, similar)
    llm_out = await ollama_generate(prompt)

    # split JSON and DEV guide
    print("LLM Output:", llm_out)
    if "---DEV_GUIDE---" in llm_out:
        json_part, md_part = llm_out.split("---DEV_GUIDE---", 1)
    else:
        json_part, md_part = llm_out, ""

    # branch + guide commit (local repo)
    branch = safe_branch_name(issue_key, title)
    md_path = "DEV_GUIDE.md"
    md_content = md_part.strip() or f"# DEV GUIDE for {issue_key}\n\n(LLM did not return guide)\n"

    created_branch = create_branch_and_commit(branch, md_path, md_content)

    # post comment back to Jira
    comment = f"""[AI Enrichment]
        Branch: {created_branch}
        Guide file: {md_path}

        Output (raw JSON + guide generated locally)."""


    await jira.add_comment(issue_key, comment)

    return {
        "issue_key": issue_key,
        "branch": created_branch,
        "dev_guide_path": md_path,
        "llm_raw": llm_out[:20000],
        "similar": similar,
    }

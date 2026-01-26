from git import Repo
from app.config import settings
import re
from datetime import datetime


# Generate a safe branch name from ticket key and title
def safe_branch_name(ticket_key: str, title: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    safe = safe[:40] if safe else "work"
    return f"{ticket_key.lower()}-{safe}"

def ensure_repo() -> Repo:
    if not settings.local_repo_path:
        raise RuntimeError("LOCAL_REPO_PATH is not set")
    return Repo(settings.local_repo_path)

def create_branch_and_commit(branch_name: str, md_path: str, md_content: str) -> str:
    repo = ensure_repo()
    origin = repo.remotes.origin

    # fetch and checkout default branch
    origin.fetch()
    repo.git.checkout(settings.git_default_branch)
    repo.git.pull("origin", settings.git_default_branch)

    # create branch
    if branch_name in [h.name for h in repo.heads]:
        repo.git.checkout(branch_name)
    else:
        repo.git.checkout("-b", branch_name)

    # write guide
    full_path = f"{settings.local_repo_path}/{md_path}"
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    repo.index.add([md_path]) # stage the new/modified file
    repo.index.commit(f"Add DEV_GUIDE for {branch_name} ({datetime.utcnow().isoformat()}Z)")

    # optional push (requires auth configured in git)
    try:
        origin.push(branch_name)
    except Exception:
        # pushing may fail if auth not configured; still fine for local POC
        pass

    return branch_name

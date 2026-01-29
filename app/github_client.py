# app/github_client.py
from typing import Dict, Any
import httpx
from app.config import settings


class GitHubClient:
    """
    GitHub Ops Agent:
    - Create GitHub Issue (tracking)
    - Create PR (from pushed branch)
    """

    def __init__(self):
        self.api = "https://api.github.com"
        self.repo = settings.repo_url  # "org/repo"
        self.headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
        }

    async def create_issue(self, title: str, body: str) -> Dict[str, Any]:
        url = f"{self.api}/repos/{self.repo}/issues"
        payload = {"title": title, "body": body}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            return r.json()

    async def create_pr(self, head: str, base: str, title: str, body: str) -> Dict[str, Any]:
        """
        head = branch name in the repo (must exist on origin)
        base = default branch
        """
        url = f"{self.api}/repos/{self.repo}/pulls"
        payload = {"head": head, "base": base, "title": title, "body": body}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self.headers, json=payload)
            if r.status_code == 422:
                # PR likely already exists
                return {"warning": "PR may already exist", "head": head, "base": base}
            r.raise_for_status()
            return r.json()

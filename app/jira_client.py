import base64
import httpx # httpx is an async HTTP client library
from app.config import settings


# this function is used to create the Basic Auth header for Jira API requests and is private to this module as it starts with an underscore
def _basic_auth_header(email: str, api_token: str) -> str:
    """Generate a Basic Auth header value for Jira API."""
    auth_str = f"{email}:{api_token}"
    b64_auth_str = base64.b64encode(auth_str.encode()).decode("utf-8")
    return f"Basic {b64_auth_str}"


class JiraClient:

    def __init__(self):
        self.base_url = settings.jira_base_url.rstrip("/")
        self.auth_header = _basic_auth_header(settings.jira_email, settings.jira_api_token)
        self.headers = {
            "Authorization": self.auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    
    async def get_issue(self, issue_key: str) -> dict:
        """Fetch a Jira issue by its key."""
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()


    async def jql_search(self, jql: str, max_results: int = 10) -> dict:
        url = f"{self.base_url}/rest/api/3/search/jql"
        payload = {"jql": jql, "maxResults": max_results}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
            return r.json()



    async def add_comment(self, issue_key: str, markdown: str) -> None:
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        payload = {"body": {"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": markdown[:30000]}]}
        ]}}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=self.headers, json=payload)
            r.raise_for_status()
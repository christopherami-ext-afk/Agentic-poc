# app/confluence_client.py
import base64
from typing import List, Dict, Any
import httpx
from app.config import settings


def _basic_auth(email: str, token: str) -> str:
    # Confluence Cloud uses Basic auth with email:APIToken
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


class ConfluenceClient:
    """
    Confluence Agent:
    - Search pages relevant to the ticket
    - Pull excerpts + web links
    """

    def __init__(self):
        self.base_url = settings.confluence_base_url.rstrip("/")
        self.headers = {
            "Authorization": _basic_auth(settings.confluence_email, settings.confluence_api_token),
            "Accept": "application/json",
        }

    async def search_pages(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Uses Confluence search API with CQL.
        We search in a space if space key is configured.
        """
        url = f"{self.base_url}/wiki/rest/api/search"

        # If space key exists, restrict search to that space (reduces noise).
        space_clause = f' AND space="{settings.confluence_space_key}"' if settings.confluence_space_key else ""
        cql = f'text ~ "{query}"{space_clause}'

        params = {"cql": cql, "limit": limit}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()

        out: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            content = item.get("content", {})
            out.append({
                "id": content.get("id"),
                "title": content.get("title"),
                "webui": content.get("_links", {}).get("webui"),
            })
        return out

    async def get_page_excerpt(self, page_id: str, max_chars: int = 1500) -> Dict[str, Any]:
        """
        Expand body.storage (HTML). For prompts, we only keep a short excerpt.
        """
        url = f"{self.base_url}/wiki/rest/api/content/{page_id}"
        params = {"expand": "body.storage"}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()

        html = data.get("body", {}).get("storage", {}).get("value", "")
        return {
            "id": data.get("id"),
            "title": data.get("title"),
            "excerpt": html[:max_chars],
            "links": data.get("_links", {}),
        }

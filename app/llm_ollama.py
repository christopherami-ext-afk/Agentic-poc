import httpx
from app.config import settings

async def ollama_generate(prompt: str) -> str:
    url = f"{settings.ollama_base_url}/api/chat"

    payload = {
        "model": settings.ollama_model,   # e.g. llama3.2:latest
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"]

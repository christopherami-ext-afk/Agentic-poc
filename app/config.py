from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    jira_base_url: str = os.getenv("JIRA_BASE_URL", "")
    jira_email: str = os.getenv("JIRA_EMAIL", "")
    jira_api_token: str = os.getenv("JIRA_API_TOKEN", "")
    jira_project_key: str = os.getenv("JIRA_PROJECT_KEY", "KAN")

    repo_url: str = os.getenv("REPO_URL", "")
    local_repo_path: str = os.getenv("LOCAL_REPO_PATH", "")
    git_default_branch: str = os.getenv("GIT_DEFAULT_BRANCH", "main")
    github_token: str = os.getenv("GITHUB_TOKEN", "")

    confluence_base_url: str = os.getenv("CONFLUENCE_BASE_URL", "")
    confluence_space_key: str = os.getenv("CONFLUENCE_SPACE_KEY", "")
    confluence_email: str = os.getenv("CONFLUENCE_EMAIL", "")
    confluence_api_token: str = os.getenv("CONFLUENCE_API_TOKEN", "")

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")

settings = Settings()

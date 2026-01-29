# Agentic-poc

## Overview
An agentic POC for ticket enrichment pipeline integrating Jira, Confluence, GitHub, and Google Gemini LLM.

## Setup

### Prerequisites
- Python 3.11+
- Redis (for Celery task queue)
- Google Gemini API key

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables in `.env`:
   - Copy `.env.example` to `.env`
   - `ROHAN-API`: Your Google Gemini API key
   - `GEMINI_MODEL`: Gemini model to use (default: gemini-1.5-flash)
   - Set up Jira, GitHub, and Confluence credentials as needed

4. Run the application:
   ```bash
   # Start Redis
   redis-server
   
   # Start Celery worker
   celery -A app.worker.celery_app worker --loglevel=INFO
   
   # Start FastAPI server
   uvicorn app.main:app --reload
   
   # Start Streamlit UI (optional)
   streamlit run ui/streamlit_app.py
   ```

## Features
- Jira webhook integration
- Automated ticket enrichment using Google Gemini
- Confluence knowledge base integration
- Repository analysis and code impact assessment
- GitHub issue and PR creation
- Knowledge base accumulation

## Configuration
See `.env.example` for all available configuration options.
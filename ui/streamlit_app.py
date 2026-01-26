import streamlit as st
import requests
import app.config as settings

st.title("Ticket Enricher POC UI")

# ---- Orchestrator ----
api_base = st.text_input("Orchestrator API base", "http://localhost:8000")
issue_key = st.text_input("Jira Issue Key (e.g., KAN-1)")

if st.button("Run enrichment"):
    r = requests.post(f"{api_base}/enrich/{issue_key}")
    st.write(r.status_code)
    st.json(r.json())

st.divider()
# ---- Confluence Search ----
st.subheader("Confluence search")

confluence_base = st.text_input("Confluence base URL", "https://christopherami87.atlassian.net/wiki")
space_key = st.text_input("Confluence space key (optional)", "SD")

# Prefill from env settings; allow override in UI
confluence_email = st.text_input("Confluence email", value="christopherami87@gmail.com", placeholder="you@company.com")
confluence_token = st.text_input("Confluence API token", value="ATATT3xFfGF0eBcoPs0qgNAxeZ2aGapmWYtoreNuXCXidk37hjdO0FHMFWwGvEIFZpH1i1630ATAI1-obUuuu40RO0DfZz1hFaj_eSQPAQKTP8PJSUMAEcenFxSqcxaAhGhTULOWxM2x1VqfJcqgIJ2WApmITfnLBZ_9XqTysuwkmS1WzNLg3U4=19ACACA8", type="password")

default_q = issue_key.strip() if issue_key else ""
query = st.text_input("Search query", value=default_q, placeholder="e.g., KAN-1 or 'payment service'")

if st.button("Search Confluence"):
    if not (confluence_base and confluence_email and confluence_token and query.strip()):
        st.error("Missing Confluence base URL, email, token, or search query.")
    else:
        # Build CQL (restrict to space if provided)
        q = query.strip().replace('"', '\\"')  # avoid breaking CQL quotes
        if space_key.strip():
            cql = f'space = "{space_key.strip()}" AND text ~ "{q}"'
        else:
            cql = f'text ~ "{q}"'

        url = f"{confluence_base.rstrip('/')}/rest/api/content/search"
        params = {"cql": cql, "limit": 10}
        auth = (confluence_email, confluence_token)

        resp = requests.get(url, params=params, auth=auth)
        st.write("Status:", resp.status_code)

        if resp.ok:
            data = resp.json()
            results = data.get("results", [])

            if not results:
                st.info("No results found.")
            else:
                for item in results:
                    title = item.get("title", "(no title)")
                    webui = item.get("_links", {}).get("webui", "")
                    full_link = confluence_base.rstrip("/") + webui if webui else None

                    if full_link:
                        st.markdown(f"- [{title}]({full_link})")
                    else:
                        st.write(f"- {title}")
        else:
            st.error("Confluence search failed.")
            st.code(resp.text)
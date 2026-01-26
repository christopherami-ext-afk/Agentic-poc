def build_prompt(ticket_key: str, title: str, description: str, similar_issues: list[str]) -> str:
    return f"""
You are a senior Semarchy-style backend engineer assistant.
Produce:
1) Enrichment JSON (strict JSON) with keys:
   - short_summary
   - acceptance_criteria (array)
   - impacted_areas (array: packages/files/modules guesses)
   - implementation_plan (array of steps)
   - test_plan (array)
   - risks (array)
   - confidence (0..1)
2) Then a DEV_GUIDE.md section (markdown) including:
   - Ticket link placeholder
   - Proposed approach
   - Suggested code changes (pseudo + minimal snippets)
   - Tests
   - References (similar Jira issues)
   - Quality Assurance checklist (markdown) including:
      - Items to verify the implementation
      - Testing steps
      - Rollback steps
      - Monitoring steps

Ticket:
Key: {ticket_key}
Title: {title}
Description:
{description}

Similar Jira issues:
{chr(10).join(similar_issues)}

Rules:
- If uncertain, say so and lower confidence.
- Keep output useful for a Java/Spring Boot developer.
- First output MUST be strict JSON on a single JSON object.
- After JSON, output a line: ---DEV_GUIDE---
- Then output markdown for DEV_GUIDE.md.
""".strip()

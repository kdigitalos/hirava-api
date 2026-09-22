# Shared AI provider settings

Configure the backend `.env` and restart the API:

```dotenv
AI_PROVIDER=openai
OPENAI_MODEL=gpt-4.1-mini
GROQ_MODEL=openai/gpt-oss-120b
OPENAI_API_KEY=your-openai-key
GROQ_API_KEY=your-groq-key
```

Change only AI_PROVIDER to groq to use the saved Groq model/key. Change the selected
provider's model setting to choose a different model. Both keys stay in place.
The model must support the agent's endpoint and strict structured output schema;
not every model is interchangeable. Account access must also be available.

app.agents.providers supplies provider_config and create_client for future agents.
Screening, criteria generation, profile extraction and employment extraction use
this shared selection. New agents must use the shared module and test their own
prompts, tool requirements and schemas on both providers. This does not implement
future agents or claim universal model compatibility. Local OCR and deterministic
candidate matching do not call either provider.

Shared settings take precedence over legacy AI_SCREENING_PROVIDER,
OPENAI_SCREENING_MODEL and GROQ_SCREENING_MODEL. Absent shared settings preserve
legacy behavior. An explicitly blank model fails configuration rather than falling
back. Never implement automatic cross-provider fallback. Clients disable SDK retries.
Screening enablement and intake enablement remain separate switches.

GPT-4.1 mini supports Responses and structured outputs. Official pricing checked
2026-09-20: $0.40 per million input tokens and $1.60 per million output tokens
(standard text pricing). Source: https://developers.openai.com/api/docs/models/gpt-4.1-mini
These rates do not guarantee a number of assessments for a dollar balance.
Criteria extraction can add a request before assessment; existing token usage is
recorded per result. No application-wide dollar spending cap is implemented.
Switching providers does not rerun historical assessments, and there is no background
paid backfill. Pending requests bound to the old provider must be checked/retried.

"""
Setup Routes — POST /de/setup-chat
Conversational Digital Employee configuration assistant.

The endpoint takes a conversation history (OpenAI-style messages array) and
returns the assistant's next reply. When enough information has been collected,
the reply includes a structured JSON config block between ---CONFIG--- / ---END---
markers. The portal detects this, renders a preview, and lets the user confirm
before calling POST /de/create.
"""

import json
import os
import re

SYSTEM_PROMPT = """You are a setup assistant helping users create a Digital Employee — an autonomous AI agent with a defined mission, KPIs, and approval gates.

Your goal: gather the information needed through a focused, natural conversation. Ask one or two things at a time. Be specific. Suggest reasonable defaults when appropriate.

You need to collect:
1. **What it does** — a clear mission statement (1-3 sentences: what does this agent own? what outcome is it responsible for?)
2. **What success looks like** — 2-5 measurable KPIs or goals
3. **Level 0 actions** — things it does autonomously with no notification (e.g. read files, ping services, update logs)
4. **Level 1 actions** — things it does and documents, you can revert (e.g. deploy a page, update a config)
5. **Level 2 actions** — things requiring your explicit approval before acting (e.g. disable a service, send external comms)
6. **Hard constraints** — things it must never do regardless of reasoning
7. **Run schedule** — how often it should run (manual, hourly, 3x_daily, daily, weekly)
8. **Data sources** — optional URLs or file paths it should read (e.g. an API endpoint for metrics)
9. **Autoresearch** — optional: should it proactively research topics and update its knowledge base?

Start by asking what problem the agent should solve or what task it should own. Build the config conversationally from the answers. Don't ask for all fields at once.

When you have gathered enough for a complete, working configuration, include your confirmation message AND then this EXACT block at the end:

---CONFIG---
{
  "name": "slug-name",
  "display_name": "DISPLAY NAME",
  "role": "Brief role description",
  "color": "#FF4500",
  "mission": "Clear mission statement.",
  "kpis": ["KPI 1", "KPI 2"],
  "responsibilities": {
    "level_0": ["Read metrics files", "Check service health"],
    "level_1": ["Update a config file"],
    "level_2": ["Disable a service entirely"]
  },
  "hard_constraints": ["Never delete production data"],
  "self_evaluation": {
    "criteria": ["Success looks like X"],
    "schedule": "daily"
  },
  "data_sources": [],
  "autoresearch": {
    "enabled": false,
    "queries": [],
    "schedule": "daily"
  }
}
---END---

Rules:
- Only output ---CONFIG--- when you have all required fields (name, mission, at least 1 KPI, at least 1 action per level, at least 1 constraint).
- name must be lowercase letters, digits, hyphens only (e.g. "cost-monitor", "ops-lead").
- Choose a fitting color: #FF4500 (orange/ops), #22c55e (green/finance), #6366f1 (purple/research), #0ea5e9 (blue/infra), #f59e0b (amber/content), #ec4899 (pink/marketing), #a855f7 (violet/data), #14b8a6 (teal/growth).
- Schedule values: manual | hourly | 3x_daily | daily | weekly
- If autoresearch is enabled, include at least 1 query."""


def handle_setup_chat(handler, body: dict):
    """POST /de/setup-chat — conversational DE configuration assistant."""
    messages = body.get('messages', [])
    if not messages:
        return handler.send_json(400, {'ok': False, 'error': 'messages array required'})

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return handler.send_json(500, {'ok': False, 'error': 'ANTHROPIC_API_KEY not configured on the server'})

    model = os.environ.get('DE_SETUP_MODEL') or os.environ.get('DE_MODEL', 'claude-haiku-4-5')

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        full_text = resp.content[0].text if resp.content else ''

        # Extract config block if present
        config = None
        config_match = re.search(
            r'---CONFIG---\s*([\s\S]*?)\s*---END---',
            full_text,
            re.DOTALL,
        )
        if config_match:
            try:
                config = json.loads(config_match.group(1).strip())
            except json.JSONDecodeError:
                config = None  # malformed — keep chatting

        # Strip the config block from the display message
        display = re.sub(
            r'\s*---CONFIG---[\s\S]*?---END---',
            '',
            full_text,
            flags=re.DOTALL,
        ).strip()

        return handler.send_json(200, {
            'ok': True,
            'message': display,
            'config': config,
            'ready': config is not None,
        })

    except Exception as e:
        return handler.send_json(500, {'ok': False, 'error': str(e)})

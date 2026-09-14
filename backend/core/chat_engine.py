#!/usr/bin/env python3
"""
Chat Engine — lightweight conversational loop for DE Chat mode.

Key differences from ReActEngine:
  - Max 5 iterations (not 15)
  - System prompt prefixed with CHAT MODE instructions
  - Takes conversation history as input (list of {role, content} dicts)
  - Returns {message: str, tools_used: list[str]}
  - No WorkSession, no portal-inbox writes, no decisions — pure conversation

Usage:
    engine = ChatEngine('ops')
    result = engine.run(message='What do you remember?', history=[...])
    # result = {'message': 'I remember...', 'tools_used': ['read_file']}
"""

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))

CHAT_SYSTEM_PREFIX = """\
## CHAT MODE
You are in a direct conversation with the user. Rules:
- Answer the user's question directly and concisely
- Use tools ONLY when you need data to answer (don't run autonomous tasks)
- If asked to update your configuration (schedule, instructions, name, etc.) — do it via exec_shell and confirm
- Keep responses brief and conversational — no long reports
- Never say you'll do something later — either do it now or explain why not
- Max 3-4 tool calls, then answer

"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_api_key() -> str:
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if key:
        return key
    raise RuntimeError(
        'ANTHROPIC_API_KEY environment variable not set. '
        'Export it before running: export ANTHROPIC_API_KEY=sk-ant-...'
    )


class ChatEngine:
    """
    Lightweight conversational loop for DE chat mode.
    Observe → Reason → Act (max 5 iterations), then return final text.
    """

    MAX_ITERATIONS = 5

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.agent_dir = AGENTS_DIR / agent_name
        self.model = os.environ.get('DE_MODEL', 'claude-haiku-4-5')
        self._api_key = _load_api_key()
        self._client = None

    # ──────────────────────────────────────────────────────────────────────
    # Anthropic client (lazy)
    # ──────────────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError('anthropic package not installed. Run: pip install anthropic')
        return self._client

    # ──────────────────────────────────────────────────────────────────────
    # Config loading
    # ──────────────────────────────────────────────────────────────────────

    def _load_de_config(self) -> dict:
        """Load DE profile from de.json."""
        f = self.agent_dir / 'de.json'
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                pass
        return {}

    def _load_job_md(self) -> str:
        """Load job.md (mission brief), capped at 5000 chars."""
        f = self.agent_dir / 'job.md'
        if f.exists():
            return f.read_text()[:5000]
        return ''

    def _load_memory(self) -> str:
        """Load MEMORY.md from workspace, capped at 3000 chars."""
        f = self.agent_dir / 'workspace' / 'MEMORY.md'
        if f.exists():
            content = f.read_text()[:3000]
            return f'\n\n## Your Memory (MEMORY.md)\n{content}'
        return ''

    # ──────────────────────────────────────────────────────────────────────
    # System prompt
    # ──────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        de_config = self._load_de_config()
        job_md = self._load_job_md()
        memory = self._load_memory()

        display_name = de_config.get('display_name', self.agent_name.upper())
        role = de_config.get('role', 'Digital Employee')

        parts = [
            CHAT_SYSTEM_PREFIX,
            f'You are {display_name}, a Digital Employee with role: {role}.',
            '',
        ]

        if job_md:
            parts.append('## Your Mission Brief')
            parts.append(job_md)
            parts.append('')

        if memory:
            parts.append(memory)

        # Workspace path hints so the DE can read/write its own files
        workspace_dir = self.agent_dir / 'workspace'
        parts.append('')
        parts.append(f'Your workspace directory: {workspace_dir.resolve()}/')
        parts.append(f'Your config file: {self.agent_dir.resolve()}/de.json')
        parts.append(f'Your memory file: {workspace_dir.resolve()}/MEMORY.md')

        return '\n'.join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────────────────────────────

    def _get_tools(self) -> tuple:
        """Return (tools_for_api: list, tool_fns: dict)."""
        try:
            from backend.core.tool_implementations import get_tool_defs
        except ImportError:
            # Fallback when running from core/ directly
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from backend.core.tool_implementations import get_tool_defs

        de_config = self._load_de_config()
        tool_ids = de_config.get('tools', [])

        # Sensible defaults if nothing configured
        if not tool_ids:
            tool_ids = [
                'exec_shell', 'read_file', 'write_file',
                'send_telegram', 'web_search',
            ]

        tool_defs = get_tool_defs(tool_ids)

        tool_fns: dict = {}
        tools_for_api: list = []
        for t in tool_defs:
            name = t['name']
            fn = t.get('fn')
            if fn:
                tool_fns[name] = fn
            api_def = {k: v for k, v in t.items() if k != 'fn'}
            tools_for_api.append(api_def)

        return tools_for_api, tool_fns

    def _execute_tool(self, tool_name: str, tool_input: dict, tool_fns: dict) -> str:
        fn = tool_fns.get(tool_name)
        if fn is None:
            return json.dumps({'error': f'Unknown tool: {tool_name}'})
        try:
            result = fn({**tool_input, '_agent_name': self.agent_name})
            if isinstance(result, (dict, list)):
                return json.dumps(result, default=str)
            return str(result)
        except Exception as e:
            tb = traceback.format_exc()
            print(f'  [CHAT:{self.agent_name.upper()}:tool_error] {tool_name}: {e}')
            return json.dumps({'error': str(e)})

    # ──────────────────────────────────────────────────────────────────────
    # Main run
    # ──────────────────────────────────────────────────────────────────────

    def run(self, message: str, history: list) -> dict:
        """
        Run a conversational exchange.

        Args:
            message: The user's current message.
            history: List of prior {role, content} dicts (oldest first).

        Returns:
            {message: str, tools_used: list[str]}
        """
        system_prompt = self._build_system_prompt()
        tools_for_api, tool_fns = self._get_tools()
        client = self._get_client()

        # Build message array: prior history + current message
        messages = []
        for h in history:
            role = h.get('role', 'user')
            content = h.get('content', '')
            if role in ('user', 'assistant') and content:
                messages.append({'role': role, 'content': str(content)})
        messages.append({'role': 'user', 'content': message})

        tools_used: list = []
        final_text = ''
        iterations = 0

        print(f'  [CHAT:{self.agent_name.upper()}] Starting chat ({len(history)} history msgs)')

        while iterations < self.MAX_ITERATIONS:
            iterations += 1
            print(f'  [CHAT:{self.agent_name.upper()}] Iteration {iterations}/{self.MAX_ITERATIONS}')

            # ── Call Claude ───────────────────────────────────────────────
            try:
                kwargs = dict(
                    model=self.model,
                    max_tokens=2048,
                    system=system_prompt,
                    messages=messages,
                )
                if tools_for_api:
                    kwargs['tools'] = tools_for_api

                response = client.messages.create(**kwargs)
            except Exception as e:
                print(f'  [CHAT:{self.agent_name.upper()}] LLM error: {e}')
                return {'message': f'LLM error: {e}', 'tools_used': tools_used}

            stop_reason = response.stop_reason
            assistant_content = []
            tool_calls_made = []

            for block in response.content:
                if block.type == 'text':
                    final_text = block.text
                    print(f'  [CHAT:{self.agent_name.upper()}] Text: {block.text[:80]}')
                    assistant_content.append({'type': 'text', 'text': block.text})

                elif block.type == 'tool_use':
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id
                    print(f'  [CHAT:{self.agent_name.upper()}] Tool: {tool_name}')
                    tools_used.append(tool_name)
                    assistant_content.append({
                        'type': 'tool_use',
                        'id': tool_id,
                        'name': tool_name,
                        'input': tool_input,
                    })
                    tool_calls_made.append((tool_id, tool_name, tool_input))

            messages.append({'role': 'assistant', 'content': assistant_content})

            # ── Execute tools ─────────────────────────────────────────────
            if tool_calls_made:
                tool_results = []
                for tool_id, tool_name, tool_input in tool_calls_made:
                    result_str = self._execute_tool(tool_name, tool_input, tool_fns)
                    print(f'  [CHAT:{self.agent_name.upper()}] Result: {result_str[:100]}')
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_id,
                        'content': result_str,
                    })
                messages.append({'role': 'user', 'content': tool_results})
            else:
                # No tool calls — Claude gave a text answer, done
                break

        if not final_text:
            final_text = '(No response generated)'

        # Deduplicate tools_used (preserve first-seen order)
        seen = set()
        unique_tools = []
        for t in tools_used:
            if t not in seen:
                seen.add(t)
                unique_tools.append(t)

        print(f'  [CHAT:{self.agent_name.upper()}] Done. Tools used: {unique_tools}')
        return {'message': final_text, 'tools_used': unique_tools}

#!/usr/bin/env python3
"""
ReAct Engine — Reasoning and Action loop for digital employees.
Each agent runs this loop: Observe state → Reason with LLM → Act with tools → Observe result → repeat.

Usage:
    from react_engine import ReActEngine
    
    engine = ReActEngine(
        agent_name="max",
        mission="Your mission prompt here",
        tools=[...],  # list of tool defs with 'fn' key
        max_iterations=5
    )
    result = engine.run()
"""

import json
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from work_session import WorkSession
except ImportError:
    WorkSession = None  # backward compat — session support is optional

# All paths from environment variables — no hardcoded assumptions
AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", "./agents"))
PORTAL_INBOX = AGENTS_DIR / "portal-inbox.jsonl"
DECISIONS_API_URL = os.environ.get("DECISIONS_API_URL", "")


def _load_api_key() -> str:
    """Load Anthropic API key from ANTHROPIC_API_KEY environment variable."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    raise RuntimeError(
        "ANTHROPIC_API_KEY environment variable not set. "
        "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReActEngine:
    """
    Observe → Reason → Act loop using Anthropic's tool-calling API.
    
    Each iteration:
      1. Observe: current messages state (includes prior tool results)
      2. Reason: call Claude with tool definitions → get next action
      3. Act: execute the chosen tool → append result to messages
      4. Repeat until complete, human_decision_needed, or max_iterations
    """

    def __init__(
        self,
        agent_name: str,
        mission: str,
        tools: list,
        max_iterations: int = 5,
        model: str = None,  # defaults to DE_MODEL env var, then claude-haiku-4-5
        session=None,  # optional WorkSession instance
    ):
        self.agent_name = agent_name
        self.mission = mission
        self.max_iterations = max_iterations
        self.model = model or os.environ.get("DE_MODEL", "claude-haiku-4-5")

        # Session tracking (optional — backward compat)
        self.session = session  # WorkSession instance or None

        # Agent-specific paths
        self.agent_dir = AGENTS_DIR / agent_name
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.agent_dir / "log.jsonl"
        self.decisions_file = self.agent_dir / "decisions.json"

        # Build tool registry
        self._tool_fns: dict = {}
        self._tools_for_api: list = []
        self._register_tools(tools)

        # Always add the human-in-loop tool
        self._register_human_decision_tool()

        # Always add the ask-colleague tool
        self._register_ask_colleague_tool()

        # Always add the write_metric tool (agent-context-aware)
        self._register_write_metric_tool()

        # Build system prompt (includes KPI list from metrics.json)
        self._system_prompt = self._build_system_prompt()

        # Load Anthropic client
        self._api_key = _load_api_key()
        self._client = None  # lazy init

    # ─────────────────────────────────────────────────────────────────────
    # Tool registration
    # ─────────────────────────────────────────────────────────────────────

    def _register_tools(self, tools: list):
        for tool in tools:
            name = tool["name"]
            fn = tool.get("fn")
            if fn:
                self._tool_fns[name] = fn
            # Strip 'fn' for API
            api_def = {k: v for k, v in tool.items() if k != "fn"}
            self._tools_for_api.append(api_def)

    def _register_human_decision_tool(self):
        human_tool = {
            "name": "request_human_decision",
            "description": (
                "Request a human decision for a Level 2 action. "
                "Use when the action requires human approval before proceeding."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "proposed_action": {"type": "string"},
                    "estimated_impact": {"type": "string"},
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
                "required": ["title", "description", "proposed_action"],
            },
        }
        self._tool_fns["request_human_decision"] = self._handle_human_decision
        # Only add to API list if not already registered by _register_tools
        if not any(t.get('name') == 'request_human_decision' for t in self._tools_for_api):
            self._tools_for_api.append(human_tool)

    def _register_write_metric_tool(self):
        write_metric_tool = {
            'name': 'write_metric',
            'description': (
                'Record a KPI metric value for this DE. '
                'Call at end of session for each KPI you directly measured or have data for.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'kpi_id': {
                        'type': 'string',
                        'description': 'KPI id (see Your KPIs section in system instructions)',
                    },
                    'value': {
                        'type': 'number',
                        'description': 'Current measured value',
                    },
                    'notes': {
                        'type': 'string',
                        'description': 'Brief note on how you measured this',
                    },
                },
                'required': ['kpi_id', 'value'],
            },
        }
        self._tool_fns['write_metric'] = self._handle_write_metric
        # Only add to API list if not already registered by _register_tools
        if not any(t.get('name') == 'write_metric' for t in self._tools_for_api):
            self._tools_for_api.append(write_metric_tool)

    def _register_ask_colleague_tool(self):
        colleague_tool = {
            "name": "ask_colleague",
            "description": (
                "Send a message to another Digital Employee (colleague) via their inbox. "
                "Use for cross-agent coordination. Max 3 calls per colleague per session to avoid deadlocks."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "colleague": {
                        "type": "string",
                        "description": "Name of the colleague DE (e.g. 'ops', 'flow', 'shield')",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to send to the colleague",
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context about why you're asking",
                    },
                },
                "required": ["colleague", "message"],
            },
        }
        self._tool_fns["ask_colleague"] = self._handle_ask_colleague
        # Only add to API list if not already registered by _register_tools
        if not any(t.get('name') == 'ask_colleague' for t in self._tools_for_api):
            self._tools_for_api.append(colleague_tool)

    def _handle_write_metric(self, input_data: dict) -> dict:
        """Write a KPI metric value to this agent's metrics.json."""
        kpi_id = (input_data.get('kpi_id') or '').strip()
        value = input_data.get('value')
        notes = input_data.get('notes', '')

        if not kpi_id:
            return {'error': 'kpi_id is required'}
        if value is None:
            return {'error': 'value is required'}
        try:
            value = float(value)
        except (TypeError, ValueError):
            return {'error': 'value must be a number'}

        metrics_file = self.agent_dir / 'metrics.json'
        try:
            data = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}
        except Exception:
            data = {}

        kpis = data.get('kpis', [])

        # Find existing KPI entry or create new one
        kpi_entry = next((k for k in kpis if k.get('id') == kpi_id), None)
        if kpi_entry is None:
            kpi_entry = {
                'id': kpi_id,
                'name': kpi_id.replace('_', ' ').title(),
                'value': None,
                'target': None,
                'unit': '',
                'direction': 'up',
                'history': [],
            }
            kpis.append(kpi_entry)

        # Append to history, cap at 90 entries
        hist_entry = {'ts': _now_iso(), 'value': value}
        if notes:
            hist_entry['notes'] = notes
        history = kpi_entry.get('history', [])
        history.append(hist_entry)
        kpi_entry['history'] = history[-90:]
        kpi_entry['value'] = value

        data['kpis'] = kpis
        data['updated'] = _now_iso()

        try:
            metrics_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            return {'error': f'Failed to write metrics.json: {e}'}

        self._log({'type': 'metric_written', 'kpi_id': kpi_id, 'value': value})
        print(f'  [{self.agent_name.upper()}:METRIC] {kpi_id} = {value}')

        return {
            'ok': True,
            'kpi_id': kpi_id,
            'value': value,
            'history_count': len(kpi_entry['history']),
        }

    def _load_workspace_context(self) -> str:
        """Load relevant workspace files to inject into session context."""
        workspace = self.agent_dir / 'workspace'
        if not workspace.exists():
            return ''

        lines = []
        # Priority order: MEMORY.md first, then README.md, TODO.md, other .md files
        priority = ['MEMORY.md', 'README.md', 'TODO.md']
        found = set()

        for fname in priority:
            fpath = workspace / fname
            if fpath.exists():
                content = fpath.read_text(errors='replace')[:3000]  # cap at 3000 chars
                lines.append(f'### {fname}\n{content}')
                found.add(fname)

        # Add other .md files (up to 2 more, capped at 1500 chars each)
        count = 0
        for fpath in sorted(workspace.glob('*.md')):
            if fpath.name not in found and count < 2:
                content = fpath.read_text(errors='replace')[:1500]
                lines.append(f'### {fpath.name}\n{content}')
                count += 1

        if not lines:
            return ''

        return '\n\n## Your Workspace\n' + '\n\n'.join(lines)

    def _build_system_prompt(self) -> str:
        """Build system prompt including KPI list and workspace context for this agent."""
        lines = [
            f'You are {self.agent_name.upper()}, a Digital Employee in an autonomous AI team.',
            'Operate as a professional ReAct agent: think step by step, use tools to gather real data, and produce concrete results.',
            'Be thorough but efficient. Document what you find.',
        ]

        # Load structured KPIs from metrics.json
        metrics_file = self.agent_dir / 'metrics.json'
        kpis = []
        try:
            if metrics_file.exists():
                kpis = json.loads(metrics_file.read_text()).get('kpis', [])
        except Exception:
            pass

        if kpis:
            lines.append('')
            lines.append('## Your KPIs')
            for kpi in kpis:
                name = kpi.get('name', kpi.get('id', 'KPI'))
                target = kpi.get('target')
                unit = kpi.get('unit', '')
                direction = kpi.get('direction', 'up')
                kpi_id = kpi.get('id', '')
                target_str = ''
                if target is not None:
                    target_str = f' (target: {target}{" " + unit if unit else ""}, {direction})'
                lines.append(f'- {name}{target_str}  [id: {kpi_id}]')

        lines.extend([
            '',
            'At the end of your session, for each KPI you directly measured or have data for, '
            'call write_metric(kpi_id, value) to record it. '
            "Only write metrics you actually measured in this session — don't guess.",
        ])

        # Workspace context (MEMORY.md and other .md files)
        workspace_context = self._load_workspace_context()
        if workspace_context:
            lines.append(workspace_context)

        # Workspace path + memory guidance (only when workspace exists)
        workspace_dir = self.agent_dir / 'workspace'
        if workspace_dir.exists():
            workspace_abs = str(workspace_dir.resolve())
            lines.append('')
            lines.append(f'Your workspace directory: {workspace_abs}/')
            lines.append('')
            lines.append('## Your Memory File')
            lines.append('')
            lines.append('You have a MEMORY.md in your workspace. Write important facts, decisions, and progress there:')
            lines.append('- Key facts about ongoing projects')
            lines.append('- Decisions made and why')
            lines.append('- What you learned in this session')
            lines.append('- What you plan to do next session')
            lines.append('')
            lines.append(f'Write to it using: write_file(path=\'{workspace_abs}/MEMORY.md\', content=\'...\')')
            lines.append('Read it at session start (it will be in the Your Workspace section above).')

        # QA step — mandatory last step for every DE
        lines.append('')
        lines.append('## Quality Assurance — Mandatory Last Step')
        lines.append('')
        lines.append('Before ending this session, always run a self-QA check:')
        lines.append('1. Did I complete the task I was given? (yes/no — if no, say what\'s missing)')
        lines.append('2. Is my output correct and verifiable? (check key facts, numbers, conclusions)')
        lines.append('3. Are there any errors or warnings I should flag to the human?')
        lines.append('4. Is there anything I should write to my MEMORY.md for next time?')
        lines.append('')
        lines.append('Only after completing QA: use report_to_colleague or write your session summary.')
        lines.append('Human time is the most valuable resource — only escalate if output is verified.')

        return '\n'.join(lines)

    # ─────────────────────────────────────────────────────────────────────
    # Anthropic client (lazy)
    # ─────────────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    # ─────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────

    def _log(self, entry: dict):
        entry["ts"] = _now_iso()
        entry["agent"] = self.agent_name
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        # Also print to stdout for visibility
        label = entry.get("type", "log")
        content = entry.get("content") or entry.get("tool") or entry.get("message", "")
        print(f"  [{self.agent_name.upper()}:{label}] {str(content)[:120]}")

    # ─────────────────────────────────────────────────────────────────────
    # Tool execution
    # ─────────────────────────────────────────────────────────────────────

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        fn = self._tool_fns.get(tool_name)
        if fn is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = fn(tool_input)
            if isinstance(result, (dict, list)):
                return json.dumps(result, default=str)
            return str(result)
        except Exception as e:
            tb = traceback.format_exc()
            self._log({"type": "tool_error", "tool": tool_name, "error": str(e), "traceback": tb})
            return json.dumps({"error": str(e)})

    # ─────────────────────────────────────────────────────────────────────
    # Human-in-loop handler
    # ─────────────────────────────────────────────────────────────────────

    def _validate_decision(self, decision_data: dict) -> list:
        """Ensure decision has enough context for voice review."""
        required = ['title', 'description', 'proposed_action']
        issues = []
        for field in required:
            if not decision_data.get(field, '').strip():
                issues.append(f"Missing {field}")
        if len(decision_data.get('title', '')) > 80:
            issues.append("Title too long (max 80 chars)")
        if 'approve' in decision_data.get('description', '').lower() and len(decision_data.get('description', '')) < 50:
            issues.append("Description too vague")
        # Check for batch language
        batch_words = ['all', 'multiple', 'various', 'several', 'many', 'batch', 'bulk']
        title_lower = decision_data.get('title', '').lower()
        if any(word in title_lower for word in batch_words) and 'experiments' in title_lower:
            issues.append("Batch decisions not allowed - split into individual decisions")
        return issues

    def _handle_human_decision(self, input_data: dict) -> dict:
        """Write decision to agent decisions.json and portal-inbox.jsonl."""
        # Validate decision quality before writing
        issues = self._validate_decision(input_data)
        if issues:
            issue_list = "; ".join(issues)
            self._log({
                "type": "decision_validation_failed",
                "issues": issues,
                "input": input_data,
            })
            print(f"  [{self.agent_name.upper()}:DECISION_REJECTED] Validation failed: {issue_list}")
            return {
                "status": "decision_rejected",
                "message": f"Decision rejected: {issue_list}. Please rewrite with more specific context.",
                "issues": issues,
            }

        # Load existing decisions
        try:
            decisions = json.loads(self.decisions_file.read_text())
        except Exception:
            decisions = {"pending": [], "resolved": []}

        decision_id = f"{self.agent_name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        item = {
            "id": decision_id,
            "agent": self.agent_name,
            "level": 2,
            "title": input_data.get("title", "Decision needed"),
            "description": input_data.get("description", ""),
            "proposed_action": input_data.get("proposed_action", ""),
            "estimated_impact": input_data.get("estimated_impact", ""),
            "urgency": input_data.get("urgency", "medium"),
            "created_at": _now_iso(),
            "status": "pending",
        }
        decisions["pending"].append(item)
        self.decisions_file.write_text(json.dumps(decisions, indent=2))

        # Write to portal inbox
        portal_entry = {
            "ts": _now_iso(),
            "agent": self.agent_name,
            "level": 2,
            "type": "approval_request",
            "decision_id": decision_id,
            "title": f"⏳ APPROVAL NEEDED: {item['title']}",
            "body": f"{item['description']}\n\nProposed: {item['proposed_action']}\n\nImpact: {item.get('estimated_impact','N/A')}",
            "urgency": item["urgency"],
            "status": "pending",
        }
        PORTAL_INBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(PORTAL_INBOX, "a") as f:
            f.write(json.dumps(portal_entry) + "\n")

        # Notify decisions API if DECISIONS_API_URL is configured
        if DECISIONS_API_URL:
            try:
                import urllib.request
                ingest_url = DECISIONS_API_URL.rstrip("/") + "/ingest"
                req = urllib.request.Request(
                    ingest_url,
                    data=json.dumps(portal_entry).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=3)
            except Exception:
                pass  # API not available — decisions still written to disk

        # Track in session
        if self.session is not None:
            self.session.add_decision_id(decision_id)
            self.session.add_step(
                "decision_request",
                decision_id=decision_id,
                title=item["title"][:200],
            )

        print(f"  [{self.agent_name.upper()}:HUMAN_DECISION] Written decision {decision_id}")
        return {"status": "decision_logged", "decision_id": decision_id, "message": "Human decision requested. Agent will pause."}

    # ─────────────────────────────────────────────────────────────────────
    # Colleague handler
    # ─────────────────────────────────────────────────────────────────────

    def _handle_ask_colleague(self, input_data: dict) -> dict:
        """Write to colleague inbox.jsonl. Track call count for deadlock detection."""
        colleague = input_data.get("colleague", "").lower().strip()
        message = input_data.get("message", "")
        context = input_data.get("context", "")

        if not colleague or not message:
            return {"error": "colleague and message are required"}

        # Track call count via session (deadlock detection)
        call_count = 1
        if self.session is not None:
            call_count = self.session.track_colleague_call(colleague)
            if call_count > 3:
                return {
                    "error": f"Deadlock guard: already called {colleague} {call_count - 1} times this session. Max 3.",
                    "action": "stop_and_pause",
                }
            self.session.add_step(
                "colleague_request",
                colleague=colleague,
                message=message[:500],
                call_count=call_count,
            )

        # Write to colleague's inbox.jsonl
        colleague_inbox = AGENTS_DIR / colleague / "inbox.jsonl"
        colleague_inbox.parent.mkdir(parents=True, exist_ok=True)

        session_id = self.session.id if self.session else None
        entry = {
            "ts": _now_iso(),
            "from": self.agent_name,
            "session_id": session_id,
            "message": message,
            "context": context,
            "status": "pending",
        }
        with open(colleague_inbox, "a") as f:
            f.write(json.dumps(entry) + "\n")

        self._log({"type": "colleague_request", "colleague": colleague, "message": message[:100]})
        print(f"  [{self.agent_name.upper()}:COLLEAGUE] Asked {colleague}: {message[:80]}")

        return {
            "status": "message_sent",
            "colleague": colleague,
            "message": "Message delivered to colleague inbox. Agent will check response on next run.",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Run the ReAct loop.
        Returns a summary dict with status, iterations, and findings.
        """
        print(f"\n{'='*60}")
        print(f"  ReAct Engine — {self.agent_name.upper()}")
        print(f"  {_now_iso()}")
        print(f"{'='*60}")

        self._log({"type": "run_start", "message": f"ReAct loop starting. Mission: {self.mission[:80]}"})

        # Session: log trigger step
        if self.session is not None:
            self.session.add_step("trigger", content=self.mission[:300])

        messages = [
            {"role": "user", "content": self.mission}
        ]

        iterations = 0
        final_status = "max_iterations_reached"
        summary = None
        stop_reason = None

        client = self._get_client()

        while iterations < self.max_iterations:
            iterations += 1
            print(f"\n--- Iteration {iterations}/{self.max_iterations} ---")
            self._log({"type": "iteration", "content": f"Iteration {iterations}"})

            # ── Reason: call Claude ──────────────────────────────────────
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self._system_prompt,
                    tools=self._tools_for_api,
                    messages=messages,
                )
            except Exception as e:
                self._log({"type": "llm_error", "message": str(e)})
                print(f"  [ERROR] LLM call failed: {e}")
                final_status = "llm_error"
                if self.session is not None:
                    self.session.set_status("error")
                break

            stop_reason = response.stop_reason
            self._log({
                "type": "llm_response",
                "stop_reason": stop_reason,
                "content_blocks": len(response.content),
            })

            # ── Process response content ─────────────────────────────────
            # Collect assistant message content
            assistant_content = []
            tool_calls_made = []

            for block in response.content:
                if block.type == "text":
                    text = block.text
                    print(f"  [THOUGHT] {text[:200]}")
                    self._log({"type": "thought", "content": text})
                    assistant_content.append({"type": "text", "text": text})
                    # Session: log reasoning block
                    if self.session is not None:
                        self.session.add_step("reasoning", content=text)

                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    print(f"  [ACTION] {tool_name}({json.dumps(tool_input, default=str)[:100]})")
                    self._log({"type": "action", "tool": tool_name, "input": tool_input})
                    # Session: log action
                    if self.session is not None:
                        self.session.add_step("action", tool=tool_name, input=json.dumps(tool_input, default=str)[:500])

                    assistant_content.append({
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                    })
                    tool_calls_made.append((tool_id, tool_name, tool_input))

            # Add assistant message to history
            messages.append({"role": "assistant", "content": assistant_content})

            # ── Act: execute tools ───────────────────────────────────────
            if tool_calls_made:
                tool_results = []
                human_decision_triggered = False

                for tool_id, tool_name, tool_input in tool_calls_made:
                    result_str = self._execute_tool(tool_name, tool_input)
                    print(f"  [OBSERVATION] {result_str[:200]}")
                    self._log({"type": "observation", "tool": tool_name, "result": result_str[:500]})
                    # Session: log observation
                    if self.session is not None:
                        self.session.add_step("observation", tool=tool_name, result=result_str[:500])

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str,
                    })

                    # Check if human decision was requested → stop after this iteration
                    if tool_name == "request_human_decision":
                        human_decision_triggered = True

                messages.append({"role": "user", "content": tool_results})

                if human_decision_triggered:
                    final_status = "human_decision_needed"
                    # Session: save paused state for human review
                    if self.session is not None:
                        self.session.set_status("paused_human")
                        self.session.save_paused_state(messages, iterations, "human")
                    break

            # ── Check if done ────────────────────────────────────────────
            if stop_reason in ("end_turn", "max_tokens") and not tool_calls_made:
                # No more tool calls — agent is done
                final_status = "complete"
                # Extract final summary text
                for block in response.content:
                    if block.type == "text":
                        summary = block.text
                        break
                break

        # ── Write final summary to portal ────────────────────────────────
        self._write_completion_summary(final_status, iterations, summary)
        self._log({
            "type": "run_end",
            "status": final_status,
            "iterations": iterations,
        })

        # ── Session: mark complete ────────────────────────────────────────
        if self.session is not None and final_status not in ("human_decision_needed", "llm_error"):
            self.session.set_status(
                "complete" if final_status == "complete" else final_status,
                summary=summary
            )
            self.session.add_step("complete", summary=summary or "")

        print(f"\n{'='*60}")
        print(f"  ReAct loop complete: {final_status} ({iterations} iterations)")
        print(f"{'='*60}\n")

        return {
            "status": final_status,
            "iterations": iterations,
            "agent": self.agent_name,
            "summary": summary,
        }

    def _write_completion_summary(self, status: str, iterations: int, summary: str = None):
        """Write a run summary to portal-inbox.jsonl."""
        status_emoji = {
            "complete": "✅",
            "human_decision_needed": "⏳",
            "max_iterations_reached": "🔄",
            "llm_error": "❌",
        }.get(status, "ℹ️")

        entry = {
            "ts": _now_iso(),
            "agent": self.agent_name,
            "level": 0,
            "type": "react_run_complete",
            "title": f"{status_emoji} {self.agent_name.upper()} ReAct run — {status}",
            "body": summary or f"Completed in {iterations} iterations. Status: {status}",
            "iterations": iterations,
            "status": status,
        }
        PORTAL_INBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(PORTAL_INBOX, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # Update metrics after run completes
        self._update_metrics(summary or "")

    def _update_metrics(self, summary: str):
        """Update metrics.json after a session completes."""
        import re
        metrics_file = self.agent_dir / "metrics.json"

        try:
            data = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}
        except Exception:
            data = {}

        data["updated"] = _now_iso()

        # For OPS: extract uptime % from summary text
        if self.agent_name == "ops" and summary:
            match = re.search(
                r'(\d+)\s*/\s*(\d+)\s*services?\s*(?:UP|up|running|ok)?',
                summary,
                re.IGNORECASE,
            )
            if match:
                n, m = int(match.group(1)), int(match.group(2))
                if m > 0:
                    uptime_pct = round((n / m) * 100, 1)
                    kpis = data.get("kpis", [])
                    uptime_kpi = next((k for k in kpis if k.get("id") == "uptime"), None)
                    if not uptime_kpi:
                        uptime_kpi = {
                            "id": "uptime",
                            "name": "Uptime %",
                            "value": None,
                            "target": 99.9,
                            "unit": "%",
                            "direction": "up",
                            "history": [],
                        }
                        kpis.append(uptime_kpi)
                    uptime_kpi["value"] = uptime_pct
                    history = uptime_kpi.get("history", [])
                    history.append({"ts": _now_iso(), "value": uptime_pct})
                    uptime_kpi["history"] = history[-30:]
                    data["kpis"] = kpis

        try:
            metrics_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            self._log({"type": "metrics_error", "message": str(e)})

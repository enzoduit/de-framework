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
        self._tools_for_api.append(human_tool)

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
        self._tools_for_api.append(colleague_tool)

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
                    max_tokens=1024,
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
            if stop_reason == "end_turn" and not tool_calls_made:
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

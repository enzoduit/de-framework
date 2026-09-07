#!/usr/bin/env python3
"""
ReAct Engine (OpenAI-compatible) — for Digital Employees.
Uses OpenClaw Gateway's OpenAI-compatible chat completions endpoint with tool calling.
Same interface as react_engine.py but routes through OpenClaw instead of Anthropic directly.

Tool format: OpenAI function calling (tool_calls/tool results).
"""

import json
import os
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", "/var/de-agents"))
PORTAL_INBOX = AGENTS_DIR / "portal-inbox.jsonl"

OPENCLAW_GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
OPENCLAW_GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
# Model routed through OpenClaw gateway — always use openclaw/default
GATEWAY_MODEL = "openclaw/default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReActEngineOpenAI:
    """
    ReAct loop using OpenAI-compatible chat completions (routed through OpenClaw gateway).
    Compatible interface with ReActEngine — drops in as replacement.
    """

    def __init__(
        self,
        agent_name: str,
        mission: str,
        tools: list,
        max_iterations: int = 8,
        model: str = None,  # ignored — always uses gateway model
        session=None,
    ):
        self.agent_name = agent_name
        self.mission = mission
        self.max_iterations = max_iterations
        self.session = session

        self.agent_dir = AGENTS_DIR / agent_name
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.agent_dir / "log.jsonl"
        self.decisions_file = self.agent_dir / "decisions.json"

        # Build tool registry
        self._tool_fns: dict = {}
        self._tools_for_api: list = []
        self._register_tools(tools)
        self._register_builtin_tools()

        # Lazy OpenAI client
        self._client = None

    # ─────────────────────────────────────────────────────────────────────
    # Tool registration
    # ─────────────────────────────────────────────────────────────────────

    def _register_tools(self, tools: list):
        for tool in tools:
            name = tool["name"]
            fn = tool.get("fn")
            if fn:
                self._tool_fns[name] = fn
            # Build OpenAI function spec
            self._tools_for_api.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            })

    def _register_builtin_tools(self):
        """Register request_human_decision and ask_colleague."""
        self._tool_fns["request_human_decision"] = self._handle_human_decision
        self._tools_for_api.append({
            "type": "function",
            "function": {
                "name": "request_human_decision",
                "description": "Request a human decision for a Level 2 action requiring approval.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "proposed_action": {"type": "string"},
                        "estimated_impact": {"type": "string"},
                        "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["title", "description", "proposed_action"],
                },
            },
        })

        self._tool_fns["ask_colleague"] = self._handle_ask_colleague
        self._tools_for_api.append({
            "type": "function",
            "function": {
                "name": "ask_colleague",
                "description": "Send a message to another Digital Employee via their inbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "colleague": {"type": "string"},
                        "message": {"type": "string"},
                        "context": {"type": "string"},
                    },
                    "required": ["colleague", "message"],
                },
            },
        })

    # ─────────────────────────────────────────────────────────────────────
    # OpenAI client (lazy, pointing at OpenClaw gateway)
    # ─────────────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=f"{OPENCLAW_GATEWAY_URL}/v1",
                    api_key=OPENCLAW_GATEWAY_TOKEN,
                )
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")
        return self._client

    # ─────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────

    def _log(self, entry: dict):
        entry["ts"] = _now_iso()
        entry["agent"] = self.agent_name
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        label = entry.get("type", "log")
        content = entry.get("content") or entry.get("tool") or entry.get("message", "")
        print(f"  [{self.agent_name.upper()}:{label}] {str(content)[:120]}")

    # ─────────────────────────────────────────────────────────────────────
    # Tool execution
    # ─────────────────────────────────────────────────────────────────────

    def _execute_tool(self, tool_name: str, arguments_str: str) -> str:
        fn = self._tool_fns.get(tool_name)
        if fn is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            tool_input = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
            result = fn(tool_input)
            if isinstance(result, (dict, list)):
                return json.dumps(result, default=str)
            return str(result)
        except Exception as e:
            tb = traceback.format_exc()
            self._log({"type": "tool_error", "tool": tool_name, "error": str(e)})
            return json.dumps({"error": str(e)})

    # ─────────────────────────────────────────────────────────────────────
    # Built-in tool handlers
    # ─────────────────────────────────────────────────────────────────────

    def _handle_human_decision(self, input_data: dict) -> dict:
        """Write decision to decisions.json and portal-inbox.jsonl."""
        try:
            decisions = json.loads(self.decisions_file.read_text())
        except Exception:
            decisions = {"pending": [], "resolved": []}

        from datetime import datetime, timezone
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

        portal_entry = {
            "ts": _now_iso(), "agent": self.agent_name, "level": 2,
            "type": "approval_request", "decision_id": decision_id,
            "title": f"⏳ APPROVAL NEEDED: {item['title']}",
            "body": f"{item['description']}\n\nProposed: {item['proposed_action']}",
            "urgency": item["urgency"], "status": "pending",
        }
        PORTAL_INBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(PORTAL_INBOX, "a") as f:
            f.write(json.dumps(portal_entry) + "\n")

        if self.session is not None:
            self.session.add_decision_id(decision_id)
            self.session.add_step("decision_request", decision_id=decision_id, title=item["title"][:200])

        print(f"  [{self.agent_name.upper()}:HUMAN_DECISION] Written decision {decision_id}")
        return {"status": "decision_logged", "decision_id": decision_id}

    def _handle_ask_colleague(self, input_data: dict) -> dict:
        colleague = input_data.get("colleague", "").lower().strip()
        message = input_data.get("message", "")
        context = input_data.get("context", "")
        if not colleague or not message:
            return {"error": "colleague and message are required"}

        call_count = 1
        if self.session is not None:
            call_count = self.session.track_colleague_call(colleague)
            if call_count > 3:
                return {"error": f"Deadlock guard: called {colleague} {call_count-1} times already."}
            self.session.add_step("colleague_request", colleague=colleague, message=message[:500], call_count=call_count)

        colleague_inbox = AGENTS_DIR / colleague / "inbox.jsonl"
        colleague_inbox.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now_iso(), "from": self.agent_name,
            "session_id": self.session.id if self.session else None,
            "message": message, "context": context, "status": "pending",
        }
        with open(colleague_inbox, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return {"status": "message_sent", "colleague": colleague}

    # ─────────────────────────────────────────────────────────────────────
    # Main ReAct loop
    # ─────────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        print(f"\n{'='*60}")
        print(f"  ReAct Engine (OpenAI compat) — {self.agent_name.upper()}")
        print(f"  {_now_iso()}")
        print(f"{'='*60}")

        self._log({"type": "run_start", "message": f"ReAct loop starting. Mission: {self.mission[:80]}"})

        if self.session is not None:
            self.session.add_step("trigger", content=self.mission[:300])

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a Digital Employee: {self.agent_name}. "
                    "Execute your mission using the available tools. "
                    "Think step by step. Use tools to gather information before reporting. "
                    "When done, provide a clear summary of what you did and found."
                ),
            },
            {"role": "user", "content": self.mission},
        ]

        iterations = 0
        final_status = "max_iterations_reached"
        summary = None
        human_decision_triggered = False

        client = self._get_client()

        while iterations < self.max_iterations:
            iterations += 1
            print(f"\n--- Iteration {iterations}/{self.max_iterations} ---")
            self._log({"type": "iteration", "content": f"Iteration {iterations}"})

            # ── Reason: call LLM ────────────────────────────────────────
            try:
                response = client.chat.completions.create(
                    model=GATEWAY_MODEL,
                    max_tokens=1500,
                    tools=self._tools_for_api,
                    tool_choice="auto",
                    messages=messages,
                    timeout=90,
                )
            except Exception as e:
                self._log({"type": "llm_error", "message": str(e)})
                print(f"  [ERROR] LLM call failed: {e}")
                final_status = "llm_error"
                if self.session is not None:
                    self.session.set_status("error")
                break

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            msg = choice.message

            # ── Log text reasoning ──────────────────────────────────────
            if msg.content:
                text = msg.content
                print(f"  [THOUGHT] {text[:200]}")
                self._log({"type": "thought", "content": text})
                if self.session is not None:
                    self.session.add_step("reasoning", content=text)

            # ── Add assistant message to history ────────────────────────
            # Convert to dict for message history
            assistant_msg = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            # ── Act: execute tool calls ─────────────────────────────────
            if msg.tool_calls:
                tool_results = []
                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    args_str = tc.function.arguments

                    print(f"  [ACTION] {tool_name}({args_str[:100]})")
                    self._log({"type": "action", "tool": tool_name, "input": args_str[:500]})
                    if self.session is not None:
                        self.session.add_step("action", tool=tool_name, input=args_str[:500])

                    result_str = self._execute_tool(tool_name, args_str)

                    print(f"  [OBSERVATION] {result_str[:200]}")
                    self._log({"type": "observation", "tool": tool_name, "result": result_str[:500]})
                    if self.session is not None:
                        self.session.add_step("observation", tool=tool_name, result=result_str[:500])

                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })

                    if tool_name == "request_human_decision":
                        human_decision_triggered = True

                messages.extend(tool_results)

                if human_decision_triggered:
                    final_status = "human_decision_needed"
                    if self.session is not None:
                        self.session.set_status("paused_human")
                        self.session.save_paused_state(messages, iterations, "human")
                    break

            # ── Check done ──────────────────────────────────────────────
            if finish_reason == "stop" and not msg.tool_calls:
                final_status = "complete"
                summary = msg.content or ""
                break

        # ── Write summary to portal inbox ────────────────────────────────
        self._write_completion_summary(final_status, iterations, summary)
        self._log({"type": "run_end", "status": final_status, "iterations": iterations})

        if self.session is not None and final_status not in ("human_decision_needed", "llm_error"):
            self.session.set_status(
                "complete" if final_status == "complete" else final_status,
                summary=summary,
            )
            self.session.add_step("complete", summary=summary or "")

        print(f"\n{'='*60}")
        print(f"  ReAct loop done: {final_status} ({iterations} iterations)")
        print(f"{'='*60}\n")

        return {
            "status": final_status,
            "iterations": iterations,
            "agent": self.agent_name,
            "summary": summary,
        }

    def _write_completion_summary(self, status: str, iterations: int, summary: str = None):
        status_emoji = {
            "complete": "✅", "human_decision_needed": "⏳",
            "max_iterations_reached": "🔄", "llm_error": "❌",
        }.get(status, "ℹ️")
        entry = {
            "ts": _now_iso(), "agent": self.agent_name, "level": 0,
            "type": "react_run_complete",
            "title": f"{status_emoji} {self.agent_name.upper()} — {status}",
            "body": summary or f"Completed in {iterations} iterations. Status: {status}",
            "iterations": iterations, "status": status,
        }
        PORTAL_INBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(PORTAL_INBOX, "a") as f:
            f.write(json.dumps(entry) + "\n")

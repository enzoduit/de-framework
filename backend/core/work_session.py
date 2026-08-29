#!/usr/bin/env python3
"""
WorkSession — Persistent session file manager for Digital Employees.
Sessions stored as JSON at agents/<name>/sessions/<session_id>.json

Session lifecycle:
  running → complete | paused_human | paused_colleague | error
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("/root/.openclaw/workspace")
AGENTS_DIR = WORKSPACE / "agents"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_session_id(de_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"ws-{de_name}-{ts}-{short}"


class WorkSession:
    """
    Manages a persistent session file for a Digital Employee run.

    Usage:
        # New session
        session = WorkSession("max", "cron", None, "Scheduled daily run")

        # Load existing
        session = WorkSession("max", "cron", None, "", session_id="ws-max-20260827-...")

        # Log steps
        session.add_step("trigger", content="Starting cost analysis...")
        session.add_step("reasoning", content="I see spend is $12 today...")
        session.add_step("action", tool="read_costs", input={"date": "today"})
        session.add_step("observation", tool="read_costs", result="$12.34")

        # Complete
        session.set_status("complete", summary="All costs within budget.")
    """

    def __init__(
        self,
        de_name: str,
        trigger_type: str,
        trigger_from: str = None,
        trigger_context: str = "",
        session_id: str = None,
    ):
        self.de_name = de_name
        self._sessions_dir = AGENTS_DIR / de_name / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        if session_id:
            # Load existing session by ID
            session_file = self._sessions_dir / f"{session_id}.json"
            if session_file.exists():
                self._data = json.loads(session_file.read_text())
                self._file = session_file
            else:
                raise FileNotFoundError(
                    f"Session {session_id} not found at {session_file}"
                )
        else:
            # Create new session
            new_id = _gen_session_id(de_name)
            self._file = self._sessions_dir / f"{new_id}.json"
            self._data = {
                "id": new_id,
                "de": de_name,
                "trigger_type": trigger_type,
                "trigger_from": trigger_from,
                "trigger_context": trigger_context,
                "status": "running",
                "decision_ids": [],
                "colleague_calls": {},
                "steps": [],
                "paused_state": None,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "summary": None,
            }
            self._save()

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def data(self) -> dict:
        return self._data

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save(self):
        self._data["updated_at"] = _now_iso()
        self._file.write_text(json.dumps(self._data, indent=2, default=str))

    # ── Step Management ──────────────────────────────────────────────────────

    def add_step(self, step_type: str, **kwargs):
        """
        Append a step to the session and save immediately.

        Step types:
          trigger    — initial mission context
          reasoning  — LLM thought block
          action     — tool call (kwargs: tool, input)
          observation — tool result (kwargs: tool, result)
          decision_request — Level 2 decision created (kwargs: decision_id, title)
          colleague_request — ask_colleague sent (kwargs: colleague, message)
          colleague_response — colleague replied (kwargs: colleague, response)
          complete   — session done (kwargs: summary)
        """
        step = {"type": step_type, "ts": _now_iso()}
        step.update(kwargs)
        self._data["steps"].append(step)
        self._save()

    # ── Status ───────────────────────────────────────────────────────────────

    def set_status(self, status: str, summary: str = None):
        """Update session status. Optionally set summary. Saves immediately."""
        self._data["status"] = status
        if summary is not None:
            self._data["summary"] = summary
        self._save()

    # ── Pause / Resume ───────────────────────────────────────────────────────

    def save_paused_state(self, messages: list, iterations: int, pause_type: str):
        """
        Persist the current LLM conversation context so the session can resume.

        pause_type: "human" | "colleague"
        """
        self._data["paused_state"] = {
            "messages": messages,
            "iterations": iterations,
            "pause_type": pause_type,
            "paused_at": _now_iso(),
        }
        self._save()

    def get_paused_state(self) -> dict | None:
        """Return saved paused state or None if not paused."""
        return self._data.get("paused_state")

    def clear_paused_state(self):
        """Clear paused state after resuming."""
        self._data["paused_state"] = None
        self._save()

    # ── Colleague Tracking ───────────────────────────────────────────────────

    def track_colleague_call(self, colleague_name: str) -> int:
        """
        Increment the call count to a colleague.
        Returns the new count. Used for deadlock detection (max 3).
        """
        calls = self._data.setdefault("colleague_calls", {})
        calls[colleague_name] = calls.get(colleague_name, 0) + 1
        self._save()
        return calls[colleague_name]

    # ── Decision Tracking ────────────────────────────────────────────────────

    def add_decision_id(self, decision_id: str):
        """Track a linked decision ID created during this session."""
        ids = self._data.setdefault("decision_ids", [])
        if decision_id not in ids:
            ids.append(decision_id)
        self._save()

    # ── Class Methods ────────────────────────────────────────────────────────

    @classmethod
    def list_sessions(cls, de_name: str, limit: int = 50) -> list:
        """Return compact session summaries for a DE, newest first."""
        sessions_dir = AGENTS_DIR / de_name / "sessions"
        if not sessions_dir.exists():
            return []
        sessions = []
        for f in sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text())
                sessions.append({
                    "id": data.get("id"),
                    "status": data.get("status"),
                    "trigger_type": data.get("trigger_type"),
                    "trigger_context": data.get("trigger_context", "")[:100],
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "step_count": len(data.get("steps", [])),
                    "summary": data.get("summary"),
                })
            except Exception:
                pass
        return sessions

    @classmethod
    def load(cls, de_name: str, session_id: str) -> "WorkSession":
        """Load an existing session by ID."""
        return cls(de_name, "", None, "", session_id=session_id)

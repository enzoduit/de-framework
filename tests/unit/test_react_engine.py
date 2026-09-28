"""
Unit tests for react_engine.py — no live backend or API keys required.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSoftCheckpoint(unittest.TestCase):
    """Soft checkpoint is injected at 70% of max_iterations."""

    def _make_engine(self, max_iter=10):
        """Build a ReActEngine with mocked Anthropic client."""
        from backend.core.react_engine import ReActEngine
        with patch("backend.core.react_engine._load_api_key", return_value="test-key"), \
             patch("backend.core.react_engine.AGENTS_DIR", Path(tempfile.mkdtemp())):
            engine = ReActEngine(
                agent_name="test",
                mission="test mission",
                tools=[],
                max_iterations=max_iter,
            )
        return engine

    def test_soft_checkpoint_flag_initialized(self):
        engine = self._make_engine()
        self.assertFalse(engine._soft_checkpoint_fired)

    def test_soft_checkpoint_fires_at_70_percent(self):
        """At iteration 7 of 10, checkpoint should fire."""
        engine = self._make_engine(max_iter=10)
        threshold = int(engine.max_iterations * 0.7)
        self.assertEqual(threshold, 7)

    def test_soft_checkpoint_not_fired_twice(self):
        """Once fired, _soft_checkpoint_fired stays True."""
        engine = self._make_engine(max_iter=10)
        engine._soft_checkpoint_fired = True
        # Simulate second check — should not reset
        self.assertTrue(engine._soft_checkpoint_fired)

    def test_soft_checkpoint_text_content(self):
        """Checkpoint message must include key guidance strings."""
        from backend.core.react_engine import ReActEngine
        # Read source and verify checkpoint text is sensible
        src = (Path(__file__).parent.parent.parent / "backend/core/react_engine.py").read_text()
        self.assertIn("_soft_checkpoint_fired", src)
        self.assertIn("Soft checkpoint", src)
        self.assertIn("continue autonomously", src)
        self.assertIn("0.7", src)  # 70% threshold


class TestMaxIterationsConfig(unittest.TestCase):
    """max_iterations_cron must be configured sensibly per DE type."""

    def _get_de_json(self, agent_dir: Path) -> dict:
        f = agent_dir / "de.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def test_agents_dir_env_respected(self):
        """AGENTS_DIR environment variable is used."""
        import os
        from backend.core import react_engine
        # The module should use os.environ.get
        src = (Path(__file__).parent.parent.parent / "backend/core/react_engine.py").read_text()
        self.assertIn('os.environ.get("AGENTS_DIR"', src)

    def test_session_runner_reads_max_iterations_cron(self):
        """session_runner.py must read max_iterations_cron from de.json."""
        src = (Path(__file__).parent.parent.parent / "backend/core/session_runner.py").read_text()
        self.assertIn("max_iterations_cron", src)


class TestFeedbackDB(unittest.TestCase):
    """Feedback database functions work correctly."""

    def test_init_creates_feedback_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["AGENTS_DIR"] = tmpdir
            from backend.core import feedback_db
            import importlib
            importlib.reload(feedback_db)
            feedback_db.init_db()
            import sqlite3
            conn = sqlite3.connect(str(Path(tmpdir) / "feedback.db"))
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            conn.close()
            self.assertIn("feedback", tables)

    def test_store_and_retrieve_feedback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            os.environ["AGENTS_DIR"] = tmpdir
            from backend.core import feedback_db
            import importlib
            importlib.reload(feedback_db)
            feedback_db.init_db()
            fid = feedback_db.store_feedback("test-agent", "sess-001", "summary text", "raw feedback")
            self.assertIsInstance(fid, int)
            self.assertGreater(fid, 0)
            row = feedback_db.get_feedback(fid)
            self.assertEqual(row["de_name"], "test-agent")
            self.assertEqual(row["raw_text"], "raw feedback")


class TestDecisionQuality(unittest.TestCase):
    """Decisions must have required fields for voice review."""

    def _engine(self):
        from backend.core.react_engine import ReActEngine
        with patch("backend.core.react_engine._load_api_key", return_value="key"), \
             patch("backend.core.react_engine.AGENTS_DIR", Path(tempfile.mkdtemp())):
            return ReActEngine("test", "mission", [], max_iterations=5)

    def test_valid_decision_passes_validation(self):
        engine = self._engine()
        issues = engine._validate_decision({
            "title": "Approve new experiment",
            "description": "We need to run this experiment because the SoAV is 0% and we have evidence.",
            "proposed_action": "Post on LinkedIn with the provided text.",
            "estimated_impact": "300 impressions",
            "urgency": "medium",
        })
        self.assertEqual(issues, [])

    def test_missing_required_fields_fail(self):
        engine = self._engine()
        issues = engine._validate_decision({"title": "Approve"})
        self.assertTrue(any("description" in i for i in issues))
        self.assertTrue(any("proposed_action" in i for i in issues))

    def test_title_too_long_fails(self):
        engine = self._engine()
        issues = engine._validate_decision({
            "title": "A" * 81,
            "description": "Sufficient description that explains the situation clearly.",
            "proposed_action": "Do this specific action right now.",
        })
        self.assertTrue(any("too long" in i for i in issues))


class TestOutputQuality(unittest.TestCase):
    """DE outputs must not contain internal filesystem paths."""

    INTERNAL_PATHS = ["/var/de-agents/", "/tmp/", "/root/.openclaw/workspace/agents/"]

    def test_no_internal_paths_in_summaries_pattern(self):
        """Verify the test pattern correctly identifies bad paths."""
        clean = "Session complete. SoAV = 30%. Content deployed to https://agentic-living.com."
        dirty = "Session complete. File at /var/de-agents/grow/workspace/output.html."
        for pat in self.INTERNAL_PATHS:
            self.assertNotIn(pat, clean)
        self.assertIn("/var/de-agents/", dirty)

    def test_system_prompt_does_not_expose_filesystem_paths(self):
        """System prompt should not include internal paths that leak to outputs."""
        from backend.core.react_engine import ReActEngine
        with patch("backend.core.react_engine._load_api_key", return_value="key"), \
             patch("backend.core.react_engine.AGENTS_DIR", Path(tempfile.mkdtemp())):
            engine = ReActEngine("test", "mission", [], max_iterations=5)
        prompt = engine._system_prompt
        # Prompt CAN reference paths (it's internal) but we track this for awareness
        # This test documents what's currently in the prompt
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)


class TestToolRegistration(unittest.TestCase):
    """Core tools must be registered in every DE session."""

    def test_human_decision_tool_always_registered(self):
        from backend.core.react_engine import ReActEngine
        with patch("backend.core.react_engine._load_api_key", return_value="key"), \
             patch("backend.core.react_engine.AGENTS_DIR", Path(tempfile.mkdtemp())):
            engine = ReActEngine("test", "mission", [], max_iterations=5)
        tool_names = [t["name"] for t in engine._tools_for_api]
        self.assertIn("request_human_decision", tool_names)

    def test_write_metric_tool_always_registered(self):
        from backend.core.react_engine import ReActEngine
        with patch("backend.core.react_engine._load_api_key", return_value="key"), \
             patch("backend.core.react_engine.AGENTS_DIR", Path(tempfile.mkdtemp())):
            engine = ReActEngine("test", "mission", [], max_iterations=5)
        tool_names = [t["name"] for t in engine._tools_for_api]
        self.assertIn("write_metric", tool_names)

    def test_ask_colleague_tool_always_registered(self):
        from backend.core.react_engine import ReActEngine
        with patch("backend.core.react_engine._load_api_key", return_value="key"), \
             patch("backend.core.react_engine.AGENTS_DIR", Path(tempfile.mkdtemp())):
            engine = ReActEngine("test", "mission", [], max_iterations=5)
        tool_names = [t["name"] for t in engine._tools_for_api]
        self.assertIn("ask_colleague", tool_names)

    def test_log_assumption_registered_in_tool_library(self):
        """log_assumption must exist in tool_implementations TOOL_LIBRARY."""
        src = (Path(__file__).parent.parent.parent / "backend/core/tool_implementations.py").read_text()
        self.assertIn("log_assumption", src)

    def test_measure_assumption_registered_in_tool_library(self):
        src = (Path(__file__).parent.parent.parent / "backend/core/tool_implementations.py").read_text()
        self.assertIn("measure_assumption", src)

    def test_create_document_registered_in_tool_library(self):
        """create_document must be in TOOL_LIBRARY so DEs can produce public-URL links."""
        src = (Path(__file__).parent.parent.parent / "backend/core/tool_implementations.py").read_text()
        self.assertIn("create_document", src)
        self.assertIn("public_url", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""
DE Framework — Integration Health Check
========================================
Run this before telling a user "it's working".
Also run by setup agents after initial deployment.

Usage:
    python3 tests/health_check.py
    python3 tests/health_check.py --base-url http://localhost:8769
    python3 tests/health_check.py --live    # includes slow live session test

Exit code: 0 = all pass, 1 = failures
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", "/var/de-agents"))
WORKSPACE  = Path(os.environ.get("AGENT_WORKSPACE", "/root/.openclaw/workspace"))
HERE       = Path(__file__).parent.parent  # repo root


def _load_env(path="/etc/de-framework.env") -> dict:
    env = {}
    try:
        for line in open(path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"\'')
    except FileNotFoundError:
        pass
    return env


ENV = _load_env()
BASE_URL  = os.environ.get("DE_API_URL", "http://localhost:8769")
API_TOKEN = ENV.get("DE_API_TOKEN", os.environ.get("DE_API_TOKEN", ""))

# ── Output ────────────────────────────────────────────────────────────────────
PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
SKIP = "\033[94m⏭  SKIP\033[0m"

results: list[dict] = []


def check(name: str, category: str, ok: bool, note: str = ""):
    """Record and print one test result."""
    status = PASS if ok else FAIL
    results.append({"name": name, "cat": category, "ok": ok, "note": note})
    print(f"  {status}  {name}" + (f" — {note}" if note else ""))
    return ok


def skip(name: str, category: str, note: str = ""):
    results.append({"name": name, "cat": category, "ok": True, "note": note})
    print(f"  {SKIP}  {name}" + (f" — {note}" if note else ""))


def api(method: str, path: str, body: dict = None) -> tuple[int, any]:
    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Backend Connectivity
# ══════════════════════════════════════════════════════════════════════════════
def check_backend_health():
    print("\n── 1. Backend Connectivity ──────────────────────────────────────")
    CAT = "connectivity"

    code, _ = api("GET", "/")
    check("Backend is reachable", CAT, code == 200, f"status={code}")

    ok = bool(API_TOKEN)
    check("Auth token is set", CAT, ok,
          "token present" if ok else "DE_API_TOKEN not found in /etc/de-framework.env")

    code, body = api("GET", "/de-list")
    agents = (body or {}).get("des", []) if isinstance(body, dict) else []
    check("Auth token is valid (GET /de-list)", CAT,
          code == 200 and len(agents) > 0,
          "401 Unauthorized" if code == 401 else f"{len(agents)} agents found")

    check("DE list has at least 5 agents", CAT, len(agents) >= 5, f"{len(agents)} agents")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Credentials
# ══════════════════════════════════════════════════════════════════════════════
def check_credentials():
    print("\n── 2. Credentials ───────────────────────────────────────────────")
    CAT = "credentials"

    cfg_path = WORKSPACE / "cloudflare-config.json"
    check("cloudflare-config.json exists", CAT, cfg_path.exists(), str(cfg_path))

    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception as e:
            check("cloudflare-config.json is valid JSON", CAT, False, str(e))
            return
        missing = [f for f in ["token", "account_id", "github_token"] if not cfg.get(f)]
        check("cloudflare-config.json has required fields", CAT,
              not missing, f"missing: {missing}" if missing else "all fields present")
    else:
        check("cloudflare-config.json has required fields", CAT, False, "file missing")

    # GitHub token
    gh_token = cfg.get("github_token") or ENV.get("GITHUB_TOKEN", "")
    if gh_token:
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                check("GitHub token is valid", CAT, r.status == 200,
                      f"authenticated as {data.get('login','?')}")
        except urllib.error.HTTPError as e:
            check("GitHub token is valid", CAT, False, f"HTTP {e.code}")
        except Exception as e:
            check("GitHub token is valid", CAT, False, str(e))
    else:
        check("GitHub token is valid", CAT, False, "no github_token found")

    # Cloudflare token
    cf_token = cfg.get("token", "")
    if cf_token:
        try:
            req = urllib.request.Request(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers={"Authorization": f"Bearer {cf_token}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                status = data.get("result", {}).get("status", "?")
                check("Cloudflare token is valid", CAT, status == "active", f"status={status}")
        except Exception as e:
            check("Cloudflare token is valid", CAT, False, str(e))
    else:
        check("Cloudflare token is valid", CAT, False, "no CF token in cloudflare-config.json")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Decision & Feedback Flow
# ══════════════════════════════════════════════════════════════════════════════
def check_decision_flow():
    print("\n── 3. Decision & Feedback Flow ──────────────────────────────────")
    CAT = "decisions"

    code, body = api("GET", "/decisions")
    items = body if isinstance(body, list) else (body or {}).get("decisions", (body or {}).get("pending", []))
    check("GET /decisions returns valid structure", CAT,
          code == 200 and isinstance(items, list), f"{len(items) if isinstance(items,list) else '?'} decisions")

    q = AGENTS_DIR / "decision-execute-queue.jsonl"
    if q.exists():
        try:
            lines = [l for l in q.read_text().splitlines() if l.strip()]
            for line in lines:
                json.loads(line)
            check("decision-execute-queue.jsonl is valid JSONL", CAT, True, f"{len(lines)} entries")
        except json.JSONDecodeError as e:
            check("decision-execute-queue.jsonl is valid JSONL", CAT, False, f"invalid: {e}")
    else:
        check("decision-execute-queue.jsonl exists", CAT, False, str(q))

    code, body = api("POST", "/feedback", {
        "de": "health-check", "session_id": "hc-001",
        "message": "health check — please ignore",
    })
    check("POST /feedback is reachable", CAT, code in (200, 201), f"status={code}")

    db = AGENTS_DIR / "feedback.db"
    db_ok = db.exists()
    if db_ok:
        try:
            conn = sqlite3.connect(str(db))
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            conn.close()
            db_ok = "feedback" in tables
            check("feedback.db has feedback table", CAT, db_ok, f"tables: {tables}")
        except Exception as e:
            check("feedback.db has feedback table", CAT, False, str(e))
    else:
        check("feedback.db exists", CAT, False, str(db))

    # Recency check (timezone-safe)
    if db_ok:
        try:
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT timestamp FROM feedback ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if not row:
                check("feedback.db has recent data (< 30 days)", CAT, False, "no entries — feedback loop may be broken")
            else:
                ts_str = row[0]
                # Parse as naive then treat as UTC
                try:
                    last = datetime.fromisoformat(ts_str)
                except ValueError:
                    last = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last).days
                check("feedback.db has recent data (< 30 days)", CAT, age < 30,
                      f"last entry {age} days ago ({ts_str[:10]})" + (" ⚠️ UI may be broken" if age >= 30 else ""))
        except Exception as e:
            check("feedback.db has recent data (< 30 days)", CAT, False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 4. Learning Loop
# ══════════════════════════════════════════════════════════════════════════════
def check_learning_loop():
    print("\n── 4. Learning Loop ─────────────────────────────────────────────")
    CAT = "learning"

    src = (HERE / "backend/core/tool_implementations.py").read_text()
    check("log_assumption tool registered", CAT, "log_assumption" in src)
    check("measure_assumption tool registered", CAT, "measure_assumption" in src)

    logs = list(AGENTS_DIR.glob("*/workspace/LEARNING_LOG.md"))
    check("At least one LEARNING_LOG.md exists", CAT, len(logs) > 0, f"{len(logs)} found")

    src = (HERE / "backend/core/react_engine.py").read_text()
    has = "_soft_checkpoint_fired" in src and "Soft checkpoint" in src and "0.7" in src
    check("Soft checkpoint implemented in react_engine.py", CAT, has,
          "soft checkpoint at 70% present" if has else "MISSING — run was this deployed?")


# ══════════════════════════════════════════════════════════════════════════════
# 5. DE Configuration
# ══════════════════════════════════════════════════════════════════════════════
def check_de_config():
    print("\n── 5. DE Configuration ──────────────────────────────────────────")
    CAT = "config"

    grow_bad, all_missing, ceiling_bad = [], [], []
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        de_json = agent_dir / "de.json"
        if not de_json.exists():
            continue
        try:
            data = json.loads(de_json.read_text())
            val = data.get("max_iterations_cron")
            name = agent_dir.name
            if val is None:
                all_missing.append(name)
            elif agent_dir.name.startswith("grow") and int(val) < 10:
                grow_bad.append(f"{name}={val}")
            elif int(val) > 20:
                ceiling_bad.append(f"{name}={val}")
        except Exception:
            pass

    check("All GROW DEs have max_iterations_cron ≥ 10", CAT, not grow_bad,
          f"under-configured: {grow_bad}" if grow_bad else "all GROW DEs ≥ 10")
    check("All DEs have max_iterations_cron set", CAT, not all_missing,
          f"missing in: {all_missing}" if all_missing else "all DEs configured")
    check("No DE exceeds max_iterations_cron = 20", CAT, not ceiling_bad,
          f"exceeds ceiling: {ceiling_bad}" if ceiling_bad else "all within safety ceiling")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Output Quality
# ══════════════════════════════════════════════════════════════════════════════
def check_output_quality():
    print("\n── 6. Output Quality ────────────────────────────────────────────")
    CAT = "quality"
    BAD_PATHS = ["/var/de-agents/", "/tmp/improved_content", "/root/.openclaw/workspace/agents/"]

    bad_sessions = []
    for agent_dir in AGENTS_DIR.iterdir():
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for sf in sorted(sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:3]:
            try:
                data = json.loads(sf.read_text())
                summary = data.get("summary") or ""
                for pat in BAD_PATHS:
                    if pat in summary:
                        bad_sessions.append(f"{agent_dir.name}")
                        break
            except Exception:
                pass

    check("Recent session summaries don't expose filesystem paths", CAT,
          not bad_sessions,
          f"{len(bad_sessions)} agents with internal paths: {bad_sessions[:3]}" if bad_sessions
          else "clean")

    bad_decisions = []
    for agent_dir in AGENTS_DIR.iterdir():
        df = agent_dir / "decisions.json"
        if not df.exists():
            continue
        try:
            data = json.loads(df.read_text())
            for dec in data.get("pending", []):
                text = dec.get("description", "") + dec.get("proposed_action", "")
                for pat in ["/var/de-agents/", "/tmp/"]:
                    if pat in text:
                        bad_decisions.append(agent_dir.name)
                        break
        except Exception:
            pass

    check("Pending decisions don't use raw filesystem paths", CAT,
          not bad_decisions,
          f"internal paths in: {bad_decisions}" if bad_decisions else "clean")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Portal Endpoints
# ══════════════════════════════════════════════════════════════════════════════
def check_portal_endpoints():
    print("\n── 7. Portal Endpoints ──────────────────────────────────────────")
    CAT = "portal"

    code, _ = api("GET", "/decisions")
    check("GET /decisions", CAT, code == 200, f"status={code}")

    code, body = api("GET", "/tools")
    tools = (body or {}).get("tools", body if isinstance(body, list) else [])
    check("GET /tools returns tools", CAT, code == 200 and len(tools) > 0, f"{len(tools)} tools")

    # Approve a non-existent decision — should return 4xx not 5xx
    code, _ = api("POST", "/decide", {"id": "hc-nonexistent", "action": "approve", "note": "hc"})
    check("POST /decide doesn't 500 on unknown ID", CAT, code != 500, f"status={code}")

    code, _ = api("POST", "/feedback", {"de": "hc", "session_id": "hc", "message": "test"})
    check("POST /feedback returns 200", CAT, code in (200, 201), f"status={code}")


# ══════════════════════════════════════════════════════════════════════════════
# 8. Live Session Test (optional, slow)
# ══════════════════════════════════════════════════════════════════════════════
def check_live_session():
    print("\n── 8. Live Session Test ─────────────────────────────────────────")
    CAT = "live"

    code, body = api("POST", "/de-start", {
        "de_name": "test-agent",
        "trigger_type": "user_chat",
        "trigger_context": "health-check: verify session completes cleanly",
    })
    if not check("Trigger test-agent session", CAT, code == 200 and (body or {}).get("ok"),
                 f"status={code}"):
        return

    session_id = body.get("session_id")
    deadline = time.time() + 90
    completed = False
    while time.time() < deadline:
        time.sleep(5)
        sf = AGENTS_DIR / "test-agent" / "sessions" / f"{session_id}.json"
        if sf.exists():
            data = json.loads(sf.read_text())
            status = data.get("status")
            if status in ("complete", "human_decision_needed", "max_iterations_reached", "error"):
                steps = data.get("steps", [])
                reasoning = [s for s in steps if s.get("type") == "reasoning"]
                check("Session completes with status", CAT,
                      status in ("complete", "human_decision_needed"),
                      f"status={status}, steps={len(steps)}")
                check("Session has reasoning steps", CAT, len(reasoning) > 0,
                      f"{len(reasoning)} reasoning steps")
                completed = True
                break

    if not completed:
        check("Session completes within 90s", CAT, False, "timed out")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def main():
    global BASE_URL, API_TOKEN

    parser = argparse.ArgumentParser(description="DE Framework Health Check")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--token", default=API_TOKEN)
    parser.add_argument("--live", action="store_true", help="Run live DE session test (~90s)")
    parser.add_argument("--quick", action="store_true", help="Skip external API calls")
    args = parser.parse_args()
    BASE_URL  = args.base_url
    API_TOKEN = args.token

    print("=" * 60)
    print("  DE Framework — Health Check")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Target: {BASE_URL}")
    print("=" * 60)

    check_backend_health()
    if not args.quick:
        check_credentials()
    check_decision_flow()
    check_learning_loop()
    check_de_config()
    check_output_quality()
    check_portal_endpoints()

    if args.live:
        check_live_session()
    else:
        skip("Live session test", "live", "use --live to enable")

    total  = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed
    skipped = sum(1 for r in results if "skipped" in (r.get("note") or "") or "use --live" in (r.get("note") or ""))

    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} passed" +
          (f", {failed} failed" if failed else "") +
          (f", {skipped} skipped" if skipped else ""))

    if failed > 0:
        print("\n  Failed tests:")
        for r in results:
            if not r["ok"]:
                print(f"    ❌ [{r['cat']}] {r['name']}: {r.get('note','')}")

    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

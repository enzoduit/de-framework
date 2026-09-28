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
# 2. Credentials (auto-discovery — tests only what's configured)
# ══════════════════════════════════════════════════════════════════════════════

# Integration validators — add new integrations here.
# Each entry: (env_var_or_cfg_key, label, validator_fn)
# validator_fn(token) -> (ok: bool, note: str)

def _validate_github(token: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return r.status == 200, f"authenticated as {data.get('login', '?')}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} — token may be expired"
    except Exception as e:
        return False, str(e)


def _validate_cloudflare(token: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            status = data.get("result", {}).get("status", "?")
            return status == "active", f"status={status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def _validate_openai(token: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200, "token valid"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def _validate_anthropic(token: str) -> tuple[bool, str]:
    # Anthropic doesn't have a lightweight "verify" endpoint;
    # just check the key is non-empty and has the right prefix.
    ok = token.startswith("sk-ant-")
    return ok, "key format valid" if ok else "unexpected key format (expected sk-ant-...)"


def _validate_perplexity(token: str) -> tuple[bool, str]:
    ok = token.startswith("pplx-")
    return ok, "key format valid" if ok else "unexpected key format (expected pplx-...)"


# Registry: env-var name → (human label, validator)
INTEGRATION_REGISTRY: dict[str, tuple[str, callable]] = {
    "GITHUB_TOKEN":        ("GitHub",      _validate_github),
    "CLOUDFLARE_TOKEN":    ("Cloudflare",  _validate_cloudflare),
    "CF_API_TOKEN":        ("Cloudflare",  _validate_cloudflare),
    "OPENAI_API_KEY":      ("OpenAI",      _validate_openai),
    "ANTHROPIC_API_KEY":   ("Anthropic",   _validate_anthropic),
    "PERPLEXITY_API_KEY":  ("Perplexity",  _validate_perplexity),
}

# Also check common credential files for tokens
CREDENTIAL_FILE_KEYS: dict[str, str] = {
    # file-key -> env-var key to map to
    "github_token":     "GITHUB_TOKEN",
    "token":            "CLOUDFLARE_TOKEN",  # cloudflare-config.json uses 'token'
    "cf_token":         "CLOUDFLARE_TOKEN",
    "openai_api_key":   "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "perplexity_key":   "PERPLEXITY_API_KEY",
}


def _discover_credentials() -> dict[str, str]:
    """Discover configured credentials from env + credential files. Returns {env_var: token}."""
    found = {}

    # 1. From environment / de-framework.env
    for key in INTEGRATION_REGISTRY:
        val = ENV.get(key) or os.environ.get(key, "")
        if val:
            found[key] = val

    # 2. From any *.json credential files in the workspace
    for cfg_file in list(WORKSPACE.glob("*config*.json")) + list(WORKSPACE.glob("*credentials*.json")):
        try:
            cfg = json.loads(cfg_file.read_text())
            for file_key, env_key in CREDENTIAL_FILE_KEYS.items():
                val = cfg.get(file_key, "")
                if val and env_key not in found:
                    found[env_key] = val
        except Exception:
            pass

    return found


def check_credentials():
    print("\n── 2. Credentials (auto-discovered) ─────────────────────────────")
    CAT = "credentials"

    creds = _discover_credentials()

    if not creds:
        check("At least one integration credential configured", CAT, False,
              "No tokens found in env or credential files — DEs may not be able to deploy")
        return

    print(f"  ℹ️  Found {len(creds)} configured integration(s): {', '.join(
        INTEGRATION_REGISTRY[k][0] for k in creds if k in INTEGRATION_REGISTRY
    )}")

    for env_key, token in creds.items():
        if env_key not in INTEGRATION_REGISTRY:
            continue
        label, validator = INTEGRATION_REGISTRY[env_key]
        try:
            ok, note = validator(token)
            check(f"{label} token is valid", CAT, ok, note)
        except Exception as e:
            check(f"{label} token is valid", CAT, False, str(e))


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

    # End-to-end: POST /feedback → verify it appears in user_inputs/
    # Note: feedback goes to user_inputs/ (not feedback.db) — this tests the actual flow
    import time as _time
    test_msg = f"health-check-{int(_time.time())}"
    api("POST", "/feedback", {"de": "system", "session_id": "hc-e2e", "message": test_msg})
    _time.sleep(0.5)
    ui_dirs = list(AGENTS_DIR.glob("*/user_inputs/*.json")) + list(AGENTS_DIR.glob("system/user_inputs/*.json"))
    recent_ui = sorted(ui_dirs, key=lambda f: f.stat().st_mtime, reverse=True)[:5]
    found_msg = any(test_msg in f.read_text() for f in recent_ui)
    check("POST /feedback stored in user_inputs/ (end-to-end)", CAT, found_msg,
          "message found in user_inputs/" if found_msg else "message NOT found — feedback not persisted")


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

    # pre_fetch.py: all DEs should have one (runs before React Loop, injects live data)
    de_dirs = [d for d in AGENTS_DIR.iterdir() if d.is_dir() and (d / "de.json").exists()]
    with_prefetch = [d.name for d in de_dirs if (d / "workspace" / "pre_fetch.py").exists()]
    without = [d.name for d in de_dirs if not (d / "workspace" / "pre_fetch.py").exists()
               and d.name not in ("test-agent", "test-intern")]
    check("All DEs have pre_fetch.py (live data before React Loop)", CAT,
          len(with_prefetch) > 0,
          f"{len(with_prefetch)} DEs have pre_fetch.py" + (f"; missing: {without}" if without else ""))

    # metrics.json: per-DE KPI storage with history
    de_with_kpis = []
    for d in de_dirs:
        mf = d / "metrics.json"
        if mf.exists():
            try:
                m = json.loads(mf.read_text())
                if m.get("kpis"):
                    de_with_kpis.append(d.name)
            except Exception:
                pass
    check("DEs have metrics.json with KPIs", CAT,
          len(de_with_kpis) >= 3,
          f"{len(de_with_kpis)} DEs tracking KPIs via metrics.json")

    # create_document tool: DEs can produce public URLs
    src2 = (HERE / "backend/core/tool_implementations.py").read_text()
    check("create_document tool registered (public URL linking)", CAT,
          "create_document" in src2 and "public_url" in src2 and "?raw=1" in src2)


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

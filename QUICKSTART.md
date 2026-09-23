# DE Framework — Quickstart for Setup Agents

**You are a Setup Agent. You have received client data (org chart + job descriptions). This document is your complete, step-by-step process. Follow it in order. Do not ask questions — use this doc.**

---

## 0. What You Need Before Starting

Confirm all four items exist before writing a single file:

| # | Input | Where to find it |
|---|-------|-----------------|
| 1 | **Org chart** | Client's provided document — who reports to whom, team structure |
| 2 | **Job descriptions** | One per role → becomes one DE |
| 3 | **API access / credentials** | Which external tools does each DE need? (Telegram, Google Analytics, Garmin, etc.) |
| 4 | **Communication channel** | How does the client receive DE outputs? (Telegram bot token, email, webhook) |

If any item is missing → stop, list what's missing, ask client.

---

## 1. Map Roles → DEs

Read the org chart. Apply these rules:

- **One job description = one DE** (1:1 mapping)
- Skip pure-human roles (CEO, human managers) — they become the **approval authority** for Level-2 decisions
- Mark any role that serves multiple teams as **transversal** → see `docs/patterns/transversal-agent.md`
- If there is a coordinator role that routes work across DEs → designate it as **chief agent** → see `docs/patterns/chief-agent.md`

Write your mapping to a scratch file first:
```
ops_agent     ← "Operations Manager" JD
grow_client   ← "Growth Manager" JD  
content_agent ← "Content Writer" JD (transversal: serves ops + grow)
chief         ← "Project Director" JD (chef pattern)
```

---

## 2. Create Directory Structure

For each DE, run:

```bash
bash /root/.openclaw/workspace/de-framework/scripts/new-client-setup.sh <client-name> <de1> <de2> <de3>
```

This creates under `/var/de-agents/`:
```
/var/de-agents/<de-name>/
├── workspace/
│   ├── kpis.yaml          ← filled in step 4
│   ├── pre_fetch.py       ← copied from framework/
│   ├── experiments.md     ← empty
│   └── log.md             ← empty
├── logs/
├── sessions/
├── job.md                 ← filled in step 3
├── de.json                ← filled in step 3
├── memory.md              ← empty stub
├── metrics.json           ← empty stub
├── decisions.json         ← {"pending": []}
└── inbox.jsonl            ← empty
```

Verify the script ran cleanly:
```bash
ls /var/de-agents/<de-name>/workspace/
```

---

## 3. Write job.md for Each DE

Use `examples/job-template.md` as your base. One file per DE.

**Mandatory fields to fill in:**
- `[DE NAME]` → the folder name (e.g. `grow_client`)
- `[Role Title]` → from job description
- `**Mission:**` → one sentence, owns one metric
- `**KPI:**` → specific number (e.g. "3 leads/week" or "uptime ≥ 99%")
- `**Measured by:**` → exact file/command (e.g. `python3 workspace/measure_leads.py`)
- Authority levels (Level 0 / 1 / 2) → derived from job description

**Rules:**
- Level 0 = acts without notification (reads, writes, internal checks)
- Level 1 = acts + logs to workspace
- Level 2 = creates a human decision request, stops
- Everything not explicitly in Level 0/1 defaults to Level 2

Place the finished file at `/var/de-agents/<de-name>/job.md`.

**Special cases:**
- Chief agent → use `docs/patterns/chief-agent.md` template instead
- Transversal agent → use `docs/patterns/transversal-agent.md` template instead

---

## 4. Write kpis.yaml for Each DE

Location: `/var/de-agents/<de-name>/workspace/kpis.yaml`

**Standard format** (when you have a known target):

```yaml
de: "<de_name>"
kpis:
  - id: leads_this_week
    name: "Leads Generated (This Week)"
    measure: "python3 workspace/measure_leads.py"
    unit: "leads"
    direction: "up"
    target: 3
    frequency: weekly
```

**Benchmark Mode** (when you don't have a target yet):

If the client has no historical data and no agreed target → use benchmark mode:

```yaml
de: "<de_name>"
kpis:
  - id: churn_rate
    name: "Monthly Churn Rate"
    measure: "python3 workspace/measure_churn.py"
    unit: "%"
    direction: "lower_is_better"
    target: null          # set automatically after first measurement
    target_auto: true     # enables benchmark mode
    target_improvement: 0.10  # 10% improvement from baseline
```

**How benchmark mode works:**
1. `pre_fetch.py` detects `target: null` + `target_auto: true`
2. Runs the `measure` command → gets first value = **baseline**
3. Calculates target: `baseline × 1.10` (up) or `baseline × 0.90` (lower_is_better)
4. Writes the concrete target back into `kpis.yaml` as `target: <calculated_value>`
5. On every subsequent run, a real target exists → normal comparison applies

Reference: `docs/kpi-system.md` → "Benchmark Mode" section for full schema and examples.

---

## 5. Connect pre_fetch.py

The generic `pre_fetch.py` from `framework/pre_fetch.py` handles all KPI measurement automatically — you typically don't need to modify it.

What to verify:
1. File exists at `/var/de-agents/<de-name>/workspace/pre_fetch.py`
   - The setup script copies it automatically
2. Each `measure:` command in `kpis.yaml` is a valid shell command that prints exactly one number to stdout
3. Test it manually:

```bash
cd /var/de-agents/<de-name>
python3 workspace/pre_fetch.py
```

Expected output: A briefing starting with `=== <DE_NAME> BRIEFING — YYYY-MM-DD ===`

If a KPI shows `not_measured` → the measure command failed or the data file doesn't exist yet. That's OK for first run — the DE will establish baseline on its first cron session.

---

## 6. Register Cron Schedules

Each DE runs on a schedule via OpenClaw's cron system.

**Standard schedules (use these unless client specifies otherwise):**

| DE Type | Default Schedule | Reason |
|---------|-----------------|--------|
| Core services (ops, shield) | Every 2h: `0 */2 * * *` | High-frequency monitoring |
| Daily review (max, flow) | Daily 06:00: `0 6 * * *` | Morning check-in |
| Growth / GEO | Every 2 days: `0 9 */2 * *` | Avoids over-optimizing |
| Chief agent | Weekly: `0 9 * * 1` | Coordination rhythm |
| Transversal | On-demand only | Triggered by colleagues |

**To register a cron schedule (OpenClaw CLI):**

```bash
# From the server where openclaw is running:
openclaw cron add \
  --name "<de_name>-cron" \
  --schedule "0 9 */2 * *" \
  --command "/var/de-agents/de-trigger.sh <de_name> cron" \
  --session isolated
```

Or via the OpenClaw Control UI: Settings → Scheduled Tasks → Add.

**Store the returned Cron ID** in the DE's `de.json` under `"cron_id"` and in `docs/de-inventory.md`.

---

## 7. Verify Everything Works

Run through this checklist before handing off:

### Filesystem check
```bash
for de in <de1> <de2> <de3>; do
  echo "--- $de ---"
  ls /var/de-agents/$de/workspace/kpis.yaml 2>/dev/null && echo "kpis.yaml ✓" || echo "kpis.yaml ✗ MISSING"
  ls /var/de-agents/$de/workspace/pre_fetch.py 2>/dev/null && echo "pre_fetch.py ✓" || echo "pre_fetch.py ✗ MISSING"
  ls /var/de-agents/$de/job.md 2>/dev/null && echo "job.md ✓" || echo "job.md ✗ MISSING"
  ls /var/de-agents/$de/de.json 2>/dev/null && echo "de.json ✓" || echo "de.json ✗ MISSING"
done
```

### Pre-fetch smoke test
```bash
for de in <de1> <de2> <de3>; do
  echo "=== $de ==="
  python3 /var/de-agents/$de/workspace/pre_fetch.py 2>&1 | head -10
done
```

### DE backend registration
```bash
TOKEN=$(grep '^DE_API_TOKEN=' /etc/de-framework.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8769/de-list
```

All DEs should appear in the response.

### Manual trigger test (first real run)
```bash
/var/de-agents/de-trigger.sh <de_name> cron
```

Check the session log appeared:
```bash
tail -1 /var/de-agents/<de_name>/log.jsonl | python3 -m json.tool
```

---

## 8. Document in de-inventory.md

Add each new DE to `docs/de-inventory.md` using the existing table format:

```markdown
### <DISPLAY NAME> — <Role Title>
| Field | Value |
|-------|-------|
| **Mission** | <one sentence> |
| **KPIs** | <KPI name> (target: <value>) |
| **Schedule** | <human readable> (`<cron expression>`) |
| **Cron ID** | `<uuid from openclaw>` |
| **Workspace** | `kpis.yaml` ✓ · `pre_fetch.py` ✓ · `experiments.md` ✓ · `log.md` ✓ |
```

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `measure` command prints multiple lines | Add `\| head -1` or `\| tail -1` to ensure one line output |
| `target: null` without `target_auto: true` | DE will never have a comparison point — add `target_auto: true` |
| Missing `direction` field | Defaults to `up` — explicitly set `lower_is_better` for churn, costs, errors |
| DE not in `/de-list` response | Check that `de.json` exists and has a valid `name` field |
| pre_fetch.py crashes | Run manually + read stderr — usually a missing dependency or missing data file |
| Level-2 decisions never approved | Check that the client has a Telegram channel to receive decision notifications |

---

## Reference Files

| File | Purpose |
|------|---------|
| `examples/job-template.md` | Base template for any DE's job.md |
| `docs/kpi-system.md` | Full KPI schema + benchmark mode |
| `docs/patterns/chief-agent.md` | Chef agent pattern + job.md template |
| `docs/patterns/transversal-agent.md` | Transversal agent pattern + job.md template |
| `docs/pre-fetch-pattern.md` | How pre_fetch.py integrates with session_runner |
| `docs/de-inventory.md` | Live roster of all registered DEs |
| `framework/pre_fetch.py` | Generic measurement script (copy to each workspace) |
| `scripts/new-client-setup.sh` | Bootstrap script for new client directories |

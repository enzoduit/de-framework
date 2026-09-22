#!/usr/bin/env python3
"""
measure_cost.py — cost metrics from session files (last 7 days).
Usage: python3 workspace/measure_cost.py --trigger <cron|all> --metric <metric>
Metrics: avg_cost (default), waste_rate, total_cost
Outputs a single number or 'not_measured'.
"""
import json, glob, sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))

trigger_filter = None
metric = 'avg_cost'
i = 0
while i < len(sys.argv):
    if sys.argv[i] == '--trigger' and i + 1 < len(sys.argv):
        trigger_filter = sys.argv[i + 1]
        i += 2
    elif sys.argv[i] == '--metric' and i + 1 < len(sys.argv):
        metric = sys.argv[i + 1]
        i += 2
    else:
        i += 1

cutoff = datetime.now(timezone.utc) - timedelta(days=7)


def estimate_cost(steps: int, model: str = '') -> float:
    m = model.lower()
    if 'haiku' in m:
        return steps * 0.0003
    if 'sonnet' in m:
        return steps * 0.003
    return steps * 0.001


sessions, costs, waste = [], [], 0
for f in glob.glob(str(AGENTS_DIR / '*/sessions/*.json')):
    try:
        d = json.loads(Path(f).read_text())
        ts = d.get('created_at', '')
        if not ts:
            continue
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if dt <= cutoff:
            continue
        trig = d.get('trigger_type', 'unknown')
        if trigger_filter and trigger_filter != 'all' and trig != trigger_filter:
            continue
        steps = len(d.get('steps', []))
        cost = estimate_cost(steps, d.get('model', ''))
        sessions.append(d)
        costs.append(cost)
        if not d.get('summary') and d.get('status') != 'running':
            waste += 1
    except Exception:
        pass

if not sessions:
    print('not_measured')
elif metric == 'avg_cost':
    print(round(sum(costs) / len(costs), 4))
elif metric == 'waste_rate':
    print(round(100 * waste / len(sessions), 1))
elif metric == 'total_cost':
    print(round(sum(costs), 4))
else:
    print('not_measured')

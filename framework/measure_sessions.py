#!/usr/bin/env python3
"""
measure_sessions.py — session efficiency metrics across all DEs (last 7 days).
Usage: python3 workspace/measure_sessions.py --metric <metric_name>
Metrics: timed_out_rate, no_output_rate, total_sessions
Outputs a single number or 'not_measured'.
"""
import json, glob, sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))
metric = 'timed_out_rate'
for i, arg in enumerate(sys.argv):
    if arg == '--metric' and i + 1 < len(sys.argv):
        metric = sys.argv[i + 1]

cutoff = datetime.now(timezone.utc) - timedelta(days=7)
total, timed_out, no_output = 0, 0, 0

for f in glob.glob(str(AGENTS_DIR / '*/sessions/*.json')):
    try:
        d = json.loads(Path(f).read_text())
        ts = d.get('created_at', '')
        if not ts:
            continue
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if dt > cutoff:
            total += 1
            if d.get('status') == 'max_iterations_reached':
                timed_out += 1
            if not d.get('summary'):
                no_output += 1
    except Exception:
        pass

if total == 0:
    print('not_measured')
elif metric == 'timed_out_rate':
    print(round(100 * timed_out / total, 1))
elif metric == 'no_output_rate':
    print(round(100 * no_output / total, 1))
elif metric == 'total_sessions':
    print(total)
else:
    print('not_measured')

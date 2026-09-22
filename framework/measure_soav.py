#!/usr/bin/env python3
"""
measure_soav.py — reads cached SoAV score from workspace/soav_latest.json
Outputs a single number (0-100) or 'not_measured'.
Run from DE_DIR: python3 workspace/measure_soav.py
"""
import json, glob, os
from pathlib import Path

DE_DIR = Path(__file__).parent.parent
WORKSPACE = DE_DIR / 'workspace'

# Primary: soav_latest.json
cache = WORKSPACE / 'soav_latest.json'
if cache.exists():
    try:
        d = json.loads(cache.read_text())
        score = d.get('soav_score') or d.get('soav_pct')
        if score is not None:
            print(round(float(score), 1))
            exit(0)
    except Exception:
        pass

# Fallback: latest benchmark_*.json (grow_agentic_living pattern)
benchmarks = sorted(WORKSPACE.glob('benchmark_*.json'))
if benchmarks:
    try:
        d = json.loads(benchmarks[-1].read_text())
        pct = d.get('soav_pct')
        if pct is not None:
            print(round(float(pct) * 100 if float(pct) <= 1.0 else float(pct), 1))
            exit(0)
    except Exception:
        pass

print('not_measured')

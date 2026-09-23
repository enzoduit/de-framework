#!/usr/bin/env python3
"""
Generic pre_fetch.py — reads kpis.yaml, runs measurements, builds briefing.
Runs WITHOUT LLM. Called by session_runner.py before ReAct loop.

Deploy to: /var/de-agents/{de}/workspace/pre_fetch.py
"""
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

DE_NAME = Path(__file__).parent.parent.name
AGENTS_DIR = Path(os.environ.get('AGENTS_DIR', '/var/de-agents'))
DE_DIR = AGENTS_DIR / DE_NAME
WORKSPACE = DE_DIR / 'workspace'
METRICS_FILE = DE_DIR / 'metrics.json'


def load_kpis():
    kpis_file = WORKSPACE / 'kpis.yaml'
    if not kpis_file.exists():
        return []
    if YAML_AVAILABLE:
        import yaml
        data = yaml.safe_load(kpis_file.read_text())
        return (data or {}).get('kpis', [])
    # Fallback: simple line parser
    kpis, current = [], {}
    for line in kpis_file.read_text().splitlines():
        if line.startswith('  - id:'):
            if current:
                kpis.append(current)
            current = {'id': line.split(':', 1)[1].strip()}
        elif line.startswith('    ') and ':' in line:
            k, v = line.strip().split(':', 1)
            current[k.strip()] = v.strip()
    if current:
        kpis.append(current)
    return kpis


def measure_kpi(kpi):
    cmd = kpi.get('measure', '')
    if not cmd:
        return None
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=10, cwd=str(DE_DIR)
        )
        val = result.stdout.strip()
        if val and val != 'not_measured':
            try:
                return float(val)
            except ValueError:
                return val
        return val if val else None
    except Exception:
        return None


def load_metrics():
    if METRICS_FILE.exists():
        try:
            return json.loads(METRICS_FILE.read_text())
        except Exception:
            pass
    return {'kpis': []}


def apply_benchmark_mode(kpis_data, new_values):
    """Benchmark Mode: if target is null and target_auto=True, set target from first measurement.

    Direction rules:
      - 'up'              → target = baseline × (1 + improvement)   e.g. 30 → 33
      - 'lower_is_better' → target = baseline × (1 - improvement)   e.g. 8% → 7.2%

    Writes the computed target back into kpis.yaml so next run has a real target.
    Marks kpi entry with target_auto_set=True and baseline=<first_value> in metrics.json.
    """
    kpis_file = WORKSPACE / 'kpis.yaml'
    if not kpis_file.exists():
        return

    updated = False
    content = kpis_file.read_text()

    for kpi in kpis_data:
        kid = kpi.get('id', '')
        target = kpi.get('target')
        target_auto = kpi.get('target_auto', False)
        if target is not None or not target_auto:
            continue  # not in benchmark mode, skip

        val = new_values.get(kid)
        if val is None or val == 'not_measured' or val == '':
            continue  # no measurement yet

        try:
            baseline = float(val)
        except (TypeError, ValueError):
            continue

        direction = kpi.get('direction', 'up')
        try:
            improvement = float(kpi.get('target_improvement', 0.10))
        except (TypeError, ValueError):
            improvement = 0.10

        if direction == 'up':
            new_target = round(baseline * (1.0 + improvement), 4)
        else:  # lower_is_better
            new_target = round(baseline * (1.0 - improvement), 4)

        # Patch kpis.yaml: replace 'target: null' for this kpi's block with 'target: <value>'
        # Strategy: find the id line, then replace the next 'target: null' line after it
        lines = content.splitlines()
        in_block = False
        patched_lines = []
        for line in lines:
            if f'id: {kid}' in line:
                in_block = True
            if in_block and 'target: null' in line:
                indent = len(line) - len(line.lstrip())
                line = ' ' * indent + f'target: {new_target}  # auto-set from baseline {baseline}'
                in_block = False
                updated = True
            patched_lines.append(line)
        content = '\n'.join(patched_lines)

        # Store baseline info back on the kpi dict (picked up by save_metrics)
        kpi['target'] = new_target
        kpi['target_auto_set'] = True
        kpi['baseline'] = baseline
        print(f'[benchmark] {kid}: baseline={baseline} → auto-target={new_target} ({direction}, {improvement*100:.0f}% improvement)', file=__import__('sys').stderr)

    if updated:
        kpis_file.write_text(content)


def save_metrics(kpis_data, new_values):
    m = load_metrics()
    existing = {k['id']: k for k in m.get('kpis', [])}
    for kpi in kpis_data:
        kid = kpi['id']
        val = new_values.get(kid)
        if val is None:
            continue
        if kid not in existing:
            existing[kid] = {
                'id': kid,
                'name': kpi.get('name', kid),
                'target': kpi.get('target'),
                'unit': kpi.get('unit', ''),
                'direction': kpi.get('direction', 'up'),
                'history': [],
            }
        prev = existing[kid].get('value')
        existing[kid]['value'] = val
        existing[kid]['target'] = kpi.get('target')  # may have been updated by benchmark mode
        existing[kid]['updated'] = datetime.now(timezone.utc).isoformat()
        # Store benchmark metadata if present
        if kpi.get('target_auto_set'):
            existing[kid]['target_auto_set'] = True
            existing[kid]['baseline'] = kpi.get('baseline')
        if prev is not None and prev != val:
            existing[kid].setdefault('history', []).append(
                {'ts': datetime.now(timezone.utc).isoformat()[:10], 'value': prev}
            )
            existing[kid]['history'] = existing[kid]['history'][-10:]

    m['kpis'] = list(existing.values())
    m['last_updated'] = datetime.now(timezone.utc).isoformat()
    METRICS_FILE.write_text(json.dumps(m, indent=2))


def build_briefing(kpis_data, values):
    lines = [
        f"=== {DE_NAME.upper()} BRIEFING — {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ==="
    ]

    on_track, off_track, not_measured = [], [], []
    for kpi in kpis_data:
        kid = kpi['id']
        val = values.get(kid)
        target = kpi.get('target')
        direction = kpi.get('direction', 'up')
        name = kpi.get('name', kid)
        unit = kpi.get('unit', '')

        if val is None or val == 'not_measured' or val == '':
            if kpi.get('target_auto') and target is None:
                not_measured.append(f"  ⚠ {name}: not measured yet (benchmark mode — first run sets baseline)")
            else:
                not_measured.append(f"  ⚠ {name}: not measured (target: {target} {unit})")
            continue

        if target is not None:
            try:
                v, t = float(val), float(target)
                ok = (v >= t) if direction == 'up' else (v <= t)
                icon = '\u2713' if ok else '\u2717'
                auto_note = ' \u2014 auto-set from baseline' if kpi.get('target_auto_set') else ''
                entry = f"  {icon} {name}: {val} {unit} (target: {target} {unit}{auto_note})"
                (on_track if ok else off_track).append(entry)
            except (TypeError, ValueError):
                on_track.append(f"  \u00b7 {name}: {val} {unit}")
        else:
            on_track.append(f"  \u00b7 {name}: {val} {unit}")

    if off_track:
        lines.append("\nOFF TRACK — action needed:")
        lines.extend(off_track)
    if not_measured:
        lines.append("\nNot yet measured:")
        lines.extend(not_measured)
    if on_track:
        lines.append("\nOn track:")
        lines.extend(on_track)

    # Experiments summary
    exp_file = WORKSPACE / 'experiments.md'
    if exp_file.exists():
        content = exp_file.read_text().strip()
        if content and 'No experiments' not in content:
            lines.append("\nActive experiments:")
            for line in content.splitlines()[:5]:
                if line.startswith('##'):
                    lines.append(f"  {line}")

    if off_track:
        lines.append("\nRULE: Address off-track KPIs first. One focused action per session.")
    elif not_measured:
        lines.append("\nRULE: Establish baseline for unmeasured KPIs first.")
    else:
        lines.append("\nRULE: All KPIs on track. Write one line to workspace/log.md and done.")

    return '\n'.join(lines)


def main():
    kpis_data = load_kpis()
    if not kpis_data:
        print(
            f"=== {DE_NAME.upper()} BRIEFING ===\n"
            "No KPIs defined. Create workspace/kpis.yaml to enable tracking."
        )
        return

    values = {}
    for kpi in kpis_data:
        val = measure_kpi(kpi)
        values[kpi['id']] = val

    # Apply benchmark mode before saving (may update targets in kpis.yaml + kpi dicts)
    apply_benchmark_mode(kpis_data, values)

    save_metrics(kpis_data, values)
    print(build_briefing(kpis_data, values))


if __name__ == '__main__':
    main()

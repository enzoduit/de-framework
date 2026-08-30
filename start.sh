#!/bin/bash
set -e
AGDIR="${AGENTS_DIR:-/tmp/de-agents}"
mkdir -p "$AGDIR"

# Seed example DEs on first run
for de_dir in examples/*/; do
  de_name=$(basename "$de_dir")
  target="$AGDIR/$de_name"
  if [ ! -d "$target" ]; then
    cp -r "$de_dir" "$target"
    mkdir -p "$target/sessions" "$target/workspace"
    echo '{"activities":[]}' > "$target/schedule.json"
    echo '{"created_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","last_updated":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' > "$target/metrics.json"
    printf "# %s Memory\n\nCreated at startup. No entries yet.\n" "$de_name" > "$target/memory.md"
    echo '{"pending":[],"resolved":[]}' > "$target/decisions.json"
    echo "Seeded: $de_name"
  fi
done

echo "Starting DE Framework API on port ${PORT:-8766}..."
python backend/server.py

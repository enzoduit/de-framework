#!/bin/bash
# de-trigger.sh <de_name> [trigger_type]
# Triggers a DE session via the de-backend API.
# Token is read from /etc/de-framework.env at runtime (never embedded).
set -e

DE_NAME="${1:?Usage: de-trigger.sh <de_name> [trigger_type]}"
TRIGGER_TYPE="${2:-cron}"

# Export all vars from env file so subprocesses inherit them
set -a
. /etc/de-framework.env
set +a

python3 -c "
import urllib.request, json, os, sys
token = os.environ.get('DE_API_TOKEN', '')
if not token:
    print('ERROR: DE_API_TOKEN not set', file=sys.stderr)
    sys.exit(1)
payload = json.dumps({'de_name': '${DE_NAME}', 'trigger_type': '${TRIGGER_TYPE}'}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8769/de-start',
    data=payload,
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
    method='POST'
)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print(json.loads(resp.read()))
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

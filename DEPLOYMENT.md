# DEPLOYMENT.md — Self-Hosted & Container Notes

Real-world learnings from production deployments. These issues surfaced during
a self-hosted ACNUR setup and are now fixed/documented here.

---

## 1. Custom Tools Directory — Persistent Volume

**Issue:** `CUSTOM_TOOLS_DIR` was hardcoded to `/var/de-framework-tools`. In containers,
`/var` is ephemeral — registered tools disappeared on restart.

**Fix (now in code):** Set via environment variable:

```bash
# /etc/de-framework.env or container env:
CUSTOM_TOOLS_DIR=/app/custom-tools    # mount a persistent volume here
```

Default remains `/var/de-framework-tools` for bare-metal servers. Container deployments
should mount a persistent volume at the chosen path and set this env var.

**docker-compose example:**
```yaml
services:
  de-backend:
    environment:
      - CUSTOM_TOOLS_DIR=/app/custom-tools
    volumes:
      - custom-tools:/app/custom-tools
      - de-agents:/var/de-agents
      - de-creds:/var/de-framework-credentials

volumes:
  custom-tools:
  de-agents:
  de-creds:
```

---

## 2. Logo Behind Cloudflare Zero Trust

**Issue:** Logo URLs on the same ZT-protected domain fail to load as `<img src>` —
sub-resource requests don't forward ZT session cookies.

**Fix:** Use a Base64 data URL instead of a domain URL:

```bash
# Convert logo to Base64 and set via API:
LOGO_B64=$(base64 -i logo.png | tr -d '\n')
curl -X POST http://your-server/api/branding \
  -H "Authorization: Bearer $DE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"logo_url\":\"data:image/png;base64,${LOGO_B64}\",\"company_name\":\"Your Co\"}"
```

Or paste the `data:image/png;base64,...` string directly into Portal Settings → Branding → Logo URL.

---

## 3. Backend URL — Self-Hosted Configuration

**Issue:** Portal previously defaulted to `https://de-api.enzoduit.com`. New installs
need to configure their own backend URL.

**Fix (now in code):** Default is now empty — the Settings dialog opens automatically
on first visit. For ZT setups where the dialog is blocked, pre-configure before deploying:

**Option A — hardcode in `portal/index.html` before deploying:**
Add before `</head>`:
```html
<script>
  window.DE_BACKEND_URL   = 'https://your-backend.example.com';
  window.DE_BACKEND_TOKEN = 'your-api-token';
</script>
```

**Option B — set via browser console after opening the portal:**
```javascript
localStorage.setItem('de_backend', JSON.stringify({
  url: 'https://your-backend.example.com',
  token: 'your-api-token'
}));
location.reload();
```

---

## 4. Python 3.11 Compatibility

**Issue:** Nested quotes in f-strings (`f'{", ".join(x)}'`) require Python 3.12+.
Ubuntu 22.04 ships Python 3.11 — these caused `SyntaxError` at import.

**Fix (now in code):** All affected f-strings use compatible quoting.

Check your version:
```bash
python3 --version
# 3.11.x → use this repo version (fixed)
# 3.10 or older → upgrade Python or use Ubuntu 22.04+
```

If you add custom backend code: avoid nested same-quote f-strings on Python 3.11.
Extract the inner expression as a variable first:
```python
# ❌ Python 3.11: SyntaxError
f"Missing: {', '.join(items)}"

# ✅ Works on 3.11+
missing_str = ", ".join(items)
f"Missing: {missing_str}"
```

/**
 * /agents-data — aggregates live metrics from agent metrics.json files
 * Called by the portal to render dynamic agent cards
 */
export async function onRequestGet(context) {
  const BASE = '/root/.openclaw/workspace/agents';

  // Fetch each agent's metrics.json + last portal-inbox entry
  const agents = ['max', 'aria', 'geo', 'ops', 'coach', 'scribe', 'flow', 'shield'];

  async function readFile(path) {
    try {
      const { execSync } = await import('child_process');
      // We can't do fs in CF Pages — serve via a pre-built JSON instead
      // This function is a passthrough to the server-generated ws-data.json
    } catch(e) { return null; }
  }

  // CF Pages Functions can't read the server filesystem directly.
  // Instead, read from the pre-built agents-data.json that the server generates.
  try {
    const resp = await fetch('https://decisions.enzoduit.com/agents-data', {
      headers: { 'Authorization': 'Bearer os-decisions-2026-xK9mP' }
    });
    const data = await resp.json();
    return new Response(JSON.stringify(data), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store'
      }
    });
  } catch(e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

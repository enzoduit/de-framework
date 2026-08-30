// Catch-all proxy for all /de/* routes:
// GET  /de/<name>                 — DE profile + recent sessions
// GET  /de/<name>/sessions        — session list
// GET  /de/<name>/sessions/<id>   — full session steps
// POST /de/create                 — create a new DE
// POST /de/setup-chat             — conversational setup assistant
// POST /de/<name>/sessions/start  — start a session (for resume flow)
// GET  /de/<name>/workspace       — list workspace files
// GET  /de/<name>/workspace/<f>   — read a workspace file

export async function onRequest(context) {
  if (context.request.method === 'OPTIONS') {
    return new Response(null, {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      },
    });
  }

  const apiUrl = context.env.DE_API_URL;
  const apiToken = context.env['DE_API_TOKEN'];

  if (!apiUrl || !apiToken) {
    return new Response(
      JSON.stringify({
        ok: false,
        des: [],
        error:
          'Backend not configured. Set DE_API_URL and DE_API_TOKEN in ' +
          'Cloudflare Pages → Settings → Environment Variables. See README.',
      }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      }
    );
  }

  try {
    // Build upstream path: params.path is the [[path]] catch-all segment(s)
    const pathParam = Array.isArray(context.params.path)
      ? context.params.path.join('/')
      : context.params.path || '';
    const upstream = apiUrl.replace(/\/$/, '') + '/de/' + pathParam;

    const body =
      context.request.method !== 'GET' ? await context.request.text() : undefined;

    const resp = await fetch(upstream, {
      method: context.request.method,
      headers: {
        Authorization: 'Bearer ' + apiToken,
        'Content-Type': 'application/json',
      },
      body,
    });

    // Parse response safely — backend may occasionally return non-JSON on errors
    const text = await resp.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { ok: false, error: text || 'Empty response from backend' };
    }

    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
      },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}

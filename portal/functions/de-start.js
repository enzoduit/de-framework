// POST /de-start — start a DE session (shorthand used by the portal)
export async function onRequestPost(context) {
  const apiUrl = context.env.DE_API_URL;
  const apiToken = context.env['DE_API_TOKEN'];

  if (!apiUrl || !apiToken) {
    return new Response(
      JSON.stringify({
        ok: false,
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
    const body = await context.request.text();
    const resp = await fetch(apiUrl.replace(/\/$/, '') + '/de-start', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + apiToken,
        'Content-Type': 'application/json',
      },
      body,
    });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { ok: false, error: text }; }
    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    },
  });
}

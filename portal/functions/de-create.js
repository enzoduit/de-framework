// POST /de/create — proxy to backend API
export async function onRequestPost({ request, env }) {
  const upstream = env.DE_API_URL;
  const token = env.DE_API_TOKEN;
  if (!upstream || !token) {
    return new Response(JSON.stringify({ ok: false, error: 'DE_API_URL or DE_API_TOKEN not configured' }), {
      status: 500, headers: { 'Content-Type': 'application/json' },
    });
  }
  const body = await request.text();
  const resp = await fetch(`${upstream}/de/create`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body,
  });
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  });
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

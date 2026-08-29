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

  try {
    const pathParam = Array.isArray(context.params.path)
      ? context.params.path.join('/')
      : (context.params.path || '');
    const upstream = 'https://decisions.enzoduit.com/de/' + pathParam;

    const body = context.request.method !== 'GET'
      ? await context.request.text()
      : undefined;

    const resp = await fetch(upstream, {
      method: context.request.method,
      headers: {
        'Authorization': 'Bearer os-decisions-2026-xK9mP',
        'Content-Type': 'application/json',
      },
      body,
    });

    const data = await resp.json();
    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
      },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}

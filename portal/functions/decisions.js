// GET /decisions — return pending and resolved decisions
export async function onRequest(context) {
  const apiUrl = context.env.DE_API_URL;
  const apiToken = context.env['DE_API_TOKEN'];

  if (!apiUrl || !apiToken) {
    return new Response(
      JSON.stringify({ pending: [], resolved: [], ok: false, error: 'Backend not configured.' }),
      { status: 503, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } }
    );
  }

  try {
    const resp = await fetch(apiUrl.replace(/\/$/, '') + '/decisions', {
      headers: { Authorization: 'Bearer ' + apiToken },
    });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { pending: [], error: text }; }
    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ pending: [], error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}

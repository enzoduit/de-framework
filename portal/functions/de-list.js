// GET /de-list — return all Digital Employees with summary info
export async function onRequest(context) {
  const apiUrl = context.env.DE_API_URL;
  const apiToken = context.env['DE_API_TOKEN'];

  if (!apiUrl || !apiToken) {
    return new Response(
      JSON.stringify({
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
    const resp = await fetch(apiUrl.replace(/\/$/, '') + '/de-list', {
      headers: { Authorization: 'Bearer ' + apiToken },
    });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { des: [], error: text }; }
    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ des: [], error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}

export async function onRequestPost(context) {
  try {
    const body = await context.request.json();
    const resp = await fetch('https://decisions.enzoduit.com/update-voice-prompt?t=' + Date.now(), {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer os-decisions-2026-xK9mP',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    return new Response(JSON.stringify(data), {
      headers: { 'Content-Type': 'application/json' }
    });
  } catch(e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type'
    }
  });
}

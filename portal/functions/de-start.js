export async function onRequestPost(context) {
  try {
    const body = await context.request.json();
    const deName = body.de_name;
    if (!deName) {
      return new Response(JSON.stringify({error: 'missing de_name'}), {
        status: 400,
        headers: {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
      });
    }
    const resp = await fetch('https://decisions.enzoduit.com/de/' + deName + '/sessions/start', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer os-decisions-2026-xK9mP',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        trigger_type: body.trigger_type || 'user',
        trigger_context: body.trigger_context || 'Manual start via portal',
      }),
    });
    const data = await resp.json();
    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
    });
  } catch (e) {
    return new Response(JSON.stringify({error: e.message}), {
      status: 500,
      headers: {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
    });
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}

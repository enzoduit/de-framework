export async function onRequestGet(context) {
  try {
    const resp = await fetch('https://decisions.enzoduit.com/tasks?t=' + Date.now(), {
      headers: { 'Authorization': 'Bearer os-decisions-2026-xK9mP' },
      cf: { cacheEverything: false },
    });
    const data = await resp.json();
    return new Response(JSON.stringify(data), {
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store'
      },
    });
  } catch(e) {
    return new Response(JSON.stringify({error: e.message, open: [], done: []}), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

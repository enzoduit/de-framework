// CF Pages Function: ElevenLabs Signed URL Proxy
// Keeps ElevenLabs API key server-side (env var ELEVENLABS_API_KEY)
// Called by agent-portal/index.html instead of ElevenLabs API directly

export async function onRequest(context) {
  const { env } = context;
  const apiKey = env.ELEVENLABS_API_KEY;
  
  if (!apiKey) {
    return new Response(JSON.stringify({ error: 'ElevenLabs API key not configured' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  const agentId = 'agent_1701kxnn22xeegya5wfaxwvm7f52';
  
  try {
    const response = await fetch(
      `https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id=${agentId}`,
      { headers: { 'xi-api-key': apiKey } }
    );
    
    if (!response.ok) {
      return new Response(JSON.stringify({ error: 'ElevenLabs API error', status: response.status }), {
        status: response.status,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    const data = await response.json();
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Proxy error', message: err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

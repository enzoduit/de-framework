import json, secrets, time

_CODES = {}

def handle_create(handler, body=None):
    if body is None:
        length = int(handler.headers.get('Content-Length', 0))
        body = json.loads(handler.rfile.read(length).decode()) if length else {}
    code = secrets.token_urlsafe(8)
    _CODES[code] = {'expires': time.time() + 86400, 'url': body.get('url',''), 'token': body.get('token','')}
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(json.dumps({'code': code}).encode())

def handle_exchange(handler, code):
    entry = _CODES.get(code)
    if not entry or time.time() > entry['expires']:
        _CODES.pop(code, None)
        handler.send_response(404)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        handler.wfile.write(b'{"error":"expired"}')
        return
    del _CODES[code]
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(json.dumps({'url': entry['url'], 'token': entry['token']}).encode())

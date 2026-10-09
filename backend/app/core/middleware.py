"""ASGI middleware: request id, body-size limit and basic security headers.

Body limits (SOA 5.6): 16 KB for POST /v1/chat, 1 KB for any other request body.
Request bodies are read (and counted) before the app sees them, so a missing or false
Content-Length does not help; at 16 KB at most, buffering them costs nothing.
"""

import json

from app.core.errors import error_body
from app.core.request_context import new_request_id

CHAT_PATH = "/v1/chat"
CHAT_LIMIT = 16 * 1024
DEFAULT_LIMIT = 1024


class ApiMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware) so streaming responses are not buffered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        rid = new_request_id(headers.get(b"x-request-id", b"").decode("latin-1") or None)
        limit = CHAT_LIMIT if scope.get("path") == CHAT_PATH else DEFAULT_LIMIT

        declared = headers.get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await _send_413(send, rid)

        if scope.get("method") in ("POST", "PUT", "PATCH"):
            # Read the (small) body first, counting bytes, then replay it to the app.
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    break
                size += len(message.get("body", b""))
                if size > limit:
                    return await _send_413(send, rid)
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            body, replayed = b"".join(chunks), False

            async def replay_receive():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            app_receive = replay_receive
        else:
            app_receive = receive

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-request-id", rid.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, app_receive, send_with_headers)


async def _send_413(send, rid):
    body = json.dumps(error_body("MM-REQ-002", "The request body is too large.")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-request-id", rid.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})

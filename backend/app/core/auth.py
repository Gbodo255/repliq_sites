"""Optional password protection for public deployments.

When the ``APP_PASSWORD`` environment variable is set, every HTTP request and
WebSocket handshake must carry HTTP Basic credentials with that password (any
user name). The browser shows its native login prompt once and then re-sends
the credentials automatically. ``/api/health`` stays open for health checks.
Without ``APP_PASSWORD`` the middleware is a no-op (local use).
"""
from __future__ import annotations

import base64
import hmac


class BasicAuthMiddleware:
    def __init__(self, app, password: str) -> None:
        self.app = app
        self.password = password.encode("utf-8")

    def _ok(self, headers: list[tuple[bytes, bytes]]) -> bool:
        for k, v in headers:
            if k.lower() == b"authorization" and v[:6].lower() == b"basic ":
                try:
                    raw = base64.b64decode(v[6:].strip())
                except ValueError:
                    return False
                _, _, pwd = raw.partition(b":")
                return hmac.compare_digest(pwd, self.password)
        return False

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or scope.get("path") == "/api/health":
            return await self.app(scope, receive, send)
        if self._ok(scope.get("headers") or []):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"www-authenticate", b'Basic realm="Replicator", charset="UTF-8"'),
                        (b"content-type", b"text/plain; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": b"Authentication required"})

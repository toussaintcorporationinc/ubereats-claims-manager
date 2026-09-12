from app.main import app as tennet_app


class StripApiPrefix:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = dict(scope)
                stripped = path[4:] or "/"
                scope["path"] = stripped
                if scope.get("raw_path"):
                    scope["raw_path"] = stripped.encode("utf-8")
        await self.inner(scope, receive, send)


app = StripApiPrefix(tennet_app)

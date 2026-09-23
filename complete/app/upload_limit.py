"""Bound multipart requests before the form parser can spool unbounded input."""
from starlette.responses import JSONResponse


class UploadLimitMiddleware:
    def __init__(self, app, limit=10 * 1024 * 1024 + 65536):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").endswith("/attachments"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            size = int(headers.get(b"content-length", b"0"))
        except ValueError:
            size = self.limit + 1
        rejection = JSONResponse({"detail": {"code": "file_too_large", "message": "Файл должен быть не больше 10 МБ."}}, status_code=413)
        if size > self.limit:
            await rejection(scope, receive, send)
            return
        chunks, size = [], 0
        while True:
            part = await receive()
            if part["type"] == "http.disconnect":
                return
            body = part.get("body", b"")
            size += len(body)
            if size > self.limit:
                await rejection(scope, receive, send)
                return
            chunks.append(body)
            if not part.get("more_body", False):
                break
        payload = b"".join(chunks)
        delivered = False

        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        await self.app(scope, limited_receive, send)

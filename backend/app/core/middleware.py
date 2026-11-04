"""Early request-size guard for the upload endpoint.

Starlette spools a whole multipart upload to disk before the route handler runs, so an
oversized upload would be fully received before the handler could reject it. This middleware
rejects requests whose declared Content-Length is clearly over the limit before any body
is read. Uploads without a Content-Length (chunked) are still limited by the streaming
check in `services.document_storage`, but only after being received (see docs/limitations.md).
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

MULTIPART_OVERHEAD_BYTES = 1024 * 1024  # boundaries/headers allowance on top of the file size


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, path: str = "/api/documents") -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"].rstrip("/") == self.path:
            headers = dict(scope["headers"])
            declared = headers.get(b"content-length", b"")
            limit = get_settings().max_upload_size_bytes
            if declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD_BYTES:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "code": "file_too_large",
                            "message": f"The upload exceeds the maximum size of {limit // (1024 * 1024)} MB.",
                        }
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

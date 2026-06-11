from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized requests before they reach validation.

    Declared Content-Length is checked here; chunked bodies are bounded
    downstream by Pydantic field length limits.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        length = request.headers.get("content-length")
        if length and int(length) > get_settings().max_request_bytes:
            return JSONResponse(
                status_code=413,
                media_type="application/problem+json",
                content={
                    "type": "about:blank",
                    "title": "Payload Too Large",
                    "status": 413,
                    "detail": "Request body exceeds the allowed size.",
                    "request_id": request.headers.get("x-request-id", ""),
                },
            )
        return await call_next(request)

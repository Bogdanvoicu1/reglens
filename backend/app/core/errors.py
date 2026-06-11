"""Consistent error responses (RFC 7807 problem+json).

Every error body carries: type, title, status, detail, request_id. The
`detail` key is also what the frontend reads, so handlers preserve it.
Unhandled exceptions return a generic 500 — internals are never leaked.
"""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

log = structlog.get_logger()

PROBLEM_CONTENT_TYPE = "application/problem+json"

_TITLES = {
    401: "Unauthorized",
    404: "Not Found",
    413: "Payload Too Large",
    422: "Validation Error",
    429: "Too Many Requests",
    500: "Internal Server Error",
    501: "Not Implemented",
}


def _problem(request: Request, status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type=PROBLEM_CONTENT_TYPE,
        content={
            "type": "about:blank",
            "title": _TITLES.get(status_code, "Error"),
            "status": status_code,
            "detail": detail,
            "request_id": request.headers.get("x-request-id", ""),
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        response = _problem(request, exc.status_code, str(exc.detail))
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        return _problem(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{loc}: {first.get('msg', 'invalid input')}",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return _problem(
            request, status.HTTP_500_INTERNAL_SERVER_ERROR, "An internal error occurred."
        )

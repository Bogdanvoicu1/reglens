from fastapi import FastAPI
from prometheus_client import make_asgi_app
from starlette.middleware.cors import CORSMiddleware

from app.api.routes import assessments, chat, conversations, corpora, health
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.observability.hardening import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.observability.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RegLens API",
        version="0.1.0",
        description="Grounded compliance Q&A over the EU AI Act and GDPR.",
    )
    register_error_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router, tags=["health"])
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(corpora.router)
    app.include_router(assessments.router)
    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()

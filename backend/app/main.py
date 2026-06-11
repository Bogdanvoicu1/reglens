from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.api.routes import chat, health
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.observability.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RegLens API",
        version="0.1.0",
        description="Grounded compliance Q&A over the EU AI Act and GDPR.",
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router, tags=["health"])
    app.include_router(chat.router)
    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()

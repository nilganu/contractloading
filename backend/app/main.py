"""FastAPI app entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.contracts import router as contracts_router
from .config import get_settings
from .db import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Hotel Contract Extraction API",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        init_db()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(contracts_router)
    return app


app = create_app()

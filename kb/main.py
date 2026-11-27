"""FastAPI 装配。

运行：
    uvicorn kb.main:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

from fastapi import FastAPI

from kb.api import documents, search_api, sources


def create_app() -> FastAPI:
    app = FastAPI(title="KB Visibility Filter", version="1.0.0")
    app.include_router(search_api.router)
    app.include_router(sources.router)
    app.include_router(documents.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()

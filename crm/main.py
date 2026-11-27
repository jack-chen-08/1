"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from crm import __version__
from crm.api.duplicates import router as duplicates_router
from crm.api.opportunities import router as opportunities_router
from crm.permissions.matrix_loader import get_matrix


def create_app() -> FastAPI:
    app = FastAPI(
        title="CRM · 商机权限与数据范围",
        version=__version__,
        description="招商商机的数据范围、金额可见性、撞单投影与漏斗汇总一致性。",
    )
    app.include_router(opportunities_router)
    app.include_router(duplicates_router)

    @app.get("/healthz")
    def healthz() -> dict:
        matrix = get_matrix()
        return {
            "status": "ok",
            "version": __version__,
            "policy_version": matrix.policy_version,
            "roles": sorted(matrix.roles),
        }

    return app


app = create_app()

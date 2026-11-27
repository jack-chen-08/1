"""API 层。"""

from crm.api.opportunities import router as opportunities_router
from crm.api.duplicates import router as duplicates_router

__all__ = ["opportunities_router", "duplicates_router"]

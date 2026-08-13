from fastapi import APIRouter

from app.api.v1.routes import admin, assets, reports, telegram, users, webhooks

router = APIRouter()

router.include_router(assets.router, prefix="/assets", tags=["Assets"])
router.include_router(reports.router, prefix="/reports", tags=["Reports"])
router.include_router(users.router, prefix="/users", tags=["Users"])
router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
router.include_router(telegram.router, prefix="/telegram", tags=["Telegram"])
router.include_router(admin.router, prefix="/admin", tags=["Admin"])

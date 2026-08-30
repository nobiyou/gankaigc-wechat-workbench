from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.settings import settings
from app.services.workbench import initialize_store
from app.services.wechat_mp_automation import WechatMpAutomationScheduler

Path(settings.generated_assets_dir).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_store()
    scheduler = WechatMpAutomationScheduler()
    app.state.wechat_mp_automation_scheduler = scheduler
    if settings.wechat_mp_automation_enabled:
        scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)
app.mount("/generated-assets", StaticFiles(directory=Path(settings.generated_assets_dir)), name="generated-assets")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": settings.app_name}

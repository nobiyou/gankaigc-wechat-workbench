from fastapi import APIRouter

from app.services.workbench import get_dashboard_summary as load_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary() -> dict[str, object]:
    return load_dashboard_summary()

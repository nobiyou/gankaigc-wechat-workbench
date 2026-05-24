from typing import Literal

from fastapi import APIRouter, Query

from app.services.workbench import get_background_task, list_background_task_logs

router = APIRouter(prefix="/background-tasks", tags=["background-tasks"])


@router.get("/logs")
def get_background_task_logs(
    scope: Literal["all", "pipeline"] = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    return [item.model_dump() for item in list_background_task_logs(scope=scope, limit=limit)]


@router.get("/{task_id}")
def get_background_task_detail(task_id: str) -> dict[str, object]:
    return get_background_task(task_id).model_dump()

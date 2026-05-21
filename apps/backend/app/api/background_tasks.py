from fastapi import APIRouter

from app.services.workbench import get_background_task

router = APIRouter(prefix="/background-tasks", tags=["background-tasks"])


@router.get("/{task_id}")
def get_background_task_detail(task_id: str) -> dict[str, object]:
    return get_background_task(task_id).model_dump()

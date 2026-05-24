from pydantic import BaseModel


class BackgroundTaskSubmission(BaseModel):
    task_id: str
    job_type: str
    status: str
    created_at: str


class BackgroundTaskDetail(BackgroundTaskSubmission):
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: dict[str, object] | None = None


class TaskLogEntry(BaseModel):
    id: int | str
    task_type: str
    status: str
    entity_slug: str | None = None
    entity_type: str | None = None
    created_at: str
    background_task_id: str | None = None

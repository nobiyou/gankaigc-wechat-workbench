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

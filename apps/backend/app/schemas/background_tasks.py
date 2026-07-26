from pydantic import BaseModel


class BackgroundTaskSubmission(BaseModel):
    task_id: str
    job_type: str
    status: str
    created_at: str


class BackgroundTaskErrorContext(BaseModel):
    type: str | None = None
    status_code: int | None = None
    detail: str | None = None
    cover_image_route_label: str | None = None
    cover_image_route_model: str | None = None
    cover_image_route_base_url: str | None = None
    fallback_account_pool_diagnosis_status: str | None = None
    fallback_account_pool_diagnosis_label: str | None = None
    fallback_account_pool_diagnosis_note: str | None = None


class BackgroundTaskDetail(BackgroundTaskSubmission):
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    error_context: BackgroundTaskErrorContext | None = None
    result: dict[str, object] | None = None


class TaskLogEntry(BaseModel):
    id: int | str
    task_type: str
    status: str
    entity_slug: str | None = None
    entity_type: str | None = None
    created_at: str
    background_task_id: str | None = None

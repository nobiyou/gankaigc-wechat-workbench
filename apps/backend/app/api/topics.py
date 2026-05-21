from fastapi import APIRouter, status

from app.schemas.projects import BatchCreateProjectsRequest, ProjectCreate
from app.schemas.topics import TopicUpdate
from app.services.workbench import create_project_from_topic, list_topics, submit_background_task, update_topic

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("")
def get_topics() -> list[dict[str, object]]:
    return [topic.model_dump() for topic in list_topics()]


@router.patch("/{topic_slug}")
def patch_topic(topic_slug: str, payload: TopicUpdate) -> dict[str, object]:
    return update_topic(topic_slug, payload).model_dump()


@router.post("/batch-create-projects", status_code=status.HTTP_202_ACCEPTED)
def post_batch_create_projects(payload: BatchCreateProjectsRequest) -> dict[str, object]:
    return submit_background_task(
        "batch_create_projects",
        {"topic_slugs": payload.topic_slugs},
    ).model_dump()


@router.post("/{topic_slug}/create-project", status_code=status.HTTP_201_CREATED)
def post_topic_create_project(topic_slug: str, payload: ProjectCreate) -> dict[str, object]:
    return create_project_from_topic(topic_slug, payload).model_dump()

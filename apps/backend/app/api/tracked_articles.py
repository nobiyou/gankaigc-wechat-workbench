from fastapi import APIRouter, status

from app.schemas.projects import BatchGenerateTrackedArticleTopicsRequest
from app.schemas.topics import TopicCreateFromTrend
from app.schemas.tracked_articles import TrackedArticleCreate
from app.services.workbench import (
    create_topic_from_tracked_article,
    create_tracked_article,
    generate_topic_from_tracked_article,
    list_tracked_articles,
    submit_background_task,
)

router = APIRouter(prefix="/tracked-articles", tags=["tracked-articles"])


@router.get("")
def get_tracked_articles() -> list[dict[str, object]]:
    return [article.model_dump() for article in list_tracked_articles()]


@router.post("", status_code=status.HTTP_201_CREATED)
def post_tracked_article(payload: TrackedArticleCreate) -> dict[str, object]:
    return create_tracked_article(payload).model_dump()


@router.post("/{article_slug}/to-topic", status_code=status.HTTP_201_CREATED)
def post_tracked_article_to_topic(article_slug: str, payload: TopicCreateFromTrend) -> dict[str, object]:
    return create_topic_from_tracked_article(article_slug, payload).model_dump()


@router.post("/{article_slug}/generate-topic", status_code=status.HTTP_201_CREATED)
def post_generate_topic_from_tracked_article(article_slug: str) -> dict[str, object]:
    return generate_topic_from_tracked_article(article_slug).model_dump()


@router.post("/batch-generate-topics", status_code=status.HTTP_202_ACCEPTED)
def post_batch_generate_topics_from_tracked_articles(payload: BatchGenerateTrackedArticleTopicsRequest) -> dict[str, object]:
    return submit_background_task(
        "batch_generate_topics_from_tracked_articles",
        {"article_slugs": payload.article_slugs},
    ).model_dump()

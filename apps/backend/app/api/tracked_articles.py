from fastapi import APIRouter, status

from app.schemas.projects import BatchGenerateTrackedArticleTopicsRequest
from app.schemas.topics import TopicCreateFromTrend
from app.schemas.tracked_articles import TrackedArticleBatchEnrichRequest, TrackedArticleCreate
from app.services.wechat_mp_client import get_wechat_mp_client
from app.services.workbench import (
    create_topic_from_tracked_article,
    create_tracked_article,
    enrich_tracked_article_metadata,
    generate_topic_from_tracked_article,
    list_tracked_articles,
    refresh_tracked_article_body,
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


@router.post("/{article_slug}/refresh-body")
def post_refresh_tracked_article_body(article_slug: str) -> dict[str, object]:
    article = next((item for item in list_tracked_articles() if item.slug == article_slug), None)
    if article is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Tracked article not found")

    body_markdown, body_source = get_wechat_mp_client().fetch_article_body(article.url, article.summary)
    return refresh_tracked_article_body(
        article_slug,
        body_markdown=body_markdown,
        body_source=body_source,
    ).model_dump()


@router.post("/{article_slug}/enrich-metadata")
def post_enrich_tracked_article_metadata(article_slug: str) -> dict[str, object]:
    return enrich_tracked_article_metadata(article_slug).model_dump()


@router.post("/enrich-metadata/background", status_code=status.HTTP_202_ACCEPTED)
def post_enrich_tracked_articles_metadata_background(payload: TrackedArticleBatchEnrichRequest) -> dict[str, object]:
    return submit_background_task(
        "enrich_tracked_articles_metadata",
        {"article_slugs": payload.article_slugs},
    ).model_dump()


@router.post("/batch-generate-topics", status_code=status.HTTP_202_ACCEPTED)
def post_batch_generate_topics_from_tracked_articles(payload: BatchGenerateTrackedArticleTopicsRequest) -> dict[str, object]:
    return submit_background_task(
        "batch_generate_topics_from_tracked_articles",
        {"article_slugs": payload.article_slugs},
    ).model_dump()

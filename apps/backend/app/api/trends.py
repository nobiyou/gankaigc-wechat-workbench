from fastapi import APIRouter, status

from app.schemas.projects import BatchGenerateTopicsRequest
from app.schemas.topics import TopicCreateFromTrend
from app.schemas.trends import TrendCreate, TrendFetchResponse, TrendImportRequest, TrendUpdate
from app.services.workbench import (
    batch_generate_topics,
    create_topic_from_trend,
    create_trend,
    fetch_trends_from_live_sources,
    generate_topic_from_trend,
    import_trends,
    list_trends,
    submit_background_task,
    update_trend,
)

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("")
def get_trends() -> list[dict[str, object]]:
    return [trend.model_dump() for trend in list_trends()]


@router.post("", status_code=status.HTTP_201_CREATED)
def post_trend(payload: TrendCreate) -> dict[str, object]:
    return create_trend(payload).model_dump()


@router.post("/import", status_code=status.HTTP_201_CREATED)
def post_import_trends(payload: TrendImportRequest) -> dict[str, object]:
    return import_trends(payload.raw_text).model_dump()


@router.post("/fetch", status_code=status.HTTP_201_CREATED)
def post_fetch_trends() -> dict[str, object]:
    return TrendFetchResponse(**fetch_trends_from_live_sources()).model_dump()


@router.patch("/{trend_slug}")
def patch_trend(trend_slug: str, payload: TrendUpdate) -> dict[str, object]:
    return update_trend(trend_slug, payload).model_dump()


@router.post("/{trend_slug}/to-topic", status_code=status.HTTP_201_CREATED)
def post_trend_to_topic(trend_slug: str, payload: TopicCreateFromTrend) -> dict[str, object]:
    return create_topic_from_trend(trend_slug, payload).model_dump()


@router.post("/{trend_slug}/generate-topic", status_code=status.HTTP_201_CREATED)
def post_generate_topic(trend_slug: str) -> dict[str, object]:
    return generate_topic_from_trend(trend_slug).model_dump()


@router.post("/batch-generate-topics", status_code=status.HTTP_202_ACCEPTED)
def post_batch_generate_topics(payload: BatchGenerateTopicsRequest) -> dict[str, object]:
    return submit_background_task(
        "batch_generate_topics",
        {"trend_slugs": payload.trend_slugs},
    ).model_dump()

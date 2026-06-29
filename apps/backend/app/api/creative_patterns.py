from fastapi import APIRouter, Query

from app.services.workbench import list_reusable_patterns

router = APIRouter(prefix="/creative-patterns", tags=["creative-patterns"])


@router.get("")
def get_creative_patterns(
    pattern_type: str | None = Query(default=None),
    source_project_slug: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> list[dict[str, object]]:
    return [
        pattern.model_dump()
        for pattern in list_reusable_patterns(
            pattern_type=pattern_type,
            source_project_slug=source_project_slug,
            include_archived=include_archived,
        )
    ]

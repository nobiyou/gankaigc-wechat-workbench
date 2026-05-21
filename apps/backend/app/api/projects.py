from fastapi import APIRouter, status

from app.schemas.projects import (
    BatchContinueProjectsRequest,
    DraftPolishAction,
    ProjectRetroCreate,
    ProjectStageUpdate,
    PublishReviewAction,
)
from app.services.workbench import (
    approve_publish_package,
    build_publish_package,
    generate_draft,
    generate_assets,
    generate_outline,
    get_project_detail,
    get_project_versions,
    list_projects,
    polish_draft,
    record_project_retro,
    regenerate_from_review,
    restore_assets_version,
    restore_outline_version,
    restore_draft_version,
    restore_publish_package_version,
    request_publish_package_revision,
    submit_background_task,
    update_project_stage,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def get_projects() -> list[dict[str, object]]:
    return [project.model_dump() for project in list_projects()]


@router.get("/{project_slug}")
def get_project(project_slug: str) -> dict[str, object]:
    return get_project_detail(project_slug).model_dump()


@router.get("/{project_slug}/versions")
def get_project_versions_view(project_slug: str) -> dict[str, object]:
    return get_project_versions(project_slug).model_dump()


@router.patch("/{project_slug}")
def patch_project(project_slug: str, payload: ProjectStageUpdate) -> dict[str, object]:
    return update_project_stage(project_slug, payload).model_dump()


@router.post("/batch-continue", status_code=status.HTTP_202_ACCEPTED)
def post_batch_continue_projects(payload: BatchContinueProjectsRequest) -> dict[str, object]:
    return submit_background_task(
        "batch_continue_projects",
        {"project_slugs": payload.project_slugs},
    ).model_dump()


@router.post("/{project_slug}/generate-outline", status_code=201)
def post_generate_outline(project_slug: str) -> dict[str, object]:
    return generate_outline(project_slug).model_dump()


@router.post("/{project_slug}/generate-draft", status_code=201)
def post_generate_draft(project_slug: str) -> dict[str, object]:
    return generate_draft(project_slug).model_dump()


@router.post("/{project_slug}/polish-draft", status_code=201)
def post_polish_draft(project_slug: str, payload: DraftPolishAction) -> dict[str, object]:
    return polish_draft(project_slug, instruction=payload.instruction).model_dump()


@router.post("/{project_slug}/generate-assets", status_code=201)
def post_generate_assets(project_slug: str) -> dict[str, object]:
    return generate_assets(project_slug).model_dump()


@router.post("/{project_slug}/build-publish-package", status_code=201)
def post_build_publish_package(project_slug: str) -> dict[str, object]:
    return build_publish_package(project_slug).model_dump()


@router.post("/{project_slug}/approve-publish-package")
def post_approve_publish_package(project_slug: str, payload: PublishReviewAction) -> dict[str, object]:
    return approve_publish_package(project_slug, reviewer=payload.reviewer, comment=payload.comment).model_dump()


@router.post("/{project_slug}/retro")
def post_project_retro(project_slug: str, payload: ProjectRetroCreate) -> dict[str, object]:
    return record_project_retro(project_slug, payload).model_dump()


@router.post("/{project_slug}/request-publish-revision")
def post_request_publish_revision(project_slug: str, payload: PublishReviewAction) -> dict[str, object]:
    return request_publish_package_revision(project_slug, reviewer=payload.reviewer, comment=payload.comment).model_dump()


@router.post("/{project_slug}/regenerate-from-review", status_code=status.HTTP_202_ACCEPTED)
def post_regenerate_from_review(project_slug: str) -> dict[str, object]:
    return submit_background_task(
        "regenerate_from_review",
        {"project_slug": project_slug},
    ).model_dump()


@router.post("/{project_slug}/restore-draft/{version}", status_code=201)
def post_restore_draft_version(project_slug: str, version: int) -> dict[str, object]:
    return restore_draft_version(project_slug, version).model_dump()


@router.post("/{project_slug}/restore-outline/{version}", status_code=201)
def post_restore_outline_version(project_slug: str, version: int) -> dict[str, object]:
    return restore_outline_version(project_slug, version).model_dump()


@router.post("/{project_slug}/restore-assets/{version}", status_code=201)
def post_restore_assets_version(project_slug: str, version: int) -> dict[str, object]:
    return restore_assets_version(project_slug, version).model_dump()


@router.post("/{project_slug}/restore-publish-package/{version}", status_code=201)
def post_restore_publish_package_version(project_slug: str, version: int) -> dict[str, object]:
    return restore_publish_package_version(project_slug, version).model_dump()

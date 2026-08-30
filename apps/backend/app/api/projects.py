from fastapi import APIRouter, status

from app.schemas.creative_workflow import PromoteCreativePatternAction
from app.schemas.projects import (
    BatchContinueProjectsRequest,
    BuildPublishPackageAction,
    DiagnoseDraftAction,
    DraftPolishAction,
    GenerateAssetsAction,
    ProjectRetroCreate,
    ProjectStageUpdate,
    PublishReviewAction,
)
from app.services.workbench import (
    approve_publish_package,
    adopt_strategy_card,
    build_publish_package,
    diagnose_draft,
    generate_creative_review_report,
    generate_draft,
    generate_assets,
    generate_outline,
    generate_strategy_package,
    get_project_detail,
    get_project_versions,
    list_projects,
    polish_draft,
    promote_creative_pattern,
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


@router.post("/{project_slug}/generate-strategy-package", status_code=201)
def post_generate_strategy_package(project_slug: str) -> dict[str, object]:
    return generate_strategy_package(project_slug).model_dump()


@router.post("/{project_slug}/adopt-strategy-card/{version}")
def post_adopt_strategy_card(project_slug: str, version: int) -> dict[str, object]:
    return adopt_strategy_card(project_slug, version).model_dump()


@router.post("/{project_slug}/generate-draft", status_code=201)
def post_generate_draft(project_slug: str) -> dict[str, object]:
    return generate_draft(project_slug).model_dump()


@router.post("/{project_slug}/generate-creative-review-report", status_code=201)
def post_generate_creative_review_report(project_slug: str) -> dict[str, object]:
    return generate_creative_review_report(project_slug).model_dump()


@router.post("/{project_slug}/promote-creative-pattern", status_code=201)
def post_promote_creative_pattern(project_slug: str, payload: PromoteCreativePatternAction) -> dict[str, object]:
    return promote_creative_pattern(project_slug, payload).model_dump()


@router.post("/{project_slug}/diagnose-draft", status_code=201)
def post_diagnose_draft(project_slug: str, payload: DiagnoseDraftAction | None = None) -> dict[str, object]:
    return diagnose_draft(
        project_slug,
        draft_version=payload.draft_version if payload else None,
    ).model_dump()


@router.post("/{project_slug}/polish-draft", status_code=201)
def post_polish_draft(project_slug: str, payload: DraftPolishAction) -> dict[str, object]:
    return polish_draft(
        project_slug,
        instruction=payload.instruction,
        diagnosis_report_version=payload.diagnosis_report_version,
        objective_key=payload.objective_key,
    ).model_dump()


@router.post("/{project_slug}/generate-assets", status_code=201)
def post_generate_assets(project_slug: str, payload: GenerateAssetsAction | None = None) -> dict[str, object]:
    return generate_assets(
        project_slug,
        polish_before_generate=payload.polish_before_generate if payload else False,
        polish_instruction=payload.polish_instruction if payload else None,
    ).model_dump()


@router.post("/{project_slug}/regenerate-cover-image", status_code=status.HTTP_202_ACCEPTED)
def post_regenerate_cover_image(project_slug: str) -> dict[str, object]:
    return submit_background_task(
        "regenerate_cover_image",
        {"project_slug": project_slug},
    ).model_dump()


@router.post("/{project_slug}/build-publish-package", status_code=201)
def post_build_publish_package(
    project_slug: str,
    payload: BuildPublishPackageAction | None = None,
) -> dict[str, object]:
    return build_publish_package(
        project_slug,
        wechat_html_style_key=payload.wechat_html_style_key if payload else None,
    ).model_dump()


@router.post("/{project_slug}/build-publish-package/background", status_code=status.HTTP_202_ACCEPTED)
def post_build_publish_package_background(
    project_slug: str,
    payload: BuildPublishPackageAction | None = None,
) -> dict[str, object]:
    if payload and payload.polish_before_generate:
        return submit_background_task(
            "polish_and_build_publish_package",
            {
                "project_slug": project_slug,
                "polish_instruction": payload.polish_instruction,
                "wechat_html_style_key": payload.wechat_html_style_key,
            },
        ).model_dump()
    return submit_background_task(
        "build_publish_package",
        {
            "project_slug": project_slug,
            "wechat_html_style_key": payload.wechat_html_style_key if payload else None,
        },
    ).model_dump()


@router.post("/{project_slug}/approve-publish-package")
def post_approve_publish_package(project_slug: str, payload: PublishReviewAction) -> dict[str, object]:
    return approve_publish_package(project_slug, reviewer=payload.reviewer, comment=payload.comment).model_dump()


@router.post("/{project_slug}/publish-wechat-draft/background", status_code=status.HTTP_202_ACCEPTED)
def post_publish_wechat_draft_background(project_slug: str) -> dict[str, object]:
    return submit_background_task(
        "publish_wechat_mp_draft",
        {"project_slug": project_slug},
    ).model_dump()


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

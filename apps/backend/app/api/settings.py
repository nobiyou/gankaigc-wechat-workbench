from fastapi import APIRouter

from app.services.ai_generator import get_ai_config_summary, run_ai_config_check, run_ai_image_config_check, run_ai_image_route_probe
from app.schemas.settings import DomainPackSummary
from app.services.prompt_templates import DEFAULT_DOMAIN_PROMPT_PACK, list_domain_prompt_packs, list_prompt_template_summaries

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/ai-config")
def get_ai_config() -> dict[str, object]:
    return get_ai_config_summary().model_dump()


@router.post("/ai-config/check")
def post_ai_config_check() -> dict[str, object]:
    return run_ai_config_check().model_dump()


@router.post("/ai-config/check-image")
def post_ai_image_config_check() -> dict[str, object]:
    return run_ai_image_config_check().model_dump()


@router.post("/ai-config/probe-image-routes")
def post_ai_image_route_probe() -> dict[str, object]:
    return run_ai_image_route_probe().model_dump()


@router.get("/domain-packs")
def get_domain_packs() -> list[dict[str, object]]:
    return [
        DomainPackSummary(
            key=pack.key,
            label=pack.label,
            audience=pack.audience,
            voice=pack.voice,
            constraints=pack.constraints,
            is_default=pack.key == DEFAULT_DOMAIN_PROMPT_PACK.key,
        ).model_dump()
        for pack in list_domain_prompt_packs()
    ]


@router.get("/prompt-templates")
def get_prompt_templates() -> list[dict[str, object]]:
    return [summary.model_dump() for summary in list_prompt_template_summaries()]

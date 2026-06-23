from pydantic import BaseModel


class AIConfigSummary(BaseModel):
    api_key_configured: bool
    base_url: str | None
    model: str
    image_model: str
    image_api_key_configured: bool
    image_base_url: str | None
    image_request_timeout_seconds: float
    image_uses_dedicated_config: bool
    reasoning_effort: str | None
    request_timeout_seconds: float


class AIConfigCheckResult(BaseModel):
    ok: bool
    status: str
    message: str
    checked_at: str


class DomainPackSummary(BaseModel):
    key: str
    label: str
    audience: str
    voice: str
    constraints: str
    is_default: bool


class PromptTemplateSummary(BaseModel):
    key: str
    label: str
    role: str
    objective: str
    output_fields: list[str]
    supports_tone_profile: bool
    supports_domain_pack: bool
    supports_review_feedback: bool

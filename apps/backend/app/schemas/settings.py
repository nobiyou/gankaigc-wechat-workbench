from pydantic import BaseModel, Field


class AIConfigSummary(BaseModel):
    api_key_configured: bool
    base_url: str | None
    model: str
    trust_env: bool
    image_model: str
    image_api_key_configured: bool
    image_base_url: str | None
    image_request_timeout_seconds: float
    image_generation_max_attempts: int
    image_uses_dedicated_config: bool
    creative_quality_retry_max_attempts: int
    allow_local_creative_fallbacks: bool
    image_fallback_route_configured: bool
    image_fallback_route_active: bool
    image_fallback_model: str | None
    image_fallback_base_url: str | None
    image_fallback_effective_model: str | None = None
    image_fallback_effective_base_url: str | None = None
    image_fallback_effective_request_timeout_seconds: float | None = None
    image_fallback_effective_api_key_configured: bool = False
    image_fallback_uses_inherited_model: bool | None = None
    image_fallback_uses_inherited_api_key: bool | None = None
    image_fallback_uses_inherited_base_url: bool | None = None
    image_fallback_uses_inherited_request_timeout: bool | None = None
    image_fallback_route_difference_labels: list[str]
    image_fallback_route_note: str | None
    image_fallback_route_recovery_actions: list[str] = Field(default_factory=list)
    image_fallback_route_config_hints: list[str] = Field(default_factory=list)
    image_fallback_route_env_example: list[str] = Field(default_factory=list)
    image_fallback_route_env_example_note: str | None = None
    image_fallback_account_pool_diagnosis_status: str
    image_fallback_account_pool_diagnosis_label: str
    image_fallback_account_pool_diagnosis_note: str
    reasoning_effort: str | None
    request_timeout_seconds: float


class AIConfigCheckResult(BaseModel):
    ok: bool
    status: str
    message: str
    checked_at: str
    route_label: str | None = None
    recovery_actions: list[str] = Field(default_factory=list)


class AIImageRouteProbeItem(BaseModel):
    route_label: str
    configured_model: str | None = None
    configured_base_url: str | None = None
    ok: bool
    status: str
    message: str
    checked_at: str
    recovery_actions: list[str] = Field(default_factory=list)


class AIImageRouteProbeResult(BaseModel):
    any_ok: bool
    checked_at: str
    routes: list[AIImageRouteProbeItem] = Field(default_factory=list)


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

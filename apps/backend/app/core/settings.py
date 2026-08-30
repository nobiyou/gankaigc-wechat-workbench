from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_repo_env_file() -> Path:
    current = Path(__file__).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate / ".env"
    return Path(".env").resolve()


class Settings(BaseSettings):
    app_name: str = "公众号内容工作台"
    api_prefix: str = "/api"
    debug: bool = True
    db_path: str = "C:/tmp/gankaigc-wechat-workbench.db"
    generated_assets_dir: str = "C:/tmp/gankaigc-wechat-workbench-assets"
    wechat_mp_session_path: str = "C:/tmp/gankaigc-wechat-workbench-wechat-session.json"
    wechat_mp_request_timeout_seconds: float = 15.0
    wx_channel_api_base_url: str = "http://127.0.0.1:2026"
    wx_channel_request_timeout_seconds: float = 15.0
    wechat_mp_automation_enabled: bool = True
    wechat_mp_automation_poll_interval_seconds: int = 30
    wechat_mp_automation_lease_seconds: int = 120
    trend_feed_urls: list[str] = []
    trend_fetch_request_timeout_seconds: float = 15.0
    trend_fetch_max_items_per_feed: int = 10
    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_request_timeout_seconds: float = 60.0
    openai_model: str = "gpt-5.4-mini"
    openai_trust_env: bool = False
    openai_reasoning_effort: str | None = "medium"
    openai_allow_local_creative_fallbacks: bool = False
    openai_creative_quality_retry_max_attempts: int = 0
    openai_image_api_key: str = ""
    openai_image_base_url: str | None = None
    openai_image_request_timeout_seconds: float | None = None
    openai_image_model: str = "gpt-image-1"
    openai_image_generation_max_attempts: int = 1
    openai_image_fallback_api_key: str = ""
    openai_image_fallback_base_url: str | None = None
    openai_image_fallback_request_timeout_seconds: float | None = None
    openai_image_fallback_model: str | None = None

    model_config = SettingsConfigDict(env_file=_resolve_repo_env_file(), env_file_encoding="utf-8")

    @property
    def effective_openai_image_api_key(self) -> str:
        return self.openai_image_api_key or self.openai_api_key

    @property
    def effective_openai_image_base_url(self) -> str | None:
        if self.openai_image_base_url not in (None, ""):
            return self.openai_image_base_url
        return self.openai_base_url

    @property
    def effective_openai_image_request_timeout_seconds(self) -> float:
        if self.openai_image_request_timeout_seconds is not None:
            return self.openai_image_request_timeout_seconds
        return self.openai_request_timeout_seconds

    @property
    def image_uses_dedicated_config(self) -> bool:
        return any(
            (
                bool(self.openai_image_api_key),
                self.openai_image_base_url not in (None, ""),
                self.openai_image_request_timeout_seconds is not None,
            )
        )

    @property
    def effective_openai_image_fallback_base_url(self) -> str | None:
        if self.openai_image_fallback_base_url not in (None, ""):
            return self.openai_image_fallback_base_url
        return self.effective_openai_image_base_url

    @property
    def effective_openai_image_fallback_request_timeout_seconds(self) -> float:
        if self.openai_image_fallback_request_timeout_seconds is not None:
            return self.openai_image_fallback_request_timeout_seconds
        return self.effective_openai_image_request_timeout_seconds

    @property
    def effective_openai_image_fallback_api_key(self) -> str:
        if self.openai_image_fallback_api_key:
            return self.openai_image_fallback_api_key
        return self.effective_openai_image_api_key

    @property
    def effective_openai_image_fallback_model(self) -> str:
        fallback_model = (self.openai_image_fallback_model or "").strip()
        if fallback_model:
            return fallback_model
        return self.openai_image_model

    @property
    def image_fallback_route_configured(self) -> bool:
        return any(
            (
                bool((self.openai_image_fallback_model or "").strip()),
                bool(self.openai_image_fallback_api_key),
                self.openai_image_fallback_base_url not in (None, ""),
                self.openai_image_fallback_request_timeout_seconds is not None,
            )
        )

    @property
    def image_fallback_route_active(self) -> bool:
        if not self.image_fallback_route_configured:
            return False
        return bool(self.image_fallback_route_difference_labels)

    @property
    def image_fallback_route_difference_labels(self) -> tuple[str, ...]:
        if not self.image_fallback_route_configured:
            return ()

        labels: list[str] = []
        if self.effective_openai_image_fallback_model != self.openai_image_model:
            labels.append("模型")
        if self.effective_openai_image_fallback_api_key != self.effective_openai_image_api_key:
            labels.append("Key")
        if self.effective_openai_image_fallback_base_url != self.effective_openai_image_base_url:
            labels.append("接口")
        if float(self.effective_openai_image_fallback_request_timeout_seconds) != float(
            self.effective_openai_image_request_timeout_seconds
        ):
            labels.append("超时")
        return tuple(labels)

    @property
    def image_fallback_route_note(self) -> str | None:
        if not self.image_fallback_route_configured:
            return "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。"
        if not self.image_fallback_route_active:
            return "已填写 fallback 字段，但生效后与主出图链路完全一致，所以当前还没有形成第二条图片 API。"
        labels = "、".join(self.image_fallback_route_difference_labels)
        return f"备用图片链路已生效；它与主出图链路的差异项：{labels}。"


settings = Settings()

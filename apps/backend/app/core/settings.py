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
    trend_feed_urls: list[str] = []
    trend_fetch_request_timeout_seconds: float = 15.0
    trend_fetch_max_items_per_feed: int = 10
    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_request_timeout_seconds: float = 60.0
    openai_model: str = "gpt-5-mini"
    openai_reasoning_effort: str | None = "medium"
    openai_image_model: str = "gpt-image-1"

    model_config = SettingsConfigDict(env_file=_resolve_repo_env_file(), env_file_encoding="utf-8")


settings = Settings()

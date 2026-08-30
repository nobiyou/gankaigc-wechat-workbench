from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


ScheduleTrigger = Literal["scheduled", "manual", "retry"]
AutomationRunStatus = Literal["queued", "running", "completed", "skipped", "failed", "claimed"]
AutomationArticleSource = Literal["wechat_mp", "wx_channel"]


def _validate_timezone(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {normalized}") from exc
    return normalized


class AutomationSubscriptionCreate(BaseModel):
    account_fakeid: str = Field(min_length=1, max_length=256)
    account_biz: str | None = Field(default=None, max_length=256)
    account_nickname: str = Field(min_length=1, max_length=128)
    account_alias: str | None = Field(default=None, max_length=128)
    account_avatar_url: str | None = Field(default=None, max_length=2000)
    article_source: AutomationArticleSource = "wechat_mp"
    enabled: bool = True
    schedule_time: str = Field(default="21:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Shanghai"
    fetch_limit: int = Field(default=1, ge=1, le=10)
    automatic_draft: bool = True

    @field_validator("account_fakeid", "account_nickname", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized

    @field_validator("account_biz", "account_alias", "account_avatar_url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def require_biz_for_wx_channel(self) -> "AutomationSubscriptionCreate":
        if self.article_source == "wx_channel" and not self.account_biz:
            raise ValueError("account_biz is required when article_source is wx_channel")
        return self

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone(value)


class AutomationSubscriptionUpdate(BaseModel):
    account_fakeid: str | None = Field(default=None, max_length=256)
    account_biz: str | None = Field(default=None, max_length=256)
    account_nickname: str | None = Field(default=None, min_length=1, max_length=128)
    account_alias: str | None = Field(default=None, max_length=128)
    account_avatar_url: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    article_source: AutomationArticleSource | None = None
    schedule_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str | None = None
    fetch_limit: int | None = Field(default=None, ge=1, le=10)
    automatic_draft: bool | None = None

    @field_validator("account_fakeid", "account_biz", "account_nickname", "account_alias", "account_avatar_url", mode="before")
    @classmethod
    def normalize_update_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("timezone")
    @classmethod
    def validate_update_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None


class AutomationSubscriptionItem(BaseModel):
    id: int
    account_fakeid: str
    account_biz: str | None = None
    account_nickname: str
    account_alias: str | None = None
    account_avatar_url: str | None = None
    article_source: AutomationArticleSource = "wechat_mp"
    enabled: bool
    schedule_time: str
    timezone: str
    fetch_limit: int
    automatic_draft: bool
    next_run_at: str | None = None
    last_scheduled_local_date: str | None = None
    last_run_id: int | None = None
    last_run_status: str | None = None
    last_run_stage: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str


class AutomationRunItem(BaseModel):
    id: int
    subscription_id: int
    trigger: ScheduleTrigger
    scheduled_local_date: str | None = None
    status: AutomationRunStatus
    stage: str
    fetched_count: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    source_article_id: str | None = None
    source_article_link: str | None = None
    source_article_title: str | None = None
    tracked_article_slug: str | None = None
    topic_slug: str | None = None
    project_slug: str | None = None
    publish_package_version: int | None = None
    draft_status: str | None = None
    draft_id: str | None = None
    error: str | None = None
    result: dict[str, object] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
    retryable: bool = False
    project_url: str | None = None
    preview_url: str | None = None
    source_url: str | None = None
    style_name: str | None = None
    provenance: str | None = None


class AutomationRunSubmission(BaseModel):
    run_id: int
    subscription_id: int
    trigger: ScheduleTrigger
    status: AutomationRunStatus
    created_at: str


class AutomationCycleResponse(BaseModel):
    evaluated_count: int
    claimed_count: int
    skipped_count: int
    failed_count: int
    run_ids: list[int] = Field(default_factory=list)


class AutomationRunnerStatus(BaseModel):
    running: bool
    poll_interval_seconds: int
    last_cycle_at: str | None = None


class AutomationRunListQuery(BaseModel):
    subscription_id: int | None = None
    limit: int = Field(default=50, ge=1, le=100)


def parse_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

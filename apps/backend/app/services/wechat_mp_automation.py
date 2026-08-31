from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app.core.settings import settings
from app.schemas.wechat_mp_automation import (
    AutomationCycleResponse,
    AutomationRunItem,
    AutomationRunSubmission,
    AutomationSubscriptionCreate,
    AutomationSubscriptionItem,
    AutomationSubscriptionUpdate,
    parse_utc_datetime,
)


logger = logging.getLogger(__name__)

AUTOMATION_PROVENANCE = "scheduled_automation"
DEFAULT_SCHEDULE_TIME = "21:00"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_FETCH_LIMIT = 1
DEFAULT_LEASE_SECONDS = 120
MAX_ERROR_LENGTH = 500
SCHEDULE_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

_RUN_STATUS_VALUES = {"queued", "running", "completed", "skipped", "failed", "claimed"}
_WORKFLOW_STATUS_VALUES = {"active", "completed", "skipped", "failed"}
_AUTOMATION_SCHEMA_LOCK = threading.Lock()


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now_iso(now: datetime | None = None) -> str:
    return _utc_now(now).replace(microsecond=0).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    return parse_utc_datetime(value)


def normalize_schedule_time(value: str) -> str:
    normalized = str(value or "").strip()
    if not SCHEDULE_TIME_PATTERN.fullmatch(normalized):
        raise ValueError("schedule_time must use strict HH:MM format")
    return normalized


def validate_timezone(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {normalized}") from exc
    return normalized


def _schedule_as_time(schedule_time: str) -> time:
    normalized = normalize_schedule_time(schedule_time)
    hour, minute = normalized.split(":")
    return time(hour=int(hour), minute=int(minute))


def _as_local_datetime(value: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(validate_timezone(timezone_name))
    return _utc_now(value).astimezone(zone)


def is_schedule_due(
    *,
    schedule_time: str = DEFAULT_SCHEDULE_TIME,
    timezone_name: str = DEFAULT_TIMEZONE,
    enabled: bool = True,
    last_scheduled_local_date: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Return whether the current local schedule has arrived and is unclaimed."""
    if not enabled:
        return False
    local_now = _as_local_datetime(_utc_now(now), timezone_name)
    scheduled_time = _schedule_as_time(schedule_time)
    local_date = local_now.date().isoformat()
    if str(last_scheduled_local_date or "").strip() == local_date:
        return False
    return local_now.time().replace(second=0, microsecond=0) >= scheduled_time


def calculate_next_run_at(
    *,
    schedule_time: str = DEFAULT_SCHEDULE_TIME,
    timezone_name: str = DEFAULT_TIMEZONE,
    enabled: bool = True,
    last_scheduled_local_date: str | None = None,
    now: datetime | None = None,
) -> str | None:
    if not enabled:
        return None
    local_now = _as_local_datetime(_utc_now(now), timezone_name)
    scheduled_time = _schedule_as_time(schedule_time)
    local_date = local_now.date()
    last_date = str(last_scheduled_local_date or "").strip()
    if last_date == local_date.isoformat():
        local_date += timedelta(days=1)
    elif local_now.time().replace(second=0, microsecond=0) < scheduled_time:
        pass
    else:
        # A due but not yet claimed cycle is shown as the current scheduled time.
        # The scheduler's atomic claim turns it into tomorrow's next run.
        pass
    candidate = datetime.combine(local_date, scheduled_time, tzinfo=local_now.tzinfo)
    return candidate.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def normalize_error(error: object, *, fallback: str = "自动化运行失败") -> str:
    if isinstance(error, HTTPException):
        error = error.detail
    message = str(error or "").strip()
    if not message:
        message = fallback
    return message[:MAX_ERROR_LENGTH]


def _get_connection() -> sqlite3.Connection:
    # Resolve the workbench module at call time so tests can redirect DB_PATH.
    from app.services import workbench

    db_path = Path(workbench.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def ensure_automation_schema(connection: sqlite3.Connection, *, reset: bool = False) -> None:
    """Create or migrate only the tables owned by scheduled automation."""
    with _AUTOMATION_SCHEMA_LOCK:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_fakeid TEXT NOT NULL UNIQUE,
                account_biz TEXT DEFAULT NULL,
                account_nickname TEXT NOT NULL,
                account_alias TEXT DEFAULT NULL,
                account_avatar_url TEXT DEFAULT NULL,
                article_source TEXT NOT NULL DEFAULT 'wechat_mp',
                enabled INTEGER NOT NULL DEFAULT 1,
                schedule_time TEXT NOT NULL DEFAULT '21:00',
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                fetch_limit INTEGER NOT NULL DEFAULT 1,
                automatic_draft INTEGER NOT NULL DEFAULT 1,
                last_scheduled_local_date TEXT DEFAULT NULL,
                last_run_id INTEGER DEFAULT NULL,
                last_success_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                workflow_id INTEGER DEFAULT NULL,
                trigger TEXT NOT NULL,
                scheduled_local_date TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT 'queued',
                fetched_count INTEGER NOT NULL DEFAULT 0,
                imported_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                source_article_id TEXT DEFAULT NULL,
                source_article_link TEXT DEFAULT NULL,
                source_article_title TEXT DEFAULT NULL,
                tracked_article_slug TEXT DEFAULT NULL,
                topic_slug TEXT DEFAULT NULL,
                project_slug TEXT DEFAULT NULL,
                publish_package_version INTEGER DEFAULT NULL,
                draft_status TEXT DEFAULT NULL,
                draft_id TEXT DEFAULT NULL,
                error TEXT DEFAULT NULL,
                result_json TEXT DEFAULT NULL,
                started_at TEXT DEFAULT NULL,
                finished_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES automation_subscriptions(id),
                UNIQUE(subscription_id, scheduled_local_date)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                source_article_key TEXT NOT NULL,
                source_article_id TEXT DEFAULT NULL,
                source_article_link TEXT DEFAULT NULL,
                source_article_title TEXT DEFAULT NULL,
                source_update_time INTEGER DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                last_stage TEXT NOT NULL DEFAULT 'discovered',
                tracked_article_slug TEXT DEFAULT NULL,
                topic_slug TEXT DEFAULT NULL,
                project_slug TEXT DEFAULT NULL,
                publish_package_version INTEGER DEFAULT NULL,
                draft_status TEXT DEFAULT NULL,
                draft_id TEXT DEFAULT NULL,
                error TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES automation_subscriptions(id),
                UNIQUE(subscription_id, source_article_key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_locks (
                lock_key TEXT PRIMARY KEY,
                owner_token TEXT NOT NULL,
                lease_until TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_automation_columns(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_runs_subscription_created ON automation_runs(subscription_id, id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_workflows_subscription_status ON automation_workflows(subscription_id, status)"
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_subscriptions_account_biz
            ON automation_subscriptions(account_biz)
            WHERE account_biz IS NOT NULL AND TRIM(account_biz) <> ''
            """
        )
        if reset:
            connection.execute("DELETE FROM automation_locks")
            connection.execute("DELETE FROM automation_runs")
            connection.execute("DELETE FROM automation_workflows")
            connection.execute("DELETE FROM automation_subscriptions")
        connection.commit()


def _ensure_automation_columns(connection: sqlite3.Connection) -> None:
    migrations = {
        "automation_subscriptions": {
            "account_biz": "TEXT DEFAULT NULL",
            "article_source": "TEXT NOT NULL DEFAULT 'wechat_mp'",
        },
        "automation_runs": {
            "workflow_id": "INTEGER DEFAULT NULL",
            "result_json": "TEXT DEFAULT NULL",
        },
        "automation_workflows": {
            "source_update_time": "INTEGER DEFAULT NULL",
        },
    }
    for table_name, columns in migrations.items():
        existing = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, definition in columns.items():
            if column_name not in existing:
                connection.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                )


def _bool_value(value: object) -> bool:
    return bool(int(value or 0))


def _json_object(value: object) -> dict[str, object] | None:
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


_NON_RETRYABLE_SKIP_REASONS = {
    "manual_import_duplicate",
    "tracked_article_duplicate",
    "workflow_already_skipped",
    "no_new_unseen_article",
}


def _first_result_item(result: Mapping[str, object]) -> dict[str, object]:
    items = result.get("items")
    if not isinstance(items, list):
        return {}
    for item in items:
        if isinstance(item, Mapping):
            return dict(item)
    return {}


def _result_value(
    primary: Mapping[str, object],
    result: Mapping[str, object],
    key: str,
    fallback: object = None,
) -> object:
    for source in (primary, result):
        value = source.get(key)
        if value not in (None, ""):
            return value
    return fallback


def _is_run_retryable(row: sqlite3.Row, result: Mapping[str, object] | None = None) -> bool:
    status = str(row["status"] or "")
    if status == "failed":
        return True
    if status != "skipped" or not row["error"]:
        return False
    parsed_result = result if result is not None else (_json_object(row["result_json"]) or {})
    reason = str(_first_result_item(parsed_result).get("reason") or parsed_result.get("reason") or "").strip()
    return reason not in _NON_RETRYABLE_SKIP_REASONS


def _row_value(row: sqlite3.Row, key: str, default: object = None) -> object:
    return row[key] if key in row.keys() else default


def _serialize_subscription(
    row: sqlite3.Row,
    *,
    last_run: sqlite3.Row | None = None,
    now: datetime | None = None,
) -> AutomationSubscriptionItem:
    enabled = _bool_value(_row_value(row, "enabled", 0))
    schedule_time = str(_row_value(row, "schedule_time", DEFAULT_SCHEDULE_TIME))
    timezone_name = str(_row_value(row, "timezone", DEFAULT_TIMEZONE))
    last_run = last_run or row
    return AutomationSubscriptionItem(
        id=int(row["id"]),
        account_fakeid=str(row["account_fakeid"]),
        account_biz=(str(_row_value(row, "account_biz")) if _row_value(row, "account_biz") else None),
        account_nickname=str(row["account_nickname"]),
        account_alias=str(row["account_alias"]) if row["account_alias"] is not None else None,
        account_avatar_url=str(row["account_avatar_url"]) if row["account_avatar_url"] is not None else None,
        article_source=str(_row_value(row, "article_source", "wechat_mp") or "wechat_mp"),
        enabled=enabled,
        schedule_time=schedule_time,
        timezone=timezone_name,
        fetch_limit=int(row["fetch_limit"]),
        automatic_draft=_bool_value(row["automatic_draft"]),
        next_run_at=calculate_next_run_at(
            schedule_time=schedule_time,
            timezone_name=timezone_name,
            enabled=enabled,
            last_scheduled_local_date=(
                str(row["last_scheduled_local_date"])
                if row["last_scheduled_local_date"] is not None
                else None
            ),
            now=now,
        ),
        last_scheduled_local_date=(
            str(row["last_scheduled_local_date"])
            if row["last_scheduled_local_date"] is not None
            else None
        ),
        last_run_id=(int(row["last_run_id"]) if row["last_run_id"] is not None else None),
        last_run_status=(
            str(_row_value(last_run, "last_run_status", _row_value(last_run, "status")))
            if _row_value(last_run, "status", None) is not None or _row_value(last_run, "last_run_status", None) is not None
            else None
        ),
        last_run_stage=(
            str(_row_value(last_run, "last_run_stage", _row_value(last_run, "stage")))
            if _row_value(last_run, "stage", None) is not None or _row_value(last_run, "last_run_stage", None) is not None
            else None
        ),
        last_success_at=(str(row["last_success_at"]) if row["last_success_at"] is not None else None),
        last_error=(
            str(_row_value(last_run, "last_error", _row_value(last_run, "error")))
            if _row_value(last_run, "error", None) is not None or _row_value(last_run, "last_error", None) is not None
            else None
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _serialize_run(row: sqlite3.Row) -> AutomationRunItem:
    status = str(row["status"])
    if status not in _RUN_STATUS_VALUES:
        status = "failed"
    trigger = str(row["trigger"])
    if trigger not in {"scheduled", "manual", "retry"}:
        trigger = "manual"
    project_slug = str(row["project_slug"]) if row["project_slug"] else None
    result = _json_object(row["result_json"])
    if result is None and row["result_json"]:
        result = {"message": normalize_error(row["result_json"])}
    result = result or {}
    primary = _first_result_item(result)
    source_article_id = _result_value(primary, result, "source_article_id", row["source_article_id"])
    source_article_link = _result_value(primary, result, "source_article_link", row["source_article_link"])
    source_article_title = _result_value(primary, result, "source_article_title", row["source_article_title"])
    tracked_article_slug = _result_value(primary, result, "tracked_article_slug", row["tracked_article_slug"])
    topic_slug = _result_value(primary, result, "topic_slug", row["topic_slug"])
    project_slug_value = _result_value(primary, result, "project_slug", row["project_slug"])
    package_version_value = _result_value(
        primary,
        result,
        "publish_package_version",
        row["publish_package_version"],
    )
    draft_status = _result_value(primary, result, "draft_status", row["draft_status"])
    draft_id = _result_value(primary, result, "draft_id", row["draft_id"])
    project_slug = str(project_slug_value) if project_slug_value else None
    package_version = _safe_int(package_version_value)
    preview_url = _result_value(primary, result, "preview_url")
    style_name = _result_value(primary, result, "style_name")
    provenance = _result_value(primary, result, "provenance")
    return AutomationRunItem(
        id=int(row["id"]),
        subscription_id=int(row["subscription_id"]),
        trigger=trigger,
        scheduled_local_date=(str(row["scheduled_local_date"]) if row["scheduled_local_date"] else None),
        status=status,
        stage=str(row["stage"] or "queued"),
        fetched_count=int(row["fetched_count"] or 0),
        imported_count=int(row["imported_count"] or 0),
        skipped_count=int(row["skipped_count"] or 0),
        source_article_id=(str(source_article_id) if source_article_id else None),
        source_article_link=(str(source_article_link) if source_article_link else None),
        source_article_title=(str(source_article_title) if source_article_title else None),
        tracked_article_slug=(str(tracked_article_slug) if tracked_article_slug else None),
        topic_slug=(str(topic_slug) if topic_slug else None),
        project_slug=project_slug,
        publish_package_version=package_version,
        draft_status=(str(draft_status) if draft_status else None),
        draft_id=(str(draft_id) if draft_id else None),
        error=(str(row["error"]) if row["error"] else None),
        result=result or None,
        started_at=(str(row["started_at"]) if row["started_at"] else None),
        finished_at=(str(row["finished_at"]) if row["finished_at"] else None),
        created_at=str(row["created_at"]),
        retryable=_is_run_retryable(row, result),
        project_url=f"/projects/{project_slug}/workbench/publish" if project_slug else None,
        preview_url=(str(preview_url) if preview_url else None),
        source_url=(str(source_article_link) if source_article_link else None),
        style_name=(str(style_name) if style_name else None),
        provenance=(str(provenance) if provenance else None),
    )


def _get_subscription_row(connection: sqlite3.Connection, subscription_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM automation_subscriptions WHERE id = ?",
        (subscription_id,),
    ).fetchone()


def _require_subscription_row(connection: sqlite3.Connection, subscription_id: int) -> sqlite3.Row:
    row = _get_subscription_row(connection, subscription_id)
    if not row:
        raise HTTPException(status_code=404, detail="Automation subscription not found")
    return row


def _find_subscription_conflict(
    connection: sqlite3.Connection,
    *,
    account_fakeid: str,
    account_biz: str | None,
    exclude_id: int | None = None,
) -> sqlite3.Row | None:
    identities = tuple(dict.fromkeys(
        value.strip()
        for value in (account_fakeid, account_biz or "")
        if value and value.strip()
    ))
    if not identities:
        return None
    clauses: list[str] = []
    parameters: list[object] = []
    for identity in identities:
        clauses.append("(account_fakeid = ? OR account_biz = ?)")
        parameters.extend((identity, identity))
    identity_clause = " OR ".join(clauses)
    exclusion_clause = ""
    if exclude_id is not None:
        exclusion_clause = " AND id <> ?"
        parameters.append(exclude_id)
    return connection.execute(
        f"SELECT * FROM automation_subscriptions WHERE ({identity_clause}){exclusion_clause} ORDER BY id LIMIT 1",
        parameters,
    ).fetchone()


def _get_latest_run_row(connection: sqlite3.Connection, subscription_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM automation_runs
        WHERE subscription_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (subscription_id,),
    ).fetchone()


def list_subscriptions(*, now: datetime | None = None) -> list[AutomationSubscriptionItem]:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        rows = connection.execute(
            "SELECT * FROM automation_subscriptions ORDER BY enabled DESC, id DESC"
        ).fetchall()
        return [
            _serialize_subscription(row, last_run=_get_latest_run_row(connection, int(row["id"])), now=now)
            for row in rows
        ]


def get_subscription(subscription_id: int, *, now: datetime | None = None) -> AutomationSubscriptionItem:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        row = _require_subscription_row(connection, subscription_id)
        return _serialize_subscription(row, last_run=_get_latest_run_row(connection, subscription_id), now=now)


def create_subscription(payload: AutomationSubscriptionCreate) -> AutomationSubscriptionItem:
    schedule_time = normalize_schedule_time(payload.schedule_time)
    timezone_name = validate_timezone(payload.timezone)
    account_fakeid = payload.account_fakeid.strip()
    now = _utc_now_iso()
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        conflict = _find_subscription_conflict(
            connection,
            account_fakeid=account_fakeid,
            account_biz=payload.account_biz,
        )
        if conflict:
            source_label = "wx_channel 捕获" if conflict["article_source"] == "wx_channel" else "扫码后台"
            raise HTTPException(
                status_code=409,
                detail=f"该公众号已存在订阅（ID {conflict['id']}，来源{source_label}），请直接编辑现有订阅。",
            )
        try:
            connection.execute(
                """
                INSERT INTO automation_subscriptions (
                    account_fakeid, account_biz, account_nickname, account_alias, account_avatar_url,
                    article_source,
                    enabled, schedule_time, timezone, fetch_limit, automatic_draft,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_fakeid,
                    payload.account_biz,
                    payload.account_nickname.strip(),
                    payload.account_alias,
                    payload.account_avatar_url,
                    payload.article_source,
                    int(payload.enabled),
                    schedule_time,
                    timezone_name,
                    int(payload.fetch_limit),
                    int(payload.automatic_draft),
                    now,
                    now,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="该公众号已存在订阅，请直接编辑现有订阅。") from exc
        row = connection.execute(
            "SELECT * FROM automation_subscriptions WHERE id = last_insert_rowid()",
        ).fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="Automation subscription was not persisted")
        return _serialize_subscription(row, now=_utc_now())


def update_subscription(
    subscription_id: int,
    payload: AutomationSubscriptionUpdate,
) -> AutomationSubscriptionItem:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return get_subscription(subscription_id)
    if "schedule_time" in updates and updates["schedule_time"] is not None:
        updates["schedule_time"] = normalize_schedule_time(str(updates["schedule_time"]))
    if "timezone" in updates and updates["timezone"] is not None:
        updates["timezone"] = validate_timezone(str(updates["timezone"]))
    allowed = {
        "account_fakeid",
        "account_biz",
        "account_nickname",
        "account_alias",
        "account_avatar_url",
        "enabled",
        "article_source",
        "schedule_time",
        "timezone",
        "fetch_limit",
        "automatic_draft",
    }
    updates = {key: value for key, value in updates.items() if key in allowed}
    if not updates:
        return get_subscription(subscription_id)
    assignments: list[str] = []
    values: list[object] = []
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        if key in {"enabled", "automatic_draft"}:
            values.append(int(bool(value)))
        else:
            values.append(value)
    assignments.append("updated_at = ?")
    values.append(_utc_now_iso())
    # Re-evaluating a changed schedule is safe because the scheduled run has a
    # unique subscription/date key; it cannot create a duplicate run.
    if "schedule_time" in updates or "timezone" in updates or "enabled" in updates:
        assignments.append("last_scheduled_local_date = NULL")
    values.append(subscription_id)
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        current = _require_subscription_row(connection, subscription_id)
        next_fakeid = str(updates.get("account_fakeid", current["account_fakeid"]) or "").strip()
        if not next_fakeid:
            raise HTTPException(status_code=422, detail="订阅必须保留公众号标识。")
        next_biz = updates.get("account_biz", _row_value(current, "account_biz"))
        next_source = updates.get("article_source", _row_value(current, "article_source", "wechat_mp"))
        if next_source == "wx_channel" and not str(next_biz or "").strip():
            raise HTTPException(status_code=422, detail="切换为 wx_channel 来源时必须提供 biz。")
        conflict = _find_subscription_conflict(
            connection,
            account_fakeid=next_fakeid,
            account_biz=str(next_biz).strip() if next_biz else None,
            exclude_id=subscription_id,
        )
        if conflict:
            source_label = "wx_channel 捕获" if conflict["article_source"] == "wx_channel" else "扫码后台"
            raise HTTPException(
                status_code=409,
                detail=f"公众号身份与现有订阅（ID {conflict['id']}，来源{source_label}）重复，请编辑原订阅。",
            )
        try:
            connection.execute(
                f"UPDATE automation_subscriptions SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="该公众号已存在其他订阅，请编辑现有订阅。") from exc
    return get_subscription(subscription_id)


def disable_subscription(subscription_id: int) -> AutomationSubscriptionItem:
    return update_subscription(subscription_id, AutomationSubscriptionUpdate(enabled=False))


def acquire_lease(
    lock_key: str,
    owner_token: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> bool:
    normalized_key = str(lock_key or "").strip()
    normalized_owner = str(owner_token or "").strip()
    if not normalized_key or not normalized_owner:
        raise ValueError("lock_key and owner_token are required")
    lease_seconds = max(1, int(lease_seconds))
    acquired_at = _utc_now(now)
    lease_until = acquired_at + timedelta(seconds=lease_seconds)
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_token, lease_until FROM automation_locks WHERE lock_key = ?",
                (normalized_key,),
            ).fetchone()
            current_expiry = _parse_datetime(str(row["lease_until"])) if row else None
            if row and current_expiry and current_expiry > acquired_at and str(row["owner_token"]) != normalized_owner:
                connection.rollback()
                return False
            if row:
                connection.execute(
                    """
                    UPDATE automation_locks
                    SET owner_token = ?, lease_until = ?, updated_at = ?
                    WHERE lock_key = ?
                    """,
                    (normalized_owner, lease_until.replace(microsecond=0).isoformat(), _utc_now_iso(acquired_at), normalized_key),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO automation_locks (lock_key, owner_token, lease_until, acquired_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_key,
                        normalized_owner,
                        lease_until.replace(microsecond=0).isoformat(),
                        _utc_now_iso(acquired_at),
                        _utc_now_iso(acquired_at),
                    ),
                )
            connection.commit()
            return True
        except sqlite3.OperationalError:
            connection.rollback()
            return False


def release_lease(lock_key: str, owner_token: str) -> bool:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        cursor = connection.execute(
            "DELETE FROM automation_locks WHERE lock_key = ? AND owner_token = ?",
            (str(lock_key), str(owner_token)),
        )
        connection.commit()
        return cursor.rowcount == 1


def claim_scheduled_run(
    subscription_id: int,
    scheduled_local_date: str,
    *,
    now: datetime | None = None,
) -> int | None:
    local_date = str(scheduled_local_date or "").strip()
    try:
        date.fromisoformat(local_date)
    except ValueError as exc:
        raise ValueError("scheduled_local_date must be an ISO date") from exc
    created_at = _utc_now_iso(now)
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            subscription = _require_subscription_row(connection, subscription_id)
            if not _bool_value(subscription["enabled"]):
                connection.rollback()
                return None
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO automation_runs (
                    subscription_id, trigger, scheduled_local_date, status, stage, created_at
                ) VALUES (?, 'scheduled', ?, 'claimed', 'claimed', ?)
                """,
                (subscription_id, local_date, created_at),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.execute(
                """
                UPDATE automation_subscriptions
                SET last_scheduled_local_date = ?, last_run_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (local_date, run_id, created_at, subscription_id),
            )
            connection.commit()
            return run_id
        except Exception:
            connection.rollback()
            raise


def create_manual_run(subscription_id: int, *, trigger: str = "manual", workflow_id: int | None = None) -> AutomationRunSubmission:
    if trigger not in {"manual", "retry"}:
        raise ValueError("manual run trigger must be manual or retry")
    created_at = _utc_now_iso()
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        subscription = _require_subscription_row(connection, subscription_id)
        cursor = connection.execute(
            """
            INSERT INTO automation_runs (
                subscription_id, workflow_id, trigger, status, stage, created_at
            ) VALUES (?, ?, ?, 'queued', 'queued', ?)
            """,
            (subscription_id, workflow_id, trigger, created_at),
        )
        run_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE automation_subscriptions SET last_run_id = ?, updated_at = ? WHERE id = ?",
            (run_id, created_at, subscription_id),
        )
        connection.commit()
    return AutomationRunSubmission(
        run_id=run_id,
        subscription_id=subscription_id,
        trigger=trigger,
        status="queued",
        created_at=created_at,
    )


def _get_run_row(connection: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM automation_runs WHERE id = ?", (run_id,)).fetchone()


def get_run(run_id: int) -> AutomationRunItem:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        row = _get_run_row(connection, run_id)
        if not row:
            raise HTTPException(status_code=404, detail="Automation run not found")
        return _serialize_run(row)


def list_runs(*, subscription_id: int | None = None, limit: int = 50) -> list[AutomationRunItem]:
    bounded_limit = max(1, min(int(limit), 100))
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        if subscription_id is None:
            rows = connection.execute(
                "SELECT * FROM automation_runs ORDER BY id DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        else:
            _require_subscription_row(connection, subscription_id)
            rows = connection.execute(
                "SELECT * FROM automation_runs WHERE subscription_id = ? ORDER BY id DESC LIMIT ?",
                (subscription_id, bounded_limit),
            ).fetchall()
        return [_serialize_run(row) for row in rows]


def _update_run(run_id: int, **fields: object) -> None:
    if not fields:
        return
    allowed = {
        "workflow_id",
        "status",
        "stage",
        "fetched_count",
        "imported_count",
        "skipped_count",
        "source_article_id",
        "source_article_link",
        "source_article_title",
        "tracked_article_slug",
        "topic_slug",
        "project_slug",
        "publish_package_version",
        "draft_status",
        "draft_id",
        "error",
        "result_json",
        "started_at",
        "finished_at",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [run_id]
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        connection.execute(f"UPDATE automation_runs SET {assignments} WHERE id = ?", values)
        connection.commit()


def _set_run_stage(run_id: int, stage: str, **fields: object) -> None:
    _update_run(run_id, stage=stage, status="running", **fields)


def _update_workflow(workflow_id: int, **fields: object) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "last_stage",
        "tracked_article_slug",
        "topic_slug",
        "project_slug",
        "publish_package_version",
        "draft_status",
        "draft_id",
        "error",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    updates["updated_at"] = _utc_now_iso()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        connection.execute(
            f"UPDATE automation_workflows SET {assignments} WHERE id = ?",
            list(updates.values()) + [workflow_id],
        )
        connection.commit()


def _source_article_key(article: Mapping[str, object]) -> str:
    article_id = str(article.get("article_id") or "").strip()
    link = str(article.get("link") or "").strip()
    raw = article_id or link
    if not raw:
        raw = f"{article.get('title', '')}|{article.get('update_time', '')}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"wechat-mp:{digest}"


def _get_or_create_workflow(
    subscription_id: int,
    article: Mapping[str, object],
) -> sqlite3.Row:
    key = _source_article_key(article)
    now = _utc_now_iso()
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO automation_workflows (
                subscription_id, source_article_key, source_article_id, source_article_link,
                source_article_title, source_update_time, status, last_stage, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', 'discovered', ?, ?)
            """,
            (
                subscription_id,
                key,
                str(article.get("article_id") or "").strip() or None,
                str(article.get("link") or "").strip() or None,
                str(article.get("title") or "").strip() or None,
                int(article.get("update_time") or 0) or None,
                now,
                now,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM automation_workflows WHERE subscription_id = ? AND source_article_key = ?",
            (subscription_id, key),
        ).fetchone()
        if not row:
            raise RuntimeError("Automation workflow was not persisted")
        return row


def list_due_subscription_rows(*, now: datetime | None = None) -> list[sqlite3.Row]:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        rows = connection.execute(
            "SELECT * FROM automation_subscriptions WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    return [
        row
        for row in rows
        if is_schedule_due(
            schedule_time=str(row["schedule_time"]),
            timezone_name=str(row["timezone"]),
            enabled=_bool_value(row["enabled"]),
            last_scheduled_local_date=(str(row["last_scheduled_local_date"]) if row["last_scheduled_local_date"] else None),
            now=now,
        )
    ]


def _local_date_for_subscription(row: sqlite3.Row, now: datetime | None = None) -> str:
    local_now = _as_local_datetime(_utc_now(now), str(row["timezone"]))
    return local_now.date().isoformat()


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _article_index(article: Mapping[str, object]) -> int | None:
    article_id = str(article.get("article_id") or "").strip()
    match = re.search(r"(?:^|:)idx:(\d+)$", article_id)
    if match:
        return int(match.group(1))

    link = str(article.get("link") or "").strip()
    if not link:
        return None
    try:
        value = parse_qsl(urlsplit(link).query, keep_blank_values=True)
    except ValueError:
        return None
    for key, raw_value in value:
        if key != "idx":
            continue
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return None
    return None


def _article_sort_key(article: Mapping[str, object]) -> tuple[int, int, int]:
    article_index = _article_index(article)
    return (
        -(_safe_int(article.get("update_time")) or 0),
        0 if article_index is not None else 1,
        article_index or 0,
    )


def _find_existing_tracked_article(url: str):
    from app.services import workbench

    normalized = str(url or "").strip()
    if not normalized:
        return None
    for article in workbench.list_tracked_articles():
        if str(article.url).strip() == normalized:
            return article
    return None


def _make_tracked_article_payload(article: Mapping[str, object], client) -> Any:
    from app.schemas.tracked_articles import TrackedArticleCreate

    account_nickname = str(article.get("account_nickname") or "").strip() or "公众号"
    article_id = str(article.get("article_id") or "").strip()
    slug_base = hashlib.sha256(
        f"{account_nickname}|{article_id}|{article.get('link', '')}".encode("utf-8")
    ).hexdigest()[:18]
    article_link = str(article.get("link") or "")
    article_digest = str(article.get("digest") or "")
    article_biz = str(article.get("account_biz") or "").strip()
    if article_biz:
        body_markdown, body_source = client.fetch_article_body(article_link, article_digest, biz=article_biz)
    else:
        body_markdown, body_source = client.fetch_article_body(article_link, article_digest)
    return TrackedArticleCreate(
        slug=f"wechat-mp-automation-{slug_base}",
        source_kind="wechat_mp_automation",
        source_name=account_nickname,
        title=str(article.get("title") or "未命名文章").strip(),
        url=str(article.get("link") or "").strip(),
        author=str(article.get("author") or account_nickname).strip(),
        summary=str(article.get("digest") or "").strip(),
        body_markdown=str(body_markdown or "").strip(),
        body_source=str(body_source or "missing"),
        structure_notes="Scheduled WeChat MP import; structure notes pending generation.",
        tags=["wechat-mp", "scheduled-automation", account_nickname],
    )


def _session_is_logged_in(client) -> Mapping[str, object] | None:
    status_getter = getattr(client, "get_cached_session_status", None)
    if not callable(status_getter):
        status_getter = getattr(client, "get_session_status", None)
    if not callable(status_getter):
        return None
    status = status_getter()
    if not isinstance(status, Mapping) or not bool(status.get("logged_in")):
        message = str((status or {}).get("status_message") if isinstance(status, Mapping) else "").strip()
        if not message:
            message = "公众号登录已过期，请重新扫码登录"
        raise RuntimeError(message)
    return status


def _project_result_value(value: object, key: str, default: object = None) -> object:
    if value is None:
        return default
    if hasattr(value, key):
        return getattr(value, key)
    if isinstance(value, Mapping):
        return value.get(key, default)
    return default


def _automation_preview_url(package: object) -> str | None:
    value = _project_result_value(package, "html_url") or _project_result_value(package, "markdown_url")
    return str(value) if value else None


def _get_project_for_topic(topic_slug: str):
    from app.services import workbench

    for project in workbench.list_projects():
        if project.topic_slug == topic_slug:
            return project
    return None


def _article_from_workflow(
    workflow: sqlite3.Row,
    account_nickname: str,
    account_biz: str | None = None,
) -> dict[str, object]:
    return {
        "article_id": str(workflow["source_article_id"] or ""),
        "link": str(workflow["source_article_link"] or ""),
        "title": str(workflow["source_article_title"] or "未命名文章"),
        "update_time": int(workflow["source_update_time"] or 0),
        "account_nickname": account_nickname,
        "account_biz": str(account_biz or "").strip(),
        "author": account_nickname,
        "digest": "",
    }


def _run_workflow_stages(
    run_id: int,
    workflow_id: int,
    subscription_id: int,
    article: Mapping[str, object],
    *,
    source_client: object | None = None,
    automatic_draft: bool = True,
) -> dict[str, object]:
    """Resume one source article through the existing content owners."""
    from app.schemas.projects import ProjectCreate
    from app.services import workbench

    workflow = _load_workflow(workflow_id)
    result: dict[str, object] = {
        "source_article_id": str(article.get("article_id") or "") or None,
        "source_article_link": str(article.get("link") or "") or None,
        "source_article_title": str(article.get("title") or "") or None,
        "provenance": AUTOMATION_PROVENANCE,
        "automatic_draft": bool(automatic_draft),
    }

    if str(workflow["status"] or "") == "skipped":
        result.update(
            {
                "status": "skipped",
                "reason": "workflow_already_skipped",
                "tracked_article_slug": str(workflow["tracked_article_slug"] or "") or None,
            }
        )
        _set_run_stage(
            run_id,
            "skipped",
            tracked_article_slug=result["tracked_article_slug"],
        )
        return result

    tracked_slug = str(workflow["tracked_article_slug"] or "").strip()
    topic_slug = str(workflow["topic_slug"] or "").strip()
    project_slug = str(workflow["project_slug"] or "").strip()
    package_version = _safe_int(workflow["publish_package_version"])

    if not tracked_slug:
        _set_run_stage(run_id, "importing", source_article_id=result["source_article_id"], source_article_link=result["source_article_link"], source_article_title=result["source_article_title"])
        existing = _find_existing_tracked_article(str(article.get("link") or ""))
        if existing:
            _update_workflow(workflow_id, status="skipped", last_stage="duplicate_tracked_article", tracked_article_slug=existing.slug, error="已存在相同链接的手动导入文章")
            result.update({"status": "skipped", "reason": "manual_import_duplicate", "tracked_article_slug": existing.slug})
            _set_run_stage(run_id, "skipped", tracked_article_slug=existing.slug)
            return result
        payload = _make_tracked_article_payload(article, source_client or get_wechat_mp_client())
        imported = workbench.import_tracked_articles([payload], source_kind="wechat_mp_automation")
        created_items = imported.get("created") or []
        if created_items:
            tracked_slug = str(_project_result_value(created_items[0], "slug") or payload.slug)
        else:
            existing = _find_existing_tracked_article(payload.url)
            if existing:
                _update_workflow(workflow_id, status="skipped", last_stage="duplicate_tracked_article", tracked_article_slug=existing.slug, error="已存在相同链接的文章")
                result.update({"status": "skipped", "reason": "tracked_article_duplicate", "tracked_article_slug": existing.slug})
                _set_run_stage(run_id, "skipped", tracked_article_slug=existing.slug)
                return result
            raise RuntimeError("公众号文章导入未产生可用文章")
        _update_workflow(workflow_id, last_stage="imported", tracked_article_slug=tracked_slug, error=None)
        _set_run_stage(run_id, "imported", tracked_article_slug=tracked_slug)

    if not topic_slug:
        _set_run_stage(run_id, "generating_topic", tracked_article_slug=tracked_slug)
        topic = workbench.generate_topic_from_tracked_article(tracked_slug)
        topic_slug = str(_project_result_value(topic, "slug"))
        _update_workflow(workflow_id, last_stage="topic_generated", topic_slug=topic_slug, error=None)
        _set_run_stage(run_id, "topic_generated", tracked_article_slug=tracked_slug, topic_slug=topic_slug)

    project = _get_project_for_topic(topic_slug)
    if project is not None and not project_slug:
        project_slug = str(project.slug)
    if not project_slug:
        _set_run_stage(run_id, "creating_project", tracked_article_slug=tracked_slug, topic_slug=topic_slug)
        project_slug = f"{topic_slug}-automation-project"
        project = workbench.create_project_from_topic(
            topic_slug,
            ProjectCreate(
                slug=project_slug,
                title=f"{str(article.get('title') or topic_slug).strip()}（自动改写）",
                owner="scheduled-automation",
            ),
        )
        _update_workflow(workflow_id, last_stage="project_created", project_slug=project_slug, error=None)
        _set_run_stage(run_id, "project_created", tracked_article_slug=tracked_slug, topic_slug=topic_slug, project_slug=project_slug)

    if project is None:
        project = workbench.get_project_detail(project_slug).project

    # Tracked-article projects retain the existing strategy gate. Automation
    # performs the same explicit generation/adoption transition before outline.
    detail = workbench.get_project_detail(project_slug)
    if str(getattr(detail.project, "next_required_step", "") or "") == "generate_strategy_package":
        _set_run_stage(run_id, "generating_strategy", project_slug=project_slug)
        strategy_result = workbench.generate_strategy_package(project_slug)
        strategy_card = _project_result_value(strategy_result, "strategy_card")
        strategy_version = _project_result_value(strategy_card, "version")
        if strategy_version is None:
            raise RuntimeError("策略包生成成功但缺少策略卡版本")
        workbench.adopt_strategy_card(project_slug, int(strategy_version))
        _update_workflow(workflow_id, last_stage="strategy_adopted", project_slug=project_slug, error=None)
        _set_run_stage(run_id, "strategy_adopted", project_slug=project_slug)
        detail = workbench.get_project_detail(project_slug)

    if not detail.outline:
        _set_run_stage(run_id, "generating_outline", project_slug=project_slug)
        workbench.generate_outline(project_slug)
        _update_workflow(workflow_id, last_stage="outline_generated", project_slug=project_slug, error=None)
        _set_run_stage(run_id, "outline_generated", project_slug=project_slug)
        detail = workbench.get_project_detail(project_slug)

    if not detail.draft:
        _set_run_stage(run_id, "generating_draft", project_slug=project_slug)
        workbench.generate_draft(project_slug)
        _update_workflow(workflow_id, last_stage="draft_generated", project_slug=project_slug, error=None)
        _set_run_stage(run_id, "draft_generated", project_slug=project_slug)
        detail = workbench.get_project_detail(project_slug)

    if not detail.assets or str(detail.assets.cover_image_status or "") != "ready":
        _set_run_stage(run_id, "generating_assets", project_slug=project_slug)
        workbench.generate_assets(project_slug)
        _update_workflow(workflow_id, last_stage="assets_generated", project_slug=project_slug, error=None)
        _set_run_stage(run_id, "assets_generated", project_slug=project_slug)
        detail = workbench.get_project_detail(project_slug)

    if not detail.publish_package:
        _set_run_stage(run_id, "building_publish_package", project_slug=project_slug)
        package = workbench.build_publish_package(project_slug)
        package_version = _safe_int(_project_result_value(package, "version"))
        _update_workflow(workflow_id, last_stage="package_built", project_slug=project_slug, publish_package_version=package_version, error=None)
        _set_run_stage(run_id, "package_built", project_slug=project_slug, publish_package_version=package_version)
        detail = workbench.get_project_detail(project_slug)
    package = detail.publish_package
    if package is None:
        raise RuntimeError("发布包生成后仍无法读取")
    package_version = _safe_int(_project_result_value(package, "version")) or package_version

    if str(_project_result_value(package, "status") or "") != "approved":
        _set_run_stage(run_id, "approving_package", project_slug=project_slug, publish_package_version=package_version)
        package = workbench.approve_publish_package(
            project_slug,
            reviewer="scheduled-automation",
            comment="自动化流程审核通过，仅写入公众号草稿箱，不执行群发。",
            provenance=AUTOMATION_PROVENANCE,
        )
        _update_workflow(workflow_id, last_stage="package_approved", project_slug=project_slug, publish_package_version=package_version, error=None)
        _set_run_stage(run_id, "package_approved", project_slug=project_slug, publish_package_version=package_version)
    elif hasattr(workbench, "mark_publish_package_provenance"):
        workbench.mark_publish_package_provenance(project_slug, provenance=AUTOMATION_PROVENANCE)

    draft_status = str(_project_result_value(package, "wechat_mp_draft_status") or "not_published")
    draft_id = _project_result_value(package, "wechat_mp_draft_id")
    completion_stage = "package_approved"
    if automatic_draft and draft_status != "published":
        _set_run_stage(run_id, "writing_draft", project_slug=project_slug, publish_package_version=package_version, draft_status=draft_status)
        package = workbench.publish_wechat_mp_draft(project_slug, provenance=AUTOMATION_PROVENANCE)
        draft_status = str(_project_result_value(package, "wechat_mp_draft_status") or "published")
        draft_id = _project_result_value(package, "wechat_mp_draft_id")
        _update_workflow(workflow_id, last_stage="draft_written", project_slug=project_slug, publish_package_version=package_version, draft_status=draft_status, draft_id=str(draft_id) if draft_id else None, error=None)
        _set_run_stage(run_id, "draft_written", project_slug=project_slug, publish_package_version=package_version, draft_status=draft_status, draft_id=str(draft_id) if draft_id else None)
        completion_stage = "draft_written"

    result.update(
        {
            "status": "completed",
            "tracked_article_slug": tracked_slug,
            "topic_slug": topic_slug,
            "project_slug": project_slug,
            "publish_package_version": package_version,
            "draft_status": draft_status,
            "draft_id": str(draft_id) if draft_id else None,
            "preview_url": _automation_preview_url(package),
            "style_name": _project_result_value(package, "wechat_html_style_name"),
            "completion_stage": completion_stage,
            "provenance": AUTOMATION_PROVENANCE,
        }
    )
    _update_workflow(workflow_id, status="completed", last_stage=completion_stage, project_slug=project_slug, publish_package_version=package_version, draft_status=draft_status, draft_id=str(draft_id) if draft_id else None, error=None)
    return result


def _load_workflow(workflow_id: int) -> sqlite3.Row:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        row = connection.execute("SELECT * FROM automation_workflows WHERE id = ?", (workflow_id,)).fetchone()
    if not row:
        raise RuntimeError("Automation workflow not found")
    return row


def get_wechat_mp_client():
    from app.services.wechat_mp_client import get_wechat_mp_client as factory

    return factory()


def get_wx_channel_client():
    from app.services.wx_channel_client import get_wx_channel_client as factory

    return factory()


def _get_subscription_article_client(subscription: AutomationSubscriptionItem):
    if subscription.article_source == "wx_channel":
        if not subscription.account_biz:
            raise RuntimeError("wx_channel 订阅缺少 biz，无法读取文章")
        return get_wx_channel_client()
    return get_wechat_mp_client()


def _list_subscription_articles(client, subscription: AutomationSubscriptionItem) -> list[dict[str, object]]:
    if subscription.article_source == "wx_channel":
        return client.list_articles(
            biz=str(subscription.account_biz or ""),
            offset=0,
            limit=max(subscription.fetch_limit, 10),
        )
    return client.list_articles(
        fakeid=subscription.account_fakeid,
        begin=0,
        size=max(subscription.fetch_limit, 10),
        keyword=None,
    )


def _mark_run_finished(run_id: int, *, status: str, stage: str, result: Mapping[str, object] | None = None, error: str | None = None) -> None:
    finished_at = _utc_now_iso()
    _update_run(
        run_id,
        status=status,
        stage=stage,
        finished_at=finished_at,
        result_json=json.dumps(dict(result or {}), ensure_ascii=False),
        error=normalize_error(error) if error else None,
    )
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        row = _get_run_row(connection, run_id)
        if row:
            connection.execute(
                "UPDATE automation_subscriptions SET updated_at = ? WHERE id = ?",
                (finished_at, int(row["subscription_id"])),
            )
            if status == "completed":
                connection.execute(
                    "UPDATE automation_subscriptions SET last_success_at = ?, updated_at = ? WHERE id = ?",
                    (finished_at, finished_at, int(row["subscription_id"])),
                )
        connection.commit()


def execute_run(run_id: int) -> AutomationRunItem:
    """Execute a queued/claimed run synchronously; safe for API, runner, and tests."""
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        run = _get_run_row(connection, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Automation run not found")
        if str(run["status"]) in {"completed", "skipped"}:
            return _serialize_run(run)
        subscription = _require_subscription_row(connection, int(run["subscription_id"]))
        workflow_id = int(run["workflow_id"]) if run["workflow_id"] is not None else None
    started_at = _utc_now_iso()
    _update_run(run_id, status="running", stage="session", started_at=started_at, error=None)
    client: object | None = None
    try:
        subscription = get_subscription(int(run["subscription_id"]))
        client = _get_subscription_article_client(subscription)
        session_status = (
            _session_is_logged_in(client)
            if subscription.article_source == "wechat_mp"
            else None
        )
        selected: list[Mapping[str, object]] = []
        if workflow_id is not None:
            workflow = _load_workflow(workflow_id)
            if int(workflow["subscription_id"]) != subscription.id:
                raise RuntimeError("自动化工作流与订阅账号不匹配")
            article = _article_from_workflow(
                workflow,
                subscription.account_nickname,
                subscription.account_biz,
            )
            if not str(workflow["tracked_article_slug"] or "").strip() and not str(article["link"] or "").strip():
                raise RuntimeError("自动化工作流缺少可恢复的文章来源链接")
            _update_run(
                run_id,
                workflow_id=workflow_id,
                stage="fetched",
                status="running",
                fetched_count=1,
                source_article_id=str(article["article_id"] or "") or None,
                source_article_link=str(article["link"] or "") or None,
                source_article_title=str(article["title"] or "") or None,
            )
            if str(workflow["status"] or "") == "skipped":
                skipped_result = {
                    "status": "skipped",
                    "reason": "workflow_already_skipped",
                    "source_article_id": article["article_id"],
                    "source_article_link": article["link"],
                    "source_article_title": article["title"],
                    "tracked_article_slug": str(workflow["tracked_article_slug"] or "") or None,
                    "automatic_draft": bool(subscription.automatic_draft),
                    "provenance": AUTOMATION_PROVENANCE,
                }
                _mark_run_finished(
                    run_id,
                    status="skipped",
                    stage="skipped",
                    result={"items": [skipped_result], "provenance": AUTOMATION_PROVENANCE},
                )
                return get_run(run_id)
            selected = [article]
        else:
            _update_run(run_id, stage="fetching_articles", status="running")
            session_nickname = str((session_status or {}).get("nickname") or "").strip()
            if session_nickname and session_nickname != subscription.account_nickname.strip():
                raise RuntimeError(
                    f"当前扫码会话登录的是“{session_nickname}”，订阅目标是“{subscription.account_nickname}”。"
                    "公众号后台文章接口只能读取当前登录账号，无法读取其他账号的文章列表；"
                    "请手动导入目标文章后继续生成，或将订阅改为当前登录账号。"
                )
            raw_articles = _list_subscription_articles(client, subscription)
            articles = sorted(
                [item for item in raw_articles if isinstance(item, Mapping)],
                key=_article_sort_key,
            )
            _update_run(run_id, stage="fetched", status="running", fetched_count=len(articles))
            for article in articles:
                workflow = _get_or_create_workflow(subscription.id, article)
                if str(workflow["status"]) == "completed":
                    continue
                if str(workflow["status"]) == "skipped":
                    continue
                selected.append(article)
                if len(selected) >= subscription.fetch_limit:
                    break
        if not selected:
            _mark_run_finished(run_id, status="skipped", stage="no_new_article", result={"provenance": AUTOMATION_PROVENANCE, "reason": "no_new_unseen_article"})
            return get_run(run_id)

        results: list[dict[str, object]] = []
        imported_count = 0
        skipped_count = 0
        for article in selected:
            workflow = _get_or_create_workflow(subscription.id, article)
            workflow_id = int(workflow["id"])
            _update_run(run_id, workflow_id=workflow_id, source_article_id=str(article.get("article_id") or "") or None, source_article_link=str(article.get("link") or "") or None, source_article_title=str(article.get("title") or "") or None)
            stage_kwargs: dict[str, object] = {"automatic_draft": subscription.automatic_draft}
            if subscription.article_source == "wx_channel":
                stage_kwargs["source_client"] = client
            result = _run_workflow_stages(
                run_id,
                workflow_id,
                subscription.id,
                article,
                **stage_kwargs,
            )
            results.append(result)
            if result.get("status") == "skipped":
                skipped_count += 1
            else:
                imported_count += 1
            _update_run(run_id, imported_count=imported_count, skipped_count=skipped_count, result_json=json.dumps({"items": results, "provenance": AUTOMATION_PROVENANCE}, ensure_ascii=False))
        status = "completed" if imported_count > 0 else "skipped"
        primary_result = next(
            (item for item in results if str(item.get("status") or "") == "completed"),
            results[0] if results else {},
        )
        primary_fields = {
            key: value
            for key, value in {
                "source_article_id": primary_result.get("source_article_id"),
                "source_article_link": primary_result.get("source_article_link"),
                "source_article_title": primary_result.get("source_article_title"),
                "tracked_article_slug": primary_result.get("tracked_article_slug"),
                "topic_slug": primary_result.get("topic_slug"),
                "project_slug": primary_result.get("project_slug"),
                "publish_package_version": _safe_int(primary_result.get("publish_package_version")),
                "draft_status": primary_result.get("draft_status"),
                "draft_id": primary_result.get("draft_id"),
            }.items()
            if value not in (None, "")
        }
        if primary_fields:
            _update_run(run_id, **primary_fields)
        final_stage = str(primary_result.get("completion_stage") or "completed") if status == "completed" else "skipped"
        _mark_run_finished(run_id, status=status, stage=final_stage, result={"items": results, "provenance": AUTOMATION_PROVENANCE})
        return get_run(run_id)
    except Exception as exc:
        error_message = normalize_error(exc)
        logger.exception("WeChat MP automation run %s failed at stage", run_id)
        _mark_run_finished(run_id, status="failed", stage=_current_run_stage(run_id), error=error_message, result={"provenance": AUTOMATION_PROVENANCE})
        with _get_connection() as connection:
            ensure_automation_schema(connection)
            current = _get_run_row(connection, run_id)
            if current and current["workflow_id"] is not None:
                _update_workflow(int(current["workflow_id"]), status="failed", last_stage=str(current["stage"]), error=error_message)
        return get_run(run_id)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _current_run_stage(run_id: int) -> str:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        row = _get_run_row(connection, run_id)
        return str(row["stage"] or "unknown") if row else "unknown"


def submit_run_in_background(subscription_id: int, *, trigger: str = "manual", workflow_id: int | None = None) -> AutomationRunSubmission:
    submission = create_manual_run(subscription_id, trigger=trigger, workflow_id=workflow_id)
    thread = threading.Thread(target=execute_run, args=(submission.run_id,), name=f"wechat-automation-{submission.run_id}", daemon=True)
    thread.start()
    return submission


def retry_run(run_id: int) -> AutomationRunSubmission:
    with _get_connection() as connection:
        ensure_automation_schema(connection)
        run = _get_run_row(connection, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Automation run not found")
        result = _json_object(run["result_json"]) or {}
        if not _is_run_retryable(run, result):
            raise HTTPException(status_code=409, detail="This automation run is not retryable")
        workflow_id = int(run["workflow_id"]) if run["workflow_id"] is not None else None
        if workflow_id is None and run["source_article_link"]:
            workflow = connection.execute(
                """
                SELECT id FROM automation_workflows
                WHERE subscription_id = ? AND source_article_link = ?
                ORDER BY id DESC LIMIT 1
                """,
                (int(run["subscription_id"]), str(run["source_article_link"])),
            ).fetchone()
            workflow_id = int(workflow["id"]) if workflow else None
        subscription_id = int(run["subscription_id"])
    return submit_run_in_background(subscription_id, trigger="retry", workflow_id=workflow_id)


def run_due_cycle(*, now: datetime | None = None, owner_token: str | None = None) -> AutomationCycleResponse:
    evaluated = 0
    claimed = 0
    skipped = 0
    failed = 0
    run_ids: list[int] = []
    cycle_now = _utc_now(now)
    owner = owner_token or f"scheduler-{uuid.uuid4().hex}"
    for subscription in list_due_subscription_rows(now=cycle_now):
        evaluated += 1
        local_date = _local_date_for_subscription(subscription, cycle_now)
        lock_key = f"subscription:{int(subscription['id'])}:{local_date}"
        if not acquire_lease(lock_key, owner, lease_seconds=settings.wechat_mp_automation_lease_seconds, now=cycle_now):
            skipped += 1
            continue
        try:
            run_id = claim_scheduled_run(int(subscription["id"]), local_date, now=cycle_now)
            if run_id is None:
                skipped += 1
                continue
            claimed += 1
            run_ids.append(run_id)
            execute_run(run_id)
            if get_run(run_id).status == "failed":
                failed += 1
        finally:
            release_lease(lock_key, owner)
    return AutomationCycleResponse(
        evaluated_count=evaluated,
        claimed_count=claimed,
        skipped_count=skipped,
        failed_count=failed,
        run_ids=run_ids,
    )


class WechatMpAutomationScheduler:
    def __init__(self, *, poll_interval_seconds: int | None = None, lease_seconds: int | None = None) -> None:
        self.poll_interval_seconds = max(1, int(poll_interval_seconds or settings.wechat_mp_automation_poll_interval_seconds))
        self.lease_seconds = max(1, int(lease_seconds or settings.wechat_mp_automation_lease_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_cycle_at: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, name="wechat-mp-automation-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(5, self.poll_interval_seconds + 1))

    def run_once(self, *, now: datetime | None = None) -> AutomationCycleResponse:
        response = run_due_cycle(now=now, owner_token=f"scheduler-{uuid.uuid4().hex}")
        self.last_cycle_at = _utc_now_iso(now)
        return response

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("WeChat MP automation scheduler cycle failed")
            self._stop_event.wait(self.poll_interval_seconds)


def get_scheduler_status(scheduler: WechatMpAutomationScheduler | None) -> dict[str, object]:
    return {
        "running": bool(scheduler and scheduler.running),
        "poll_interval_seconds": int(scheduler.poll_interval_seconds if scheduler else settings.wechat_mp_automation_poll_interval_seconds),
        "last_cycle_at": scheduler.last_cycle_at if scheduler else None,
    }

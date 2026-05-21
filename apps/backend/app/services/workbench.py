from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from app.core.settings import settings
from app.schemas.background_tasks import BackgroundTaskDetail, BackgroundTaskSubmission
from app.services.ai_generator import get_default_generator
from app.schemas.projects import (
    AssetItem,
    BatchCreateProjectResult,
    BatchCreateProjectsResponse,
    BatchCreateProjectsRequest,
    BatchContinueProjectResult,
    BatchContinueProjectsResponse,
    BatchGenerateTopicResult,
    BatchGenerateTrackedArticleTopicResult,
    BatchGenerateTrackedArticleTopicsResponse,
    BatchGenerateTopicsResponse,
    BatchGenerateTopicsRequest,
    DraftItem,
    OutlineItem,
    ProjectCreate,
    ProjectDetail,
    ProjectItem,
    ProjectRetroCreate,
    ProjectRetroItem,
    PublishPackageItem,
    ProjectVersions,
    ProjectStageUpdate,
)
from app.schemas.tone_profiles import ToneProfileItem, ToneProfileReorder, ToneProfileUpsert
from app.schemas.tracked_articles import TrackedArticleCreate, TrackedArticleItem
from app.schemas.topics import TopicCreateFromTrend, TopicItem, TopicUpdate
from app.schemas.trends import TrendCreate, TrendImportResponse, TrendImportResult, TrendItem, TrendUpdate


logger = logging.getLogger(__name__)
DB_PATH = Path(settings.db_path)
GENERATED_ASSETS_DIR = Path(settings.generated_assets_dir)
DEFAULT_DB_PATH = Path("C:/tmp/gankaigc-wechat-workbench.db")
TREND_SEEDS = [
    {
        "slug": "office-burnout-recovery",
        "title": "办公室倦怠修复",
        "source": "xiaohongshu",
        "heat_score": 92,
        "status": "screening",
    },
    {
        "slug": "relationship-boundary-reset",
        "title": "关系边界重设",
        "source": "wechat-search",
        "heat_score": 88,
        "status": "selected",
    },
    {
        "slug": "self-worth-rebuild",
        "title": "自我价值重建",
        "source": "douyin",
        "heat_score": 81,
        "status": "watching",
    },
]

TOPIC_SEEDS = [
    {
        "slug": "office-burnout-recovery-for-girls",
        "source_type": "trend",
        "source_ref_slug": "office-burnout-recovery",
        "title": "把办公室倦怠写成自救路径",
        "angle": "情绪恢复",
        "status": "drafting",
    },
    {
        "slug": "relationship-boundary-reset-playbook",
        "source_type": "trend",
        "source_ref_slug": "relationship-boundary-reset",
        "title": "关系边界重设的三步清单",
        "angle": "边界表达",
        "status": "pending",
    },
    {
        "slug": "high-sensitivity-restoration",
        "source_type": "trend",
        "source_ref_slug": "relationship-boundary-reset",
        "title": "高敏感人群的稳定感恢复",
        "angle": "自我照顾",
        "status": "approved",
    },
]

PROJECT_SEEDS = [
    {
        "slug": "office-burnout-recovery-weekly",
        "topic_slug": "office-burnout-recovery-for-girls",
        "title": "办公室倦怠修复周更",
        "stage": "draft_ready",
        "owner": "editorial",
        "preferred_tone_profile_id": None,
    },
    {
        "slug": "relationship-boundary-reset-series",
        "topic_slug": "relationship-boundary-reset-playbook",
        "title": "关系边界重设系列",
        "stage": "publishing",
        "owner": "editorial",
        "preferred_tone_profile_id": None,
    },
    {
        "slug": "high-sensitivity-restoration-notes",
        "topic_slug": "high-sensitivity-restoration",
        "title": "高敏感恢复备稿",
        "stage": "outline",
        "owner": "editorial",
        "preferred_tone_profile_id": None,
    },
]

DEFAULT_TONE_PROFILE = {
    "name": "女性成长克制陪伴风",
    "opening_style": "从具体场景冷启动切入",
    "paragraph_rhythm": "短段落，慢推进",
    "closing_style": "留白式收束",
    "forbidden_phrases": ["你必须", "立刻改变"],
    "value_constraints": "不说教，不制造羞耻感，避免空泛鸡汤",
    "target_word_count": 1400,
}


def _normalize_tracked_article_source_name(source_name: str | None) -> str:
    normalized = (source_name or "").strip()
    return normalized or "手动录入"


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_generated_assets_dir() -> None:
    GENERATED_ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _is_default_persistent_store(path: Path) -> bool:
    return path.resolve() == DEFAULT_DB_PATH.resolve()


def _get_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _ensure_assets_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "assets")
    if "cover_image_path" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_path TEXT NOT NULL DEFAULT ''"
        )
    if "cover_image_url" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_url TEXT NOT NULL DEFAULT ''"
        )
    if "tone_profile_id" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN tone_profile_id INTEGER DEFAULT NULL"
        )
    if "tone_profile_name" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN tone_profile_name TEXT DEFAULT NULL"
        )


def _ensure_outlines_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "outlines")
    if "tone_profile_id" not in columns:
        connection.execute(
            "ALTER TABLE outlines ADD COLUMN tone_profile_id INTEGER DEFAULT NULL"
        )
    if "tone_profile_name" not in columns:
        connection.execute(
            "ALTER TABLE outlines ADD COLUMN tone_profile_name TEXT DEFAULT NULL"
        )


def _ensure_drafts_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "drafts")
    if "tone_profile_id" not in columns:
        connection.execute(
            "ALTER TABLE drafts ADD COLUMN tone_profile_id INTEGER DEFAULT NULL"
        )
    if "tone_profile_name" not in columns:
        connection.execute(
            "ALTER TABLE drafts ADD COLUMN tone_profile_name TEXT DEFAULT NULL"
        )


def _ensure_tone_profiles_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "tone_profiles")
    if "is_active" not in columns:
        connection.execute(
            "ALTER TABLE tone_profiles ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0"
        )
        connection.execute(
            """
            UPDATE tone_profiles
            SET is_active = CASE
                WHEN id = (SELECT MIN(id) FROM tone_profiles) THEN 1
                ELSE 0
            END
            """
        )
    if "sort_order" not in columns:
        connection.execute(
            "ALTER TABLE tone_profiles ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
        )
        rows = connection.execute(
            "SELECT id FROM tone_profiles ORDER BY is_active DESC, id ASC"
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            connection.execute(
                "UPDATE tone_profiles SET sort_order = ? WHERE id = ?",
                (index, row["id"]),
            )


def _ensure_projects_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "projects")
    if "preferred_tone_profile_id" not in columns:
        connection.execute(
            "ALTER TABLE projects ADD COLUMN preferred_tone_profile_id INTEGER DEFAULT NULL"
        )


def _ensure_publish_packages_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "publish_packages")
    if "assets_version" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN assets_version INTEGER NOT NULL DEFAULT 0"
        )
    if "version" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
        )
    if "tags" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'"
        )
    if "publish_checklist" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN publish_checklist TEXT NOT NULL DEFAULT '[]'"
        )
    if "editor_note" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN editor_note TEXT NOT NULL DEFAULT ''"
        )
    if "markdown_path" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN markdown_path TEXT NOT NULL DEFAULT ''"
        )
    if "markdown_url" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN markdown_url TEXT NOT NULL DEFAULT ''"
        )
    if "manifest_path" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN manifest_path TEXT NOT NULL DEFAULT ''"
        )
    if "manifest_url" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN manifest_url TEXT NOT NULL DEFAULT ''"
        )
    if "review_comment" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN review_comment TEXT DEFAULT NULL"
        )
    if "reviewed_by" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN reviewed_by TEXT DEFAULT NULL"
        )
    if "reviewed_at" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN reviewed_at TEXT DEFAULT NULL"
        )
    if "tone_profile_id" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN tone_profile_id INTEGER DEFAULT NULL"
        )
    if "tone_profile_name" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN tone_profile_name TEXT DEFAULT NULL"
        )


def _ensure_project_retros_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS project_retros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            publish_package_version INTEGER DEFAULT NULL,
            performance_rating INTEGER NOT NULL,
            summary TEXT NOT NULL,
            wins TEXT NOT NULL,
            gaps TEXT NOT NULL,
            next_focus TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )
        """
    )
    columns = _get_table_columns(connection, "project_retros")
    if "publish_package_version" not in columns:
        connection.execute(
            "ALTER TABLE project_retros ADD COLUMN publish_package_version INTEGER DEFAULT NULL"
        )


def _ensure_topics_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "topics")
    if "source_type" not in columns:
        connection.execute("ALTER TABLE topics ADD COLUMN source_type TEXT NOT NULL DEFAULT 'trend'")
    if "source_ref_slug" not in columns:
        connection.execute("ALTER TABLE topics ADD COLUMN source_ref_slug TEXT NOT NULL DEFAULT ''")
        connection.execute("UPDATE topics SET source_ref_slug = trend_slug WHERE source_ref_slug = ''")


def _ensure_tracked_articles_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_articles (
            slug TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            author TEXT NOT NULL,
            summary TEXT NOT NULL,
            structure_notes TEXT NOT NULL,
            tags TEXT NOT NULL
        )
        """
    )


def _ensure_background_tasks_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS background_tasks (
            task_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            result TEXT DEFAULT NULL,
            error TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT DEFAULT NULL,
            finished_at TEXT DEFAULT NULL
        )
        """
    )


def _ensure_task_logs_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "task_logs")
    if "background_task_id" not in columns:
        connection.execute(
            "ALTER TABLE task_logs ADD COLUMN background_task_id TEXT DEFAULT NULL"
        )


def initialize_store(reset: bool = False) -> None:
    if reset and _is_default_persistent_store(DB_PATH):
        raise RuntimeError(
            f"Refusing to reset persistent store at {DB_PATH}. "
            "Point DB_PATH to an isolated test database before calling initialize_store(reset=True)."
        )
    _ensure_generated_assets_dir()
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trends (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                heat_score INTEGER NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS topics (
                slug TEXT PRIMARY KEY,
                trend_slug TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'trend',
                source_ref_slug TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                angle TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                slug TEXT PRIMARY KEY,
                topic_slug TEXT NOT NULL,
                title TEXT NOT NULL,
                stage TEXT NOT NULL,
                owner TEXT NOT NULL,
                preferred_tone_profile_id INTEGER DEFAULT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_slug TEXT NOT NULL,
                version INTEGER NOT NULL,
                hook TEXT NOT NULL,
                outline_body TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_slug TEXT NOT NULL,
                outline_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                body_markdown TEXT NOT NULL,
                word_count INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_slug TEXT NOT NULL,
                draft_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                title_options TEXT NOT NULL,
                cover_prompt TEXT NOT NULL,
                cover_copy TEXT NOT NULL,
                social_teaser TEXT NOT NULL,
                cover_image_path TEXT NOT NULL,
                cover_image_url TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS publish_packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_slug TEXT NOT NULL,
                draft_version INTEGER NOT NULL,
                assets_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                abstract TEXT NOT NULL,
                tags TEXT NOT NULL,
                publish_checklist TEXT NOT NULL,
                editor_note TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                markdown_url TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                manifest_url TEXT NOT NULL,
                status TEXT NOT NULL,
                review_comment TEXT DEFAULT NULL,
                reviewed_by TEXT DEFAULT NULL,
                reviewed_at TEXT DEFAULT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                entity_slug TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                background_task_id TEXT DEFAULT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tone_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                is_active INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                opening_style TEXT NOT NULL,
                paragraph_rhythm TEXT NOT NULL,
                closing_style TEXT NOT NULL,
                forbidden_phrases TEXT NOT NULL,
                value_constraints TEXT NOT NULL,
                target_word_count INTEGER NOT NULL
            )
            """
        )
        _ensure_projects_schema(connection)
        _ensure_topics_schema(connection)
        _ensure_outlines_schema(connection)
        _ensure_drafts_schema(connection)
        _ensure_assets_schema(connection)
        _ensure_tone_profiles_schema(connection)
        _ensure_publish_packages_schema(connection)
        _ensure_project_retros_schema(connection)
        _ensure_tracked_articles_schema(connection)
        _ensure_background_tasks_schema(connection)
        _ensure_task_logs_schema(connection)

        if reset:
            connection.execute("DELETE FROM trends")
            connection.execute("DELETE FROM topics")
            connection.execute("DELETE FROM projects")
            connection.execute("DELETE FROM outlines")
            connection.execute("DELETE FROM drafts")
            connection.execute("DELETE FROM assets")
            connection.execute("DELETE FROM publish_packages")
            connection.execute("DELETE FROM project_retros")
            connection.execute("DELETE FROM tracked_articles")
            connection.execute("DELETE FROM task_logs")
            connection.execute("DELETE FROM tone_profiles")
            connection.execute("DELETE FROM background_tasks")
            connection.execute("DELETE FROM app_meta")
            connection.commit()
            for asset_file in GENERATED_ASSETS_DIR.glob("*"):
                if asset_file.is_file():
                    asset_file.unlink()

        initialized = connection.execute("SELECT value FROM app_meta WHERE key = 'seeded'").fetchone()
        if initialized:
            return

        connection.executemany(
            """
            INSERT INTO trends (slug, title, source, heat_score, status)
            VALUES (:slug, :title, :source, :heat_score, :status)
            """,
            TREND_SEEDS,
        )
        connection.executemany(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (:slug, :source_ref_slug, :source_type, :source_ref_slug, :title, :angle, :status)
            """,
            TOPIC_SEEDS,
        )
        connection.executemany(
            """
            INSERT INTO projects (slug, topic_slug, title, stage, owner)
            VALUES (:slug, :topic_slug, :title, :stage, :owner)
            """,
            [
                {
                    "slug": project["slug"],
                    "topic_slug": project["topic_slug"],
                    "title": project["title"],
                    "stage": project["stage"],
                    "owner": project["owner"],
                }
                for project in PROJECT_SEEDS
            ],
        )
        for project in PROJECT_SEEDS:
            connection.execute(
                "UPDATE projects SET preferred_tone_profile_id = ? WHERE slug = ?",
                (project["preferred_tone_profile_id"], project["slug"]),
            )
        connection.execute(
            """
            INSERT INTO tone_profiles (
                is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                DEFAULT_TONE_PROFILE["name"],
                DEFAULT_TONE_PROFILE["opening_style"],
                DEFAULT_TONE_PROFILE["paragraph_rhythm"],
                DEFAULT_TONE_PROFILE["closing_style"],
                json.dumps(DEFAULT_TONE_PROFILE["forbidden_phrases"], ensure_ascii=False),
                DEFAULT_TONE_PROFILE["value_constraints"],
                DEFAULT_TONE_PROFILE["target_word_count"],
            ),
        )
        connection.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?)",
            ("seeded", json.dumps({"version": 1})),
        )
        connection.commit()


def list_trends() -> list[TrendItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT slug, title, source, heat_score, status
            FROM trends
            ORDER BY heat_score DESC, rowid ASC
            """
        ).fetchall()
    return [TrendItem(**dict(row)) for row in rows]


def _hydrate_tone_profile_row(row: sqlite3.Row) -> ToneProfileItem:
    payload = dict(row)
    payload["is_active"] = bool(payload["is_active"])
    payload["forbidden_phrases"] = json.loads(payload["forbidden_phrases"])
    return ToneProfileItem(**payload)


def list_tone_profiles() -> list[ToneProfileItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            ORDER BY is_active DESC, sort_order ASC, id ASC
            """
        ).fetchall()
    return [_hydrate_tone_profile_row(row) for row in rows]


def create_tone_profile(payload: ToneProfileUpsert) -> ToneProfileItem:
    with _get_connection() as connection:
        next_sort_order = int(
            connection.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS sort_order FROM tone_profiles"
            ).fetchone()["sort_order"]
        ) + 1
        connection.execute(
            """
            INSERT INTO tone_profiles (
                is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                0,
                next_sort_order,
                payload.name,
                payload.opening_style,
                payload.paragraph_rhythm,
                payload.closing_style,
                json.dumps(payload.forbidden_phrases, ensure_ascii=False),
                payload.value_constraints,
                payload.target_word_count,
            ),
        )
        profile_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
    return _hydrate_tone_profile_row(row)


def update_tone_profile(profile_id: int, payload: ToneProfileUpsert) -> ToneProfileItem:
    with _get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM tone_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Tone profile not found")

        connection.execute(
            """
            UPDATE tone_profiles
            SET name = ?, opening_style = ?, paragraph_rhythm = ?, closing_style = ?, forbidden_phrases = ?, value_constraints = ?, target_word_count = ?
            WHERE id = ?
            """,
            (
                payload.name,
                payload.opening_style,
                payload.paragraph_rhythm,
                payload.closing_style,
                json.dumps(payload.forbidden_phrases, ensure_ascii=False),
                payload.value_constraints,
                payload.target_word_count,
                profile_id,
            ),
        )
        connection.commit()
        row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
    return _hydrate_tone_profile_row(row)


def activate_tone_profile(profile_id: int) -> ToneProfileItem:
    with _get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM tone_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Tone profile not found")

        connection.execute("UPDATE tone_profiles SET is_active = 0")
        connection.execute(
            "UPDATE tone_profiles SET is_active = 1 WHERE id = ?",
            (profile_id,),
        )
        connection.commit()
        row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
    return _hydrate_tone_profile_row(row)


def get_active_tone_profile() -> ToneProfileItem:
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE is_active = 1
            ORDER BY sort_order ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Tone profile not configured")
    return _hydrate_tone_profile_row(row)


def get_tone_profile_by_id(profile_id: int) -> ToneProfileItem | None:
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
    return _hydrate_tone_profile_row(row) if row else None


def get_project_tone_profile(project_row: sqlite3.Row) -> ToneProfileItem:
    preferred_tone_profile_id = project_row["preferred_tone_profile_id"]
    if preferred_tone_profile_id is not None:
        preferred_profile = get_tone_profile_by_id(int(preferred_tone_profile_id))
        if preferred_profile:
            return preferred_profile
    return get_active_tone_profile()


def duplicate_tone_profile(profile_id: int) -> ToneProfileItem:
    with _get_connection() as connection:
        source_row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
        if not source_row:
            raise HTTPException(status_code=404, detail="Tone profile not found")

        next_sort_order = int(
            connection.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS sort_order FROM tone_profiles"
            ).fetchone()["sort_order"]
        ) + 1
        connection.execute(
            """
            INSERT INTO tone_profiles (
                is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                0,
                next_sort_order,
                f"{source_row['name']} 副本",
                source_row["opening_style"],
                source_row["paragraph_rhythm"],
                source_row["closing_style"],
                source_row["forbidden_phrases"],
                source_row["value_constraints"],
                source_row["target_word_count"],
            ),
        )
        duplicated_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        row = connection.execute(
            """
            SELECT id, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
            FROM tone_profiles
            WHERE id = ?
            """,
            (duplicated_id,),
        ).fetchone()
    return _hydrate_tone_profile_row(row)


def reorder_tone_profiles(payload: ToneProfileReorder) -> list[ToneProfileItem]:
    with _get_connection() as connection:
        rows = connection.execute("SELECT id FROM tone_profiles ORDER BY sort_order ASC, id ASC").fetchall()
        existing_ids = [int(row["id"]) for row in rows]
        if sorted(existing_ids) != sorted(payload.profile_ids):
            raise HTTPException(status_code=400, detail="Tone profile reorder set does not match existing profiles")

        for sort_order, profile_id in enumerate(payload.profile_ids, start=1):
            connection.execute(
                "UPDATE tone_profiles SET sort_order = ? WHERE id = ?",
                (sort_order, profile_id),
            )
        connection.commit()
    return list_tone_profiles()


def delete_tone_profile(profile_id: int) -> dict[str, int]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, is_active, sort_order
            FROM tone_profiles
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        if len(rows) <= 1:
            raise HTTPException(status_code=409, detail="Cannot delete the last tone profile")

        target_row = next((row for row in rows if int(row["id"]) == profile_id), None)
        if not target_row:
            raise HTTPException(status_code=404, detail="Tone profile not found")

        connection.execute(
            "UPDATE projects SET preferred_tone_profile_id = NULL WHERE preferred_tone_profile_id = ?",
            (profile_id,),
        )
        connection.execute("DELETE FROM tone_profiles WHERE id = ?", (profile_id,))

        remaining_rows = connection.execute(
            """
            SELECT id, is_active
            FROM tone_profiles
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        if bool(target_row["is_active"]) and remaining_rows:
            next_active_id = int(remaining_rows[0]["id"])
            connection.execute("UPDATE tone_profiles SET is_active = 0")
            connection.execute(
                "UPDATE tone_profiles SET is_active = 1 WHERE id = ?",
                (next_active_id,),
            )
        connection.commit()
    return {"deleted_profile_id": profile_id}


def _record_task(
    connection: sqlite3.Connection,
    *,
    task_type: str,
    status: str,
    entity_slug: str,
    entity_type: str,
    background_task_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO task_logs (task_type, status, entity_slug, entity_type, created_at, background_task_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_type, status, entity_slug, entity_type, _utc_now_iso(), background_task_id),
    )


def _update_background_task_log_status(
    connection: sqlite3.Connection,
    *,
    background_task_id: str,
    status: str,
) -> None:
    connection.execute(
        """
        UPDATE task_logs
        SET status = ?
        WHERE background_task_id = ?
        """,
        (status, background_task_id),
    )


def create_trend(payload: TrendCreate) -> TrendItem:
    with _get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO trends (slug, title, source, heat_score, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.slug,
                    payload.title,
                    payload.source,
                    payload.heat_score,
                    payload.status,
                ),
            )
            _record_task(
                connection,
                task_type="trend_created",
                status="done",
                entity_slug=payload.slug,
                entity_type="trend",
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Trend slug already exists") from exc
    return TrendItem(**payload.model_dump())


def _slugify_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "trend"


def import_trends(raw_text: str) -> TrendImportResponse:
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    results: list[TrendImportResult] = []
    created_count = 0
    title_counts: dict[str, int] = {}
    existing_titles = {trend.title for trend in list_trends()}

    for line_number, raw_line in enumerate(raw_lines, start=1):
        parts = [part.strip() for part in raw_line.split("|")]
        title = parts[0] if parts else ""
        source = parts[1] if len(parts) > 1 and parts[1] else "manual-import"
        heat_score = 50
        if len(parts) > 2 and parts[2]:
            try:
                heat_score = int(parts[2])
            except ValueError:
                heat_score = 50
        status = parts[3] if len(parts) > 3 and parts[3] else "screening"
        if title in existing_titles:
            results.append(
                TrendImportResult(
                    line_number=line_number,
                    raw_line=raw_line,
                    status="failed",
                    error="Trend title already exists",
                )
            )
            continue

        base_slug = _slugify_text(title)
        title_counts[base_slug] = title_counts.get(base_slug, 0) + 1
        slug = f"{base_slug}-{title_counts[base_slug]}"

        try:
            trend = create_trend(
                TrendCreate(
                    slug=slug,
                    title=title,
                    source=source,
                    heat_score=heat_score,
                    status=status,
                )
            )
            created_count += 1
            results.append(
                TrendImportResult(
                    line_number=line_number,
                    raw_line=raw_line,
                    status="done",
                    trend=trend,
                )
            )
            existing_titles.add(title)
        except HTTPException as exc:
            results.append(
                TrendImportResult(
                    line_number=line_number,
                    raw_line=raw_line,
                    status="failed",
                    error=str(exc.detail),
                )
            )

    return TrendImportResponse(
        requested_count=len(raw_lines),
        created_count=created_count,
        failed_count=len(raw_lines) - created_count,
        results=results,
    )


def update_trend(trend_slug: str, payload: TrendUpdate) -> TrendItem:
    with _get_connection() as connection:
        existing = connection.execute(
            """
            SELECT slug, source
            FROM trends
            WHERE slug = ?
            """,
            (trend_slug,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Trend not found")

        connection.execute(
            """
            UPDATE trends
            SET title = ?, heat_score = ?, status = ?
            WHERE slug = ?
            """,
            (payload.title, payload.heat_score, payload.status, trend_slug),
        )
        _record_task(
            connection,
            task_type="trend_updated",
            status="done",
            entity_slug=trend_slug,
            entity_type="trend",
        )
        connection.commit()
    return TrendItem(
        slug=trend_slug,
        title=payload.title,
        source=str(existing["source"]),
        heat_score=payload.heat_score,
        status=payload.status,
    )


def list_tracked_articles() -> list[TrackedArticleItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT slug, source_name, title, url, author, summary, structure_notes, tags
            FROM tracked_articles
            ORDER BY rowid DESC
            """
        ).fetchall()
    return [
        TrackedArticleItem(
            slug=str(row["slug"]),
            source_name=_normalize_tracked_article_source_name(str(row["source_name"])),
            title=str(row["title"]),
            url=str(row["url"]),
            author=str(row["author"]),
            summary=str(row["summary"]),
            structure_notes=str(row["structure_notes"]),
            tags=json.loads(str(row["tags"])),
        )
        for row in rows
    ]


def create_tracked_article(payload: TrackedArticleCreate) -> TrackedArticleItem:
    source_name = _normalize_tracked_article_source_name(payload.source_name)
    with _get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO tracked_articles (slug, source_name, title, url, author, summary, structure_notes, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.slug,
                    source_name,
                    payload.title,
                    payload.url,
                    payload.author,
                    payload.summary,
                    payload.structure_notes,
                    json.dumps(payload.tags, ensure_ascii=False),
                ),
            )
            _record_task(
                connection,
                task_type="tracked_article_created",
                status="done",
                entity_slug=payload.slug,
                entity_type="tracked_article",
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Tracked article slug already exists") from exc
    return TrackedArticleItem(**{**payload.model_dump(), "source_name": source_name})


def list_topics() -> list[TopicItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT slug, trend_slug, source_type, source_ref_slug, title, angle, status
            FROM topics
            ORDER BY rowid DESC
            """
        ).fetchall()
    return [TopicItem(**dict(row)) for row in rows]


def create_topic_from_trend(trend_slug: str, payload: TopicCreateFromTrend) -> TopicItem:
    with _get_connection() as connection:
        trend = connection.execute(
            "SELECT slug FROM trends WHERE slug = ?",
            (trend_slug,),
        ).fetchone()
        if not trend:
            raise HTTPException(status_code=404, detail="Trend not found")

        try:
            connection.execute(
                """
                INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (payload.slug, trend_slug, "trend", trend_slug, payload.title, payload.angle, "pending"),
            )
            _record_task(
                connection,
                task_type="topic_created",
                status="done",
                entity_slug=payload.slug,
                entity_type="topic",
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Topic slug already exists") from exc
    return TopicItem(
        slug=payload.slug,
        trend_slug=trend_slug,
        source_type="trend",
        source_ref_slug=trend_slug,
        title=payload.title,
        angle=payload.angle,
        status="pending",
    )


def create_topic_from_tracked_article(article_slug: str, payload: TopicCreateFromTrend) -> TopicItem:
    with _get_connection() as connection:
        article = connection.execute(
            "SELECT slug FROM tracked_articles WHERE slug = ?",
            (article_slug,),
        ).fetchone()
        if not article:
            raise HTTPException(status_code=404, detail="Tracked article not found")

        try:
            connection.execute(
                """
                INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (payload.slug, article_slug, "tracked_article", article_slug, payload.title, payload.angle, "pending"),
            )
            _record_task(
                connection,
                task_type="topic_created",
                status="done",
                entity_slug=payload.slug,
                entity_type="topic",
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Topic slug already exists") from exc
    return TopicItem(
        slug=payload.slug,
        trend_slug=article_slug,
        source_type="tracked_article",
        source_ref_slug=article_slug,
        title=payload.title,
        angle=payload.angle,
        status="pending",
    )


def update_topic(topic_slug: str, payload: TopicUpdate) -> TopicItem:
    with _get_connection() as connection:
        existing = connection.execute(
            """
            SELECT slug, trend_slug, source_type, source_ref_slug
            FROM topics
            WHERE slug = ?
            """,
            (topic_slug,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Topic not found")

        connection.execute(
            """
            UPDATE topics
            SET title = ?, angle = ?, status = ?
            WHERE slug = ?
            """,
            (payload.title, payload.angle, payload.status, topic_slug),
        )
        _record_task(
            connection,
            task_type="topic_updated",
            status="done",
            entity_slug=topic_slug,
            entity_type="topic",
        )
        connection.commit()
    return TopicItem(
        slug=topic_slug,
        trend_slug=str(existing["trend_slug"]) if existing["trend_slug"] is not None else None,
        source_type=str(existing["source_type"]),
        source_ref_slug=str(existing["source_ref_slug"]),
        title=payload.title,
        angle=payload.angle,
        status=payload.status,
    )


def generate_topic_from_trend(trend_slug: str) -> TopicItem:
    tone_profile = get_active_tone_profile()
    with _get_connection() as connection:
        trend = connection.execute(
            """
            SELECT slug, title, source, heat_score, status
            FROM trends
            WHERE slug = ?
            """,
            (trend_slug,),
        ).fetchone()
        if not trend:
            raise HTTPException(status_code=404, detail="Trend not found")

        current = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM topics
            WHERE trend_slug = ? AND slug LIKE ?
            """,
            (trend_slug, f"{trend_slug}-ai-topic-%"),
        ).fetchone()
        slug = f"{trend_slug}-ai-topic-{int(current['total']) + 1}"
        ai_result = get_ai_generator().generate_topic(
            {
                "trend_slug": trend["slug"],
                "trend_title": trend["title"],
                "source": trend["source"],
                "heat_score": trend["heat_score"],
                "status": trend["status"],
                "tone_profile": tone_profile.model_dump(),
            }
        )
        connection.execute(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (slug, trend_slug, "trend", trend_slug, ai_result["title"], ai_result["angle"], "pending"),
        )
        _record_task(
            connection,
            task_type="topic_generation",
            status="done",
            entity_slug=slug,
            entity_type="topic",
        )
        connection.commit()

    return TopicItem(
        slug=slug,
        trend_slug=trend_slug,
        source_type="trend",
        source_ref_slug=trend_slug,
        title=str(ai_result["title"]),
        angle=str(ai_result["angle"]),
        status="pending",
    )


def generate_topic_from_tracked_article(article_slug: str) -> TopicItem:
    tone_profile = get_active_tone_profile()
    with _get_connection() as connection:
        article = connection.execute(
            """
            SELECT slug, source_name, title, author, summary, structure_notes, tags
            FROM tracked_articles
            WHERE slug = ?
            """,
            (article_slug,),
        ).fetchone()
        if not article:
            raise HTTPException(status_code=404, detail="Tracked article not found")

        current = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM topics
            WHERE source_type = 'tracked_article' AND source_ref_slug = ? AND slug LIKE ?
            """,
            (article_slug, f"{article_slug}-ai-topic-%"),
        ).fetchone()
        slug = f"{article_slug}-ai-topic-{int(current['total']) + 1}"
        ai_result = get_ai_generator().generate_topic(
            {
                "source_type": "tracked_article",
                "source_ref_slug": article["slug"],
                "source_name": _normalize_tracked_article_source_name(str(article["source_name"])),
                "article_title": article["title"],
                "author": article["author"],
                "summary": article["summary"],
                "structure_notes": article["structure_notes"],
                "tags": json.loads(str(article["tags"])),
                "tone_profile": tone_profile.model_dump(),
            }
        )
        connection.execute(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (slug, article_slug, "tracked_article", article_slug, ai_result["title"], ai_result["angle"], "pending"),
        )
        _record_task(
            connection,
            task_type="topic_generation",
            status="done",
            entity_slug=slug,
            entity_type="topic",
        )
        connection.commit()

    return TopicItem(
        slug=slug,
        trend_slug=article_slug,
        source_type="tracked_article",
        source_ref_slug=article_slug,
        title=str(ai_result["title"]),
        angle=str(ai_result["angle"]),
        status="pending",
    )


def list_projects() -> list[ProjectItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                p.slug,
                p.topic_slug,
                p.title,
                p.stage,
                p.owner,
                p.preferred_tone_profile_id,
                tp.name AS preferred_tone_profile_name
            FROM projects p
            LEFT JOIN tone_profiles tp ON tp.id = p.preferred_tone_profile_id
            ORDER BY p.rowid DESC
            """
        ).fetchall()
        return [_build_project_item(connection, row) for row in rows]


def create_project_from_topic(topic_slug: str, payload: ProjectCreate) -> ProjectItem:
    with _get_connection() as connection:
        topic = connection.execute(
            "SELECT slug FROM topics WHERE slug = ?",
            (topic_slug,),
        ).fetchone()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        if payload.preferred_tone_profile_id is not None:
            tone_profile = connection.execute(
                "SELECT id FROM tone_profiles WHERE id = ?",
                (payload.preferred_tone_profile_id,),
            ).fetchone()
            if not tone_profile:
                raise HTTPException(status_code=404, detail="Tone profile not found")

        try:
            connection.execute(
                """
                INSERT INTO projects (slug, topic_slug, title, stage, owner, preferred_tone_profile_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (payload.slug, topic_slug, payload.title, "outline", payload.owner, payload.preferred_tone_profile_id),
            )
            _record_task(
                connection,
                task_type="project_created",
                status="done",
                entity_slug=payload.slug,
                entity_type="project",
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Project slug already exists") from exc
    return get_project_detail(payload.slug).project


def update_project_stage(project_slug: str, payload: ProjectStageUpdate) -> ProjectItem:
    with _get_connection() as connection:
        existing = connection.execute(
            """
            SELECT slug, topic_slug, title, stage, owner, preferred_tone_profile_id
            FROM projects
            WHERE slug = ?
            """,
            (project_slug,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Project not found")

        if payload.preferred_tone_profile_id is not None:
            tone_profile = connection.execute(
                "SELECT id FROM tone_profiles WHERE id = ?",
                (payload.preferred_tone_profile_id,),
            ).fetchone()
            if not tone_profile:
                raise HTTPException(status_code=404, detail="Tone profile not found")

        next_preferred_tone_profile_id = existing["preferred_tone_profile_id"]
        if "preferred_tone_profile_id" in payload.model_fields_set:
            next_preferred_tone_profile_id = payload.preferred_tone_profile_id

        connection.execute(
            "UPDATE projects SET stage = ?, preferred_tone_profile_id = ? WHERE slug = ?",
            (payload.stage, next_preferred_tone_profile_id, project_slug),
        )
        connection.commit()

    return get_project_detail(project_slug).project


def _get_project_row(project_slug: str) -> sqlite3.Row:
    with _get_connection() as connection:
        existing = connection.execute(
            """
            SELECT
                p.slug,
                p.topic_slug,
                p.title,
                p.stage,
                p.owner,
                p.preferred_tone_profile_id,
                tp.name AS preferred_tone_profile_name
            FROM projects p
            LEFT JOIN tone_profiles tp ON tp.id = p.preferred_tone_profile_id
            WHERE p.slug = ?
            """,
            (project_slug,),
        ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    return existing


def _get_project_context(project_slug: str) -> sqlite3.Row:
    with _get_connection() as connection:
        existing = connection.execute(
            """
            SELECT
                p.slug,
                p.topic_slug,
                p.title,
                p.stage,
                p.owner,
                p.preferred_tone_profile_id,
                tp.name AS preferred_tone_profile_name,
                t.source_type,
                t.source_ref_slug,
                t.title AS topic_title,
                t.angle AS topic_angle,
                CASE
                    WHEN t.source_type = 'trend' THEN tr.title
                    WHEN t.source_type = 'tracked_article' THEN '参考文章 / ' || COALESCE(NULLIF(TRIM(ta.source_name), ''), '手动录入')
                    ELSE t.source_ref_slug
                END AS trend_title
            FROM projects p
            LEFT JOIN tone_profiles tp ON tp.id = p.preferred_tone_profile_id
            JOIN topics t ON t.slug = p.topic_slug
            LEFT JOIN trends tr ON tr.slug = t.source_ref_slug AND t.source_type = 'trend'
            LEFT JOIN tracked_articles ta ON ta.slug = t.source_ref_slug AND t.source_type = 'tracked_article'
            WHERE p.slug = ?
            """,
            (project_slug,),
        ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    return existing


def get_ai_generator():
    return get_default_generator()


def _get_project_chain_rows(connection: sqlite3.Connection, project_slug: str) -> tuple[
    sqlite3.Row | None,
    sqlite3.Row | None,
    sqlite3.Row | None,
    sqlite3.Row | None,
]:
    outline_row = connection.execute(
        """
        SELECT project_slug, version, hook, outline_body, tone_profile_id, tone_profile_name
        FROM outlines
        WHERE project_slug = ?
        ORDER BY version DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()

    draft_row = None
    assets_row = None
    publish_package_row = None
    if outline_row:
        draft_row = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ? AND outline_version = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug, outline_row["version"]),
        ).fetchone()
    if draft_row:
        assets_row = connection.execute(
            """
            SELECT
                project_slug,
                draft_version,
                version,
                title_options,
                cover_prompt,
                cover_copy,
                social_teaser,
                cover_image_path,
                cover_image_url,
                tone_profile_id,
                tone_profile_name
            FROM assets
            WHERE project_slug = ? AND draft_version = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug, draft_row["version"]),
        ).fetchone()
    if assets_row:
        publish_package_row = connection.execute(
            """
            SELECT
                project_slug,
                draft_version,
                assets_version,
                version,
                abstract,
                tags,
                publish_checklist,
                editor_note,
                markdown_path,
                markdown_url,
                manifest_path,
                manifest_url,
                status,
                review_comment,
                reviewed_by,
                reviewed_at,
                tone_profile_id,
                tone_profile_name
            FROM publish_packages
            WHERE project_slug = ? AND draft_version = ? AND assets_version = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug, draft_row["version"], assets_row["version"]),
        ).fetchone()

    return outline_row, draft_row, assets_row, publish_package_row


def _derive_project_chain_state(
    *,
    stage: str,
    outline_row: sqlite3.Row | None,
    draft_row: sqlite3.Row | None,
    assets_row: sqlite3.Row | None,
    publish_package_row: sqlite3.Row | None,
) -> dict[str, object]:
    current_outline_version = int(outline_row["version"]) if outline_row else None
    current_draft_version = int(draft_row["version"]) if draft_row else None
    current_assets_version = int(assets_row["version"]) if assets_row else None
    current_publish_package_version = int(publish_package_row["version"]) if publish_package_row else None

    if not outline_row:
        chain_status = "missing"
        current_chain_state = "missing_outline"
        next_required_step = "generate_outline"
    elif not draft_row:
        chain_status = "stale"
        current_chain_state = "outline_ready"
        next_required_step = "generate_draft"
    elif not assets_row:
        chain_status = "stale"
        current_chain_state = "draft_ready"
        next_required_step = "generate_assets"
    elif not publish_package_row:
        chain_status = "stale"
        current_chain_state = "assets_ready"
        next_required_step = "build_publish_package"
    else:
        package_status = str(publish_package_row["status"])
        if package_status == "needs_revision":
            chain_status = "stale"
            current_chain_state = "revision_requested"
            next_required_step = "regenerate_from_review"
        elif package_status == "approved":
            chain_status = "ready"
            current_chain_state = "published"
            next_required_step = None
        else:
            chain_status = "ready"
            current_chain_state = "publish_ready"
            next_required_step = None

    return {
        "chain_status": chain_status,
        "current_chain_state": current_chain_state,
        "next_required_step": next_required_step,
        "current_outline_version": current_outline_version,
        "current_draft_version": current_draft_version,
        "current_assets_version": current_assets_version,
        "current_publish_package_version": current_publish_package_version,
    }


def _build_project_item_from_rows(
    project_row: sqlite3.Row,
    *,
    outline_row: sqlite3.Row | None,
    draft_row: sqlite3.Row | None,
    assets_row: sqlite3.Row | None,
    publish_package_row: sqlite3.Row | None,
    retro_row: sqlite3.Row | None = None,
) -> ProjectItem:
    payload = dict(project_row)
    payload["retro"] = _hydrate_project_retro_row(retro_row).model_dump() if retro_row else None
    payload.update(
        _derive_project_chain_state(
            stage=str(project_row["stage"]),
            outline_row=outline_row,
            draft_row=draft_row,
            assets_row=assets_row,
            publish_package_row=publish_package_row,
        )
    )
    return ProjectItem(**payload)


def _build_project_item(connection: sqlite3.Connection, project_row: sqlite3.Row) -> ProjectItem:
    outline_row, draft_row, assets_row, publish_package_row = _get_project_chain_rows(
        connection, str(project_row["slug"])
    )
    retro_row = _get_project_retro_row(
        connection,
        str(project_row["slug"]),
        publish_package_row=publish_package_row,
    )
    return _build_project_item_from_rows(
        project_row,
        outline_row=outline_row,
        draft_row=draft_row,
        assets_row=assets_row,
        publish_package_row=publish_package_row,
        retro_row=retro_row,
    )


def _get_project_retro_row(
    connection: sqlite3.Connection,
    project_slug: str,
    *,
    publish_package_row: sqlite3.Row | None,
) -> sqlite3.Row | None:
    if not publish_package_row or str(publish_package_row["status"]) != "approved":
        return None

    current_publish_package_version = int(publish_package_row["version"])
    version_bound_row = connection.execute(
        """
        SELECT
            project_slug,
            publish_package_version,
            performance_rating,
            summary,
            wins,
            gaps,
            next_focus,
            recorded_at
        FROM project_retros
        WHERE project_slug = ? AND publish_package_version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug, current_publish_package_version),
    ).fetchone()
    if version_bound_row:
        return version_bound_row

    legacy_row = connection.execute(
        """
        SELECT
            id,
            project_slug,
            publish_package_version,
            performance_rating,
            summary,
            wins,
            gaps,
            next_focus,
            recorded_at
        FROM project_retros
        WHERE project_slug = ? AND publish_package_version IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()
    if not legacy_row:
        return None

    inferred_version = _infer_legacy_retro_publish_package_version(
        connection,
        project_slug,
        recorded_at=str(legacy_row["recorded_at"]),
    )
    if inferred_version == current_publish_package_version:
        return legacy_row

    return None


def _infer_legacy_retro_publish_package_version(
    connection: sqlite3.Connection,
    project_slug: str,
    *,
    recorded_at: str,
) -> int | None:
    package_rows = connection.execute(
        """
        SELECT version, reviewed_at
        FROM publish_packages
        WHERE project_slug = ? AND reviewed_at IS NOT NULL
        ORDER BY version ASC
        """,
        (project_slug,),
    ).fetchall()
    if not package_rows:
        return None

    retro_task_row = connection.execute(
        """
        SELECT id
        FROM task_logs
        WHERE entity_slug = ? AND entity_type = 'project' AND task_type = 'project_retro_recorded'
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()
    if retro_task_row:
        build_count_row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM task_logs
            WHERE
                entity_slug = ?
                AND entity_type = 'project'
                AND task_type = 'publish_package_built'
                AND id < ?
            """,
            (project_slug, retro_task_row["id"]),
        ).fetchone()
        build_count = int(build_count_row["count"])
        if build_count > 0:
            return build_count

    if not recorded_at:
        return None

    matched_version: int | None = None
    for row in package_rows:
        if str(row["reviewed_at"]) <= recorded_at:
            matched_version = int(row["version"])
    return matched_version


def _hydrate_project_retro_row(row: sqlite3.Row) -> ProjectRetroItem:
    return ProjectRetroItem(
        project_slug=str(row["project_slug"]),
        performance_rating=int(row["performance_rating"]),
        summary=str(row["summary"]),
        wins=json.loads(str(row["wins"])),
        gaps=json.loads(str(row["gaps"])),
        next_focus=str(row["next_focus"]),
        recorded_at=str(row["recorded_at"]),
    )


def get_project_detail(project_slug: str) -> ProjectDetail:
    project_row = _get_project_row(project_slug)
    with _get_connection() as connection:
        outline_row, draft_row, assets_row, publish_package_row = _get_project_chain_rows(
            connection, project_slug
        )
        retro_row = _get_project_retro_row(
            connection,
            project_slug,
            publish_package_row=publish_package_row,
        )

    return ProjectDetail(
        project=_build_project_item_from_rows(
            project_row,
            outline_row=outline_row,
            draft_row=draft_row,
            assets_row=assets_row,
            publish_package_row=publish_package_row,
            retro_row=retro_row,
        ),
        outline=OutlineItem(**dict(outline_row)) if outline_row else None,
        draft=DraftItem(**dict(draft_row)) if draft_row else None,
        assets=_hydrate_asset_row(assets_row) if assets_row else None,
        publish_package=_hydrate_publish_package_row(publish_package_row) if publish_package_row else None,
        retro=_hydrate_project_retro_row(retro_row) if retro_row else None,
    )


def get_project_versions(project_slug: str) -> ProjectVersions:
    _get_project_row(project_slug)
    with _get_connection() as connection:
        outline_rows = connection.execute(
            """
            SELECT project_slug, version, hook, outline_body, tone_profile_id, tone_profile_name
            FROM outlines
            WHERE project_slug = ?
            ORDER BY version DESC
            """,
            (project_slug,),
        ).fetchall()
        draft_rows = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ?
            ORDER BY version DESC
            """,
            (project_slug,),
        ).fetchall()
        assets_rows = connection.execute(
            """
            SELECT
                project_slug,
                draft_version,
                version,
                title_options,
                cover_prompt,
                cover_copy,
                social_teaser,
                cover_image_path,
                cover_image_url,
                tone_profile_id,
                tone_profile_name
            FROM assets
            WHERE project_slug = ?
            ORDER BY version DESC
            """,
            (project_slug,),
        ).fetchall()
        publish_package_rows = connection.execute(
            """
            SELECT
                project_slug,
                draft_version,
                assets_version,
                version,
                abstract,
                tags,
                publish_checklist,
                editor_note,
                markdown_path,
                markdown_url,
                manifest_path,
                manifest_url,
                status,
                review_comment,
                reviewed_by,
                reviewed_at,
                tone_profile_id,
                tone_profile_name
            FROM publish_packages
            WHERE project_slug = ?
            ORDER BY version DESC
            """,
            (project_slug,),
        ).fetchall()

    return ProjectVersions(
        project_slug=project_slug,
        outlines=[OutlineItem(**dict(row)) for row in outline_rows],
        drafts=[DraftItem(**dict(row)) for row in draft_rows],
        assets=[_hydrate_asset_row(row) for row in assets_rows],
        publish_packages=[_hydrate_publish_package_row(row) for row in publish_package_rows],
    )


def generate_outline(project_slug: str) -> OutlineItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    ai_result = get_ai_generator().generate_outline(
        {
            "trend_title": project["trend_title"],
            "topic_title": project["topic_title"],
            "topic_angle": project["topic_angle"],
            "project_title": project["title"],
            "tone_profile": tone_profile.model_dump(),
        }
    )
    with _get_connection() as connection:
        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM outlines WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        version = int(current["version"]) + 1
        hook = str(ai_result["hook"])
        outline_body = str(ai_result["outline_body"])
        connection.execute(
            """
            INSERT INTO outlines (project_slug, version, hook, outline_body, tone_profile_id, tone_profile_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_slug, version, hook, outline_body, tone_profile.id, tone_profile.name),
        )
        _record_task(
            connection,
            task_type="outline_generation",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("outline_ready", project_slug),
        )
        connection.commit()

    return OutlineItem(
        project_slug=project_slug,
        version=version,
        hook=hook,
        outline_body=outline_body,
        tone_profile_id=tone_profile.id,
        tone_profile_name=tone_profile.name,
    )


def restore_outline_version(project_slug: str, version: int) -> OutlineItem:
    with _get_connection() as connection:
        outline_row = connection.execute(
            """
            SELECT project_slug, version, hook, outline_body, tone_profile_id, tone_profile_name
            FROM outlines
            WHERE project_slug = ? AND version = ?
            """,
            (project_slug, version),
        ).fetchone()
        if not outline_row:
            raise HTTPException(status_code=404, detail="Outline version not found")

        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM outlines WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        next_version = int(current["version"]) + 1
        connection.execute(
            """
            INSERT INTO outlines (project_slug, version, hook, outline_body, tone_profile_id, tone_profile_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                next_version,
                outline_row["hook"],
                outline_row["outline_body"],
                outline_row["tone_profile_id"],
                outline_row["tone_profile_name"],
            ),
        )
        _record_task(
            connection,
            task_type="outline_restored",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("outline_ready", project_slug),
        )
        connection.commit()

    return OutlineItem(
        project_slug=project_slug,
        version=next_version,
        hook=str(outline_row["hook"]),
        outline_body=str(outline_row["outline_body"]),
        tone_profile_id=int(outline_row["tone_profile_id"]) if outline_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(outline_row["tone_profile_name"]) if outline_row["tone_profile_name"] is not None else None,
    )


def generate_draft(project_slug: str) -> DraftItem:
    return _generate_draft(project_slug)


def polish_draft(project_slug: str, instruction: str) -> DraftItem:
    return _generate_draft(project_slug, polish_instruction=instruction)


def _generate_draft(
    project_slug: str,
    *,
    review_comment: str | None = None,
    polish_instruction: str | None = None,
) -> DraftItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    with _get_connection() as connection:
        outline_row = connection.execute(
            """
            SELECT project_slug, version, hook, outline_body, tone_profile_id, tone_profile_name
            FROM outlines
            WHERE project_slug = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
        if not outline_row:
            raise HTTPException(status_code=409, detail="Outline not generated")

        latest_draft_row = None
        if polish_instruction:
            latest_draft_row = connection.execute(
                """
                SELECT project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name
                FROM drafts
                WHERE project_slug = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (project_slug,),
            ).fetchone()
            if not latest_draft_row:
                raise HTTPException(status_code=409, detail="Draft not generated")

        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM drafts WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        version = int(current["version"]) + 1
        ai_result = get_ai_generator().generate_draft(
            {
                "trend_title": project["trend_title"],
                "topic_title": project["topic_title"],
                "topic_angle": project["topic_angle"],
                "project_title": project["title"],
                "outline": {
                    "hook": outline_row["hook"],
                    "outline_body": outline_row["outline_body"],
                },
                "tone_profile": tone_profile.model_dump(),
                "review_comment": review_comment,
                "polish_instruction": polish_instruction,
                "draft": {
                    "title": latest_draft_row["title"],
                    "body_markdown": latest_draft_row["body_markdown"],
                }
                if polish_instruction and latest_draft_row
                else None,
            }
        )
        title = str(ai_result["title"])
        body_markdown = str(ai_result["body_markdown"])
        body_markdown, title = _maybe_compress_draft_output(
            project_slug=project_slug,
            tone_profile=tone_profile,
            title=title,
            body_markdown=body_markdown,
            project=project,
            outline_row=outline_row,
            review_comment=review_comment,
            generator=get_ai_generator(),
        )
        word_count = len(body_markdown)
        connection.execute(
            """
            INSERT INTO drafts (project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                outline_row["version"],
                version,
                title,
                body_markdown,
                word_count,
                tone_profile.id,
                tone_profile.name,
            ),
        )
        _record_task(
            connection,
            task_type="draft_polished" if polish_instruction else "draft_generation",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("draft_ready", project_slug),
        )
        connection.commit()

    return DraftItem(
        project_slug=project_slug,
        outline_version=int(outline_row["version"]),
        version=version,
        title=title,
        body_markdown=body_markdown,
        word_count=word_count,
        tone_profile_id=tone_profile.id,
        tone_profile_name=tone_profile.name,
    )


def _maybe_compress_draft_output(
    *,
    project_slug: str,
    tone_profile: ToneProfileItem,
    title: str,
    body_markdown: str,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    review_comment: str | None,
    generator,
) -> tuple[str, str]:
    target_word_count = tone_profile.target_word_count
    if target_word_count <= 0:
        return body_markdown, title

    max_allowed_length = int(target_word_count * 1.5)
    if len(body_markdown) <= max_allowed_length:
        return body_markdown, title

    compressed_result = generator.generate_draft(
        {
            "trend_title": project["trend_title"],
            "topic_title": project["topic_title"],
            "topic_angle": project["topic_angle"],
            "project_title": project["title"],
            "outline": {
                "hook": outline_row["hook"],
                "outline_body": outline_row["outline_body"],
            },
            "tone_profile": tone_profile.model_dump(),
            "review_comment": review_comment,
            "polish_instruction": "请在不改变核心观点和结构顺序的前提下，压缩这篇草稿，删除重复表达与重复场景，把正文控制回目标字数附近。",
            "draft": {
                "title": title,
                "body_markdown": body_markdown,
            },
        }
    )
    return str(compressed_result["body_markdown"]), str(compressed_result["title"])


def restore_draft_version(project_slug: str, version: int) -> DraftItem:
    with _get_connection() as connection:
        draft_row = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ? AND version = ?
            """,
            (project_slug, version),
        ).fetchone()
        if not draft_row:
            raise HTTPException(status_code=404, detail="Draft version not found")

        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM drafts WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        next_version = int(current["version"]) + 1
        connection.execute(
            """
            INSERT INTO drafts (project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                draft_row["outline_version"],
                next_version,
                draft_row["title"],
                draft_row["body_markdown"],
                draft_row["word_count"],
                draft_row["tone_profile_id"],
                draft_row["tone_profile_name"],
            ),
        )
        _record_task(
            connection,
            task_type="draft_restored",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("draft_ready", project_slug),
        )
        connection.commit()

    return DraftItem(
        project_slug=project_slug,
        outline_version=int(draft_row["outline_version"]),
        version=next_version,
        title=str(draft_row["title"]),
        body_markdown=str(draft_row["body_markdown"]),
        word_count=int(draft_row["word_count"]),
        tone_profile_id=int(draft_row["tone_profile_id"]) if draft_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(draft_row["tone_profile_name"]) if draft_row["tone_profile_name"] is not None else None,
    )


def _hydrate_asset_row(asset_row: sqlite3.Row) -> AssetItem:
    payload = dict(asset_row)
    payload["title_options"] = json.loads(payload["title_options"])
    return AssetItem(**payload)


def _hydrate_publish_package_row(package_row: sqlite3.Row) -> PublishPackageItem:
    payload = dict(package_row)
    payload["tags"] = json.loads(payload["tags"])
    payload["publish_checklist"] = json.loads(payload["publish_checklist"])
    return PublishPackageItem(**payload)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def submit_background_task(job_type: str, payload: dict[str, object]) -> BackgroundTaskSubmission:
    task_id = str(uuid.uuid4())
    created_at = _utc_now_iso()
    with _get_connection() as connection:
        connection.execute(
            """
            INSERT INTO background_tasks (task_id, job_type, status, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, job_type, "queued", json.dumps(payload, ensure_ascii=False), created_at),
        )
        _record_task(
            connection,
            task_type=job_type,
            status="queued",
            entity_slug=task_id,
            entity_type="batch",
            background_task_id=task_id,
        )
        connection.commit()

    worker = threading.Thread(
        target=_run_background_task,
        args=(task_id,),
        daemon=True,
    )
    worker.start()

    task = get_background_task(task_id)
    return BackgroundTaskSubmission(
        task_id=task.task_id,
        job_type=task.job_type,
        status=task.status,
        created_at=task.created_at,
    )


def get_background_task(task_id: str) -> BackgroundTaskDetail:
    with _get_connection() as connection:
        row = connection.execute(
            """
            SELECT task_id, job_type, status, payload, result, error, created_at, started_at, finished_at
            FROM background_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Background task not found")

    result = json.loads(str(row["result"])) if row["result"] else None
    return BackgroundTaskDetail(
        task_id=str(row["task_id"]),
        job_type=str(row["job_type"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row["started_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        error=str(row["error"]) if row["error"] else None,
        result=result,
    )


def _run_background_task(task_id: str) -> None:
    with _get_connection() as connection:
        row = connection.execute(
            "SELECT job_type, payload FROM background_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return
        started_at = _utc_now_iso()
        connection.execute(
            "UPDATE background_tasks SET status = ?, started_at = ? WHERE task_id = ?",
            ("running", started_at, task_id),
        )
        _update_background_task_log_status(
            connection,
            background_task_id=task_id,
            status="running",
        )
        connection.commit()
        job_type = str(row["job_type"])
        payload = json.loads(str(row["payload"]))

    try:
        if job_type == "batch_continue_projects":
            result = batch_continue_projects(payload.get("project_slugs"))
        elif job_type == "batch_generate_topics":
            result = batch_generate_topics(payload.get("trend_slugs"))
        elif job_type == "batch_generate_topics_from_tracked_articles":
            result = batch_generate_topics_from_tracked_articles(payload.get("article_slugs"))
        elif job_type == "batch_create_projects":
            result = batch_create_projects(payload.get("topic_slugs"))
        elif job_type == "regenerate_from_review":
            result = regenerate_from_review(str(payload["project_slug"]))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported background job type: {job_type}")

        with _get_connection() as connection:
            connection.execute(
                """
                UPDATE background_tasks
                SET status = ?, result = ?, finished_at = ?, error = NULL
                WHERE task_id = ?
                """,
                ("done", json.dumps(result.model_dump(), ensure_ascii=False), _utc_now_iso(), task_id),
            )
            _update_background_task_log_status(
                connection,
                background_task_id=task_id,
                status="done",
            )
            connection.commit()
    except HTTPException as exc:
        with _get_connection() as connection:
            connection.execute(
                """
                UPDATE background_tasks
                SET status = ?, error = ?, finished_at = ?
                WHERE task_id = ?
                """,
                ("failed", str(exc.detail), _utc_now_iso(), task_id),
            )
            _update_background_task_log_status(
                connection,
                background_task_id=task_id,
                status="failed",
            )
            connection.commit()
    except Exception as exc:
        with _get_connection() as connection:
            connection.execute(
                """
                UPDATE background_tasks
                SET status = ?, error = ?, finished_at = ?
                WHERE task_id = ?
                """,
                ("failed", str(exc), _utc_now_iso(), task_id),
            )
            _update_background_task_log_status(
                connection,
                background_task_id=task_id,
                status="failed",
            )
            connection.commit()


def _build_publish_checklist() -> list[str]:
    return [
        "核对标题与封面文案是否同一情绪主线",
        "确认摘要、标签、导语和正文结论一致",
        "检查配图、错别字和发布时间建议后再发布",
    ]


def generate_assets(project_slug: str) -> AssetItem:
    return _generate_assets(project_slug)


def restore_assets_version(project_slug: str, version: int) -> AssetItem:
    with _get_connection() as connection:
        assets_row = connection.execute(
            """
            SELECT
                project_slug,
                draft_version,
                version,
                title_options,
                cover_prompt,
                cover_copy,
                social_teaser,
                cover_image_path,
                cover_image_url,
                tone_profile_id,
                tone_profile_name
            FROM assets
            WHERE project_slug = ? AND version = ?
            """,
            (project_slug, version),
        ).fetchone()
        if not assets_row:
            raise HTTPException(status_code=404, detail="Assets version not found")

        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM assets WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        next_version = int(current["version"]) + 1
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, cover_prompt, cover_copy, social_teaser,
                cover_image_path, cover_image_url, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                assets_row["draft_version"],
                next_version,
                assets_row["title_options"],
                assets_row["cover_prompt"],
                assets_row["cover_copy"],
                assets_row["social_teaser"],
                assets_row["cover_image_path"],
                assets_row["cover_image_url"],
                assets_row["tone_profile_id"],
                assets_row["tone_profile_name"],
            ),
        )
        _record_task(
            connection,
            task_type="assets_restored",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("assets_ready", project_slug),
        )
        connection.commit()

    return AssetItem(
        project_slug=project_slug,
        draft_version=int(assets_row["draft_version"]),
        version=next_version,
        title_options=json.loads(str(assets_row["title_options"])),
        cover_prompt=str(assets_row["cover_prompt"]),
        cover_copy=str(assets_row["cover_copy"]),
        social_teaser=str(assets_row["social_teaser"]),
        cover_image_path=str(assets_row["cover_image_path"]),
        cover_image_url=str(assets_row["cover_image_url"]),
        tone_profile_id=int(assets_row["tone_profile_id"]) if assets_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(assets_row["tone_profile_name"]) if assets_row["tone_profile_name"] is not None else None,
    )


def _generate_assets(project_slug: str, *, review_comment: str | None = None) -> AssetItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    _ensure_generated_assets_dir()
    with _get_connection() as connection:
        draft_row = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
        if not draft_row:
            raise HTTPException(status_code=409, detail="Draft not generated")

        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM assets WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        version = int(current["version"]) + 1
        ai_result = get_ai_generator().generate_assets(
            {
                "trend_title": project["trend_title"],
                "topic_title": project["topic_title"],
                "topic_angle": project["topic_angle"],
                "project_title": project["title"],
                "draft": {
                    "title": draft_row["title"],
                    "body_markdown": draft_row["body_markdown"],
                },
                "tone_profile": tone_profile.model_dump(),
                "review_comment": review_comment,
            }
        )
        cover_filename = f"{project_slug}-assets-v{version}.png"
        cover_file_path = GENERATED_ASSETS_DIR / cover_filename
        cover_image_path = ""
        cover_image_url = ""
        try:
            cover_image_bytes = get_ai_generator().generate_cover_image(
                {
                    "project_slug": project_slug,
                    "project_title": project["title"],
                    "cover_prompt": ai_result["cover_prompt"],
                    "cover_copy": ai_result["cover_copy"],
                }
            )
            cover_file_path.write_bytes(cover_image_bytes)
            cover_image_path = str(cover_file_path)
            cover_image_url = f"/generated-assets/{cover_filename}"
        except Exception as exc:
            logger.warning(
                "Cover image generation failed for project %s: %s",
                project_slug,
                exc,
            )
            cover_image_path = ""
            cover_image_url = ""
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, cover_prompt, cover_copy, social_teaser,
                cover_image_path, cover_image_url, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                draft_row["version"],
                version,
                json.dumps(ai_result["title_options"], ensure_ascii=False),
                ai_result["cover_prompt"],
                ai_result["cover_copy"],
                ai_result["social_teaser"],
                cover_image_path,
                cover_image_url,
                tone_profile.id,
                tone_profile.name,
            ),
        )
        _record_task(
            connection,
            task_type="assets_generation",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("assets_ready", project_slug),
        )
        connection.commit()

    return AssetItem(
        project_slug=project_slug,
        draft_version=int(draft_row["version"]),
        version=version,
        title_options=list(ai_result["title_options"]),
        cover_prompt=str(ai_result["cover_prompt"]),
        cover_copy=str(ai_result["cover_copy"]),
        social_teaser=str(ai_result["social_teaser"]),
        cover_image_path=cover_image_path,
        cover_image_url=cover_image_url,
        tone_profile_id=tone_profile.id,
        tone_profile_name=tone_profile.name,
    )


def build_publish_package(project_slug: str) -> PublishPackageItem:
    return _build_publish_package(project_slug)


def _build_publish_package(project_slug: str, *, review_comment: str | None = None) -> PublishPackageItem:
    return _create_publish_package(project_slug, review_comment=review_comment)


def _create_publish_package(
    project_slug: str,
    *,
    review_comment: str | None = None,
    package_override: dict[str, object] | None = None,
) -> PublishPackageItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    effective_tone_profile_id = tone_profile.id
    effective_tone_profile_name = tone_profile.name
    if package_override and package_override.get("tone_profile_name") is not None:
        effective_tone_profile_id = int(package_override["tone_profile_id"]) if package_override.get("tone_profile_id") is not None else None
        effective_tone_profile_name = str(package_override["tone_profile_name"])
    _ensure_generated_assets_dir()
    with _get_connection() as connection:
        draft_row = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
        if not draft_row:
            raise HTTPException(status_code=409, detail="Draft not generated")

        assets_row = connection.execute(
            """
            SELECT
                project_slug,
                draft_version,
                version,
                title_options,
                cover_prompt,
                cover_copy,
                social_teaser,
                cover_image_path,
                cover_image_url,
                tone_profile_id,
                tone_profile_name
            FROM assets
            WHERE project_slug = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
        if not assets_row:
            raise HTTPException(status_code=409, detail="Assets not generated")
        publish_columns = _get_table_columns(connection, "publish_packages")
        draft_version = int(draft_row["version"])
        draft_title = str(draft_row["title"])
        draft_body_markdown = str(draft_row["body_markdown"])
        assets = _hydrate_asset_row(assets_row)

    ai_result = package_override or get_ai_generator().generate_publish_package(
        {
            "project_title": project["title"],
            "draft": {
                "title": draft_title,
                "body_markdown": draft_body_markdown,
            },
            "assets": assets.model_dump(),
            "tone_profile": tone_profile.model_dump(),
            "review_comment": review_comment,
        }
    )
    publish_checklist = list(package_override["publish_checklist"]) if package_override and "publish_checklist" in package_override else _build_publish_checklist()

    with _get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM publish_packages WHERE project_slug = ?",
            (project_slug,),
        ).fetchone()
        version = int(current["version"]) + 1
        markdown_filename = f"{project_slug}-publish-v{version}.md"
        manifest_filename = f"{project_slug}-publish-v{version}.json"
        markdown_path = GENERATED_ASSETS_DIR / markdown_filename
        manifest_path = GENERATED_ASSETS_DIR / manifest_filename
        markdown_url = f"/generated-assets/{markdown_filename}"
        manifest_url = f"/generated-assets/{manifest_filename}"
        markdown_body = _build_publish_markdown(
            project_title=project["title"],
            draft_title=draft_title,
            draft_body=draft_body_markdown,
            assets=assets,
            abstract=str(ai_result["abstract"]),
            tags=list(ai_result["tags"]),
            publish_checklist=publish_checklist,
            editor_note=str(ai_result["editor_note"]),
            tone_profile_name=effective_tone_profile_name,
        )
        manifest_body = {
            "project_slug": project_slug,
            "project_title": project["title"],
            "draft_version": draft_version,
            "assets_version": assets.version,
            "abstract": ai_result["abstract"],
            "tags": ai_result["tags"],
            "publish_checklist": publish_checklist,
            "editor_note": ai_result["editor_note"],
            "tone_profile_id": effective_tone_profile_id,
            "tone_profile_name": effective_tone_profile_name,
            "cover_image_url": assets.cover_image_url,
            "markdown_url": markdown_url,
        }
        markdown_path.write_text(markdown_body, encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest_body, ensure_ascii=False, indent=2), encoding="utf-8")
        payload: dict[str, object] = {
            "project_slug": project_slug,
            "draft_version": draft_version,
            "assets_version": assets.version,
            "version": version,
            "abstract": ai_result["abstract"],
            "tags": json.dumps(ai_result["tags"], ensure_ascii=False),
            "publish_checklist": json.dumps(publish_checklist, ensure_ascii=False),
            "editor_note": ai_result["editor_note"],
            "markdown_path": str(markdown_path),
            "markdown_url": markdown_url,
            "manifest_path": str(manifest_path),
            "manifest_url": manifest_url,
            "status": "ready",
            "review_comment": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "tone_profile_id": effective_tone_profile_id,
            "tone_profile_name": effective_tone_profile_name,
        }
        if "wechat_body" in publish_columns:
            payload["wechat_body"] = draft_body_markdown
        if "cover_title" in publish_columns:
            payload["cover_title"] = assets.title_options[0]
        if "checklist_markdown" in publish_columns:
            payload["checklist_markdown"] = "\n".join(f"- {item}" for item in publish_checklist)

        active_columns = [column for column in payload if column in publish_columns]
        placeholders = ", ".join("?" for _ in active_columns)
        column_sql = ", ".join(active_columns)
        values = tuple(payload[column] for column in active_columns)
        connection.execute(
            f"INSERT INTO publish_packages ({column_sql}) VALUES ({placeholders})",
            values,
        )
        _record_task(
            connection,
            task_type="publish_package_built",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            ("publish_ready", project_slug),
        )
        connection.commit()

    return PublishPackageItem(
        project_slug=project_slug,
        draft_version=draft_version,
        assets_version=assets.version,
        version=version,
        abstract=str(ai_result["abstract"]),
        tags=list(ai_result["tags"]),
        publish_checklist=publish_checklist,
        editor_note=str(ai_result["editor_note"]),
        markdown_path=str(markdown_path),
        markdown_url=markdown_url,
        manifest_path=str(manifest_path),
        manifest_url=manifest_url,
        status="ready",
        review_comment=None,
        reviewed_by=None,
        reviewed_at=None,
        tone_profile_id=effective_tone_profile_id,
        tone_profile_name=effective_tone_profile_name,
    )


def restore_publish_package_version(project_slug: str, version: int) -> PublishPackageItem:
    with _get_connection() as connection:
        package_row = connection.execute(
            """
            SELECT abstract, tags, publish_checklist, editor_note, tone_profile_id, tone_profile_name
            FROM publish_packages
            WHERE project_slug = ? AND version = ?
            """,
            (project_slug, version),
        ).fetchone()
        if not package_row:
            raise HTTPException(status_code=404, detail="Publish package version not found")

    return _create_publish_package(
        project_slug,
        package_override={
            "abstract": str(package_row["abstract"]),
            "tags": json.loads(str(package_row["tags"])),
            "publish_checklist": json.loads(str(package_row["publish_checklist"])),
            "editor_note": str(package_row["editor_note"]),
            "tone_profile_id": package_row["tone_profile_id"],
            "tone_profile_name": package_row["tone_profile_name"],
        },
    )


def approve_publish_package(project_slug: str, reviewer: str, comment: str) -> PublishPackageItem:
    return _review_publish_package(project_slug, reviewer=reviewer, comment=comment, status="approved", stage="published")


def request_publish_package_revision(project_slug: str, reviewer: str, comment: str) -> PublishPackageItem:
    return _review_publish_package(project_slug, reviewer=reviewer, comment=comment, status="needs_revision", stage="revision_requested")


def record_project_retro(project_slug: str, payload: ProjectRetroCreate) -> ProjectRetroItem:
    with _get_connection() as connection:
        project_row = connection.execute(
            """
            SELECT slug, stage
            FROM projects
            WHERE slug = ?
            """,
            (project_slug,),
        ).fetchone()
        if not project_row:
            raise HTTPException(status_code=404, detail="Project not found")
        if str(project_row["stage"]) != "published":
            raise HTTPException(status_code=409, detail="Project is not published yet")
        _, _, _, publish_package_row = _get_project_chain_rows(connection, project_slug)
        if not publish_package_row or str(publish_package_row["status"]) != "approved":
            raise HTTPException(status_code=409, detail="Project publish package is not approved yet")

        recorded_at = _utc_now_iso()
        connection.execute(
            """
            INSERT INTO project_retros (
                project_slug,
                publish_package_version,
                performance_rating,
                summary,
                wins,
                gaps,
                next_focus,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                int(publish_package_row["version"]),
                payload.performance_rating,
                payload.summary,
                json.dumps(payload.wins, ensure_ascii=False),
                json.dumps(payload.gaps, ensure_ascii=False),
                payload.next_focus,
                recorded_at,
            ),
        )
        _record_task(
            connection,
            task_type="project_retro_recorded",
            status="done",
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.commit()

    return ProjectRetroItem(
        project_slug=project_slug,
        performance_rating=payload.performance_rating,
        summary=payload.summary,
        wins=list(payload.wins),
        gaps=list(payload.gaps),
        next_focus=payload.next_focus,
        recorded_at=recorded_at,
    )


def regenerate_from_review(project_slug: str) -> PublishPackageItem:
    with _get_connection() as connection:
        package_row = connection.execute(
            """
            SELECT review_comment, status
            FROM publish_packages
            WHERE project_slug = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
        if not package_row:
            raise HTTPException(status_code=409, detail="Publish package not generated")
        if package_row["status"] != "needs_revision":
            raise HTTPException(status_code=409, detail="Latest publish package does not need revision")
        review_comment = str(package_row["review_comment"] or "").strip()
        if not review_comment:
            raise HTTPException(status_code=409, detail="Review comment is required for regeneration")

    _generate_draft(project_slug, review_comment=review_comment)
    _generate_assets(project_slug, review_comment=review_comment)
    return _build_publish_package(project_slug, review_comment=review_comment)


def _review_publish_package(
    project_slug: str,
    *,
    reviewer: str,
    comment: str,
    status: str,
    stage: str,
) -> PublishPackageItem:
    with _get_connection() as connection:
        package_row = connection.execute(
            """
            SELECT
                id,
                project_slug,
                draft_version,
                assets_version,
                version,
                abstract,
                tags,
                publish_checklist,
                editor_note,
                markdown_path,
                markdown_url,
                manifest_path,
                manifest_url,
                status,
                review_comment,
                reviewed_by,
                reviewed_at,
                tone_profile_id,
                tone_profile_name
            FROM publish_packages
            WHERE project_slug = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
        if not package_row:
            raise HTTPException(status_code=409, detail="Publish package not generated")

        reviewed_at = _utc_now_iso()
        connection.execute(
            """
            UPDATE publish_packages
            SET status = ?, review_comment = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (status, comment, reviewer, reviewed_at, package_row["id"]),
        )
        _record_task(
            connection,
            task_type="publish_review",
            status=status,
            entity_slug=project_slug,
            entity_type="project",
        )
        connection.execute(
            "UPDATE projects SET stage = ? WHERE slug = ?",
            (stage, project_slug),
        )
        connection.commit()

    payload = dict(package_row)
    payload["status"] = status
    payload["review_comment"] = comment
    payload["reviewed_by"] = reviewer
    payload["reviewed_at"] = reviewed_at
    payload["tags"] = json.loads(payload["tags"])
    payload["publish_checklist"] = json.loads(payload["publish_checklist"])
    return PublishPackageItem(**payload)


def _build_publish_markdown(
    *,
    project_title: str,
    draft_title: str,
    draft_body: str,
    assets: AssetItem,
    abstract: str,
    tags: list[str],
    publish_checklist: list[str],
    editor_note: str,
    tone_profile_name: str | None,
) -> str:
    tags_line = " / ".join(tags)
    title_options = "\n".join(f"- {title}" for title in assets.title_options)
    checklist_lines = "\n".join(f"- {item}" for item in publish_checklist)
    tone_profile_line = tone_profile_name or "未记录"
    cover_image_line = assets.cover_image_url or "未生成（图片服务暂时不可用）"
    return (
        f"# {draft_title}\n\n"
        f"> 项目：{project_title}\n"
        f"> 摘要：{abstract}\n"
        f"> 标签：{tags_line}\n"
        f"> 风格：{tone_profile_line}\n"
        f"> 封面图：{cover_image_line}\n\n"
        "## 标题备选\n"
        f"{title_options}\n\n"
        "## 封面文案\n"
        f"{assets.cover_copy}\n\n"
        "## 分发导语\n"
        f"{assets.social_teaser}\n\n"
        "## 编辑备注\n"
        f"{editor_note}\n\n"
        "## 发布前检查清单\n"
        f"{checklist_lines}\n\n"
        "## 正文\n\n"
        f"{draft_body}\n"
    )


def get_dashboard_summary() -> dict[str, object]:
    trends = list_trends()
    topics = list_topics()
    projects = list_projects()
    with _get_connection() as connection:
        recent_task_rows = connection.execute(
            """
            SELECT id, task_type, status, entity_slug, entity_type, created_at, background_task_id
            FROM task_logs
            ORDER BY id DESC
            LIMIT 3
            """
        ).fetchall()

    return {
        "today_trends": len(trends),
        "pending_topics": sum(1 for topic in topics if topic.status in {"drafting", "pending"}),
        "draft_ready_projects": sum(1 for project in projects if project.next_required_step is not None),
        "publish_ready_projects": sum(1 for project in projects if project.chain_status == "ready"),
        "recent_tasks": [dict(row) for row in recent_task_rows],
    }


def _continue_project_next_step(project_slug: str, next_required_step: str):
    if next_required_step == "generate_outline":
        return generate_outline(project_slug)
    if next_required_step == "generate_draft":
        return generate_draft(project_slug)
    if next_required_step == "generate_assets":
        return generate_assets(project_slug)
    if next_required_step == "build_publish_package":
        return build_publish_package(project_slug)
    if next_required_step == "regenerate_from_review":
        return regenerate_from_review(project_slug)
    raise HTTPException(status_code=400, detail=f"Unsupported next step: {next_required_step}")


def batch_continue_projects(project_slugs: list[str] | None = None) -> BatchContinueProjectsResponse:
    projects = list_projects()
    if project_slugs:
        projects_by_slug = {project.slug: project for project in projects}
        selected_projects = [projects_by_slug[slug] for slug in project_slugs if slug in projects_by_slug]
    else:
        selected_projects = projects
    results: list[BatchContinueProjectResult] = []
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for project in selected_projects:
        started_next_step = project.next_required_step
        if not started_next_step:
            skipped_count += 1
            results.append(
                BatchContinueProjectResult(
                    slug=project.slug,
                    status="skipped",
                    project=project,
                )
            )
            continue

        completed_steps: list[str] = []
        try:
            current_project = project
            while current_project.next_required_step:
                step = str(current_project.next_required_step)
                _continue_project_next_step(current_project.slug, step)
                completed_steps.append(step)
                current_project = get_project_detail(current_project.slug).project

            processed_count += 1
            results.append(
                BatchContinueProjectResult(
                    slug=project.slug,
                    status="done",
                    started_next_step=started_next_step,
                    completed_steps=completed_steps,
                    project=current_project,
                )
            )
        except HTTPException as exc:
            failed_count += 1
            results.append(
                BatchContinueProjectResult(
                    slug=project.slug,
                    status="failed",
                    started_next_step=started_next_step,
                    completed_steps=completed_steps,
                    error=str(exc.detail),
                    project=get_project_detail(project.slug).project,
                )
            )

    return BatchContinueProjectsResponse(
        requested_count=len(selected_projects),
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    )


def batch_generate_topics(trend_slugs: list[str] | None = None) -> BatchGenerateTopicsResponse:
    trends = list_trends()
    topics = list_topics()
    existing_trend_slugs = {
        topic.source_ref_slug
        for topic in topics
        if topic.source_type == "trend"
    }
    if trend_slugs:
        trends_by_slug = {trend.slug: trend for trend in trends}
        selected_trends = [trends_by_slug[slug] for slug in trend_slugs if slug in trends_by_slug]
    else:
        selected_trends = [
            trend
            for trend in trends
            if trend.status == "screening" and trend.slug not in existing_trend_slugs
        ]

    results: list[BatchGenerateTopicResult] = []
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for trend in selected_trends:
        try:
            topic = generate_topic_from_trend(trend.slug)
            processed_count += 1
            results.append(
                BatchGenerateTopicResult(
                    trend_slug=trend.slug,
                    status="done",
                    topic=topic.model_dump(),
                )
            )
        except HTTPException as exc:
            failed_count += 1
            results.append(
                BatchGenerateTopicResult(
                    trend_slug=trend.slug,
                    status="failed",
                    error=str(exc.detail),
                )
            )

    return BatchGenerateTopicsResponse(
        requested_count=len(selected_trends),
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    )


def batch_generate_topics_from_tracked_articles(
    article_slugs: list[str] | None = None,
) -> BatchGenerateTrackedArticleTopicsResponse:
    tracked_articles = list_tracked_articles()
    topics = list_topics()
    existing_article_slugs = {
        topic.source_ref_slug
        for topic in topics
        if topic.source_type == "tracked_article"
    }
    if article_slugs:
        articles_by_slug = {article.slug: article for article in tracked_articles}
        selected_articles = [articles_by_slug[slug] for slug in article_slugs if slug in articles_by_slug]
    else:
        selected_articles = [
            article
            for article in tracked_articles
            if article.slug not in existing_article_slugs
        ]

    results: list[BatchGenerateTrackedArticleTopicResult] = []
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for article in selected_articles:
        try:
            topic = generate_topic_from_tracked_article(article.slug)
            processed_count += 1
            results.append(
                BatchGenerateTrackedArticleTopicResult(
                    article_slug=article.slug,
                    status="done",
                    topic=topic.model_dump(),
                )
            )
        except HTTPException as exc:
            failed_count += 1
            results.append(
                BatchGenerateTrackedArticleTopicResult(
                    article_slug=article.slug,
                    status="failed",
                    error=str(exc.detail),
                )
            )

    return BatchGenerateTrackedArticleTopicsResponse(
        requested_count=len(selected_articles),
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    )


def batch_create_projects(topic_slugs: list[str] | None = None) -> BatchCreateProjectsResponse:
    topics = list_topics()
    projects = list_projects()
    existing_topic_slugs = {project.topic_slug for project in projects}
    if topic_slugs:
        topics_by_slug = {topic.slug: topic for topic in topics}
        selected_topics = [topics_by_slug[slug] for slug in topic_slugs if slug in topics_by_slug]
    else:
        selected_topics = [
            topic
            for topic in topics
            if topic.status in {"pending", "drafting"} and topic.slug not in existing_topic_slugs
        ]

    results: list[BatchCreateProjectResult] = []
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for topic in selected_topics:
        if topic.slug in existing_topic_slugs:
            skipped_count += 1
            results.append(
                BatchCreateProjectResult(
                    topic_slug=topic.slug,
                    status="skipped",
                    error="Project already exists",
                )
            )
            continue

        try:
            project = create_project_from_topic(
                topic.slug,
                ProjectCreate(
                    slug=f"{topic.slug}-project",
                    title=f"{topic.title} 项目",
                    owner="editorial",
                ),
            )
            processed_count += 1
            results.append(
                BatchCreateProjectResult(
                    topic_slug=topic.slug,
                    status="done",
                    project=project,
                )
            )
        except HTTPException as exc:
            failed_count += 1
            results.append(
                BatchCreateProjectResult(
                    topic_slug=topic.slug,
                    status="failed",
                    error=str(exc.detail),
                )
            )

    return BatchCreateProjectsResponse(
        requested_count=len(selected_topics),
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    )

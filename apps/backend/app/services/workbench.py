from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import html
import json
import logging
import re
import sqlite3
import threading
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from app.core.settings import settings
from app.schemas.background_tasks import BackgroundTaskDetail, BackgroundTaskSubmission, TaskLogEntry
from app.schemas.creative_workflow import (
    AdoptStrategyCardResponse,
    BenchmarkReferenceItem,
    CreativeReviewReportItem,
    DirectionalPolishLinkItem,
    DraftDiagnosisReportItem,
    ProblemBriefItem,
    PromoteCreativePatternAction,
    ReusablePatternItem,
    StrategyCardItem,
    StrategyPackageResult,
)
from app.services.ai_generator import get_default_generator
from app.services.ai_flavor import (
    build_ai_flavor_polish_instruction,
    count_short_long_cadence_pairs,
    count_repeated_paragraph_starter_run,
    evaluate_ai_flavor_risk,
    extract_explanatory_bridge_paragraphs,
    extract_bridging_summary_paragraphs,
    extract_embedded_banner_paragraphs,
    extract_growth_cliches,
    extract_generic_reflective_openers,
    extract_isolated_quote_paragraphs,
    extract_not_ab_skeletons,
    extract_orphaned_rebound_tails,
    extract_rebound_explainer_tails,
    extract_short_judgment_paragraphs,
)
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
from app.services.content_diagnosis import (
    build_diagnosis_polish_instruction,
    build_draft_diagnosis_report,
    build_reference_originality_report,
    resolve_diagnosis_objective_summary,
)
from app.services.creative_reports import build_creative_review_report
from app.services.creative_patterns import build_reusable_pattern_from_lesson, build_reusable_pattern_id
from app.services.creative_strategy import build_strategy_package
from app.schemas.tone_profiles import ToneProfileItem, ToneProfileReorder, ToneProfileUpsert
from app.services.prompt_templates import DEFAULT_DOMAIN_PROMPT_PACK, get_domain_prompt_pack
from app.services.prompt_templates import (
    _extract_tracked_article_body_cues,
    _extract_tracked_article_emotional_cues,
    _infer_tracked_article_pressure_guard,
    _has_broad_emotional_release_focus,
    _has_everyday_warmth_return_focus,
)
from app.services.tone_profile_presets import (
    DEFAULT_TONE_PROFILE_PRESET,
    list_builtin_tone_profile_presets,
)
from app.schemas.tracked_articles import (
    TrackedArticleBatchEnrichResponse,
    TrackedArticleBatchEnrichResult,
    TrackedArticleCreate,
    TrackedArticleItem,
)
from app.schemas.topics import TopicCreate, TopicCreateFromTrend, TopicItem, TopicUpdate
from app.schemas.trends import (
    TrendCreate,
    TrendFetchResponse,
    TrendFetchSourceResult,
    TrendImportResponse,
    TrendImportResult,
    TrendItem,
    TrendUpdate,
)
from app.services.wechat_mp_client import _normalize_wechat_text


logger = logging.getLogger(__name__)
DB_PATH = Path(settings.db_path)
GENERATED_ASSETS_DIR = Path(settings.generated_assets_dir)
DEFAULT_DB_PATH = Path("C:/tmp/gankaigc-wechat-workbench.db")
_COVER_PROMPT_LAYOUT_CONFLICT_PATTERN = re.compile(
    r"(?:9\s*[:：]\s*16|竖版|竖构图|竖幅|手机竖屏|海报竖版|适合竖版|竖屏)",
    re.IGNORECASE,
)
_PROJECT_VERSION_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_VERSION_LOCKS_GUARD = threading.Lock()
PIPELINE_BATCH_TASK_TYPES = (
    "batch_continue_projects",
    "batch_create_projects",
    "enrich_tracked_articles_metadata",
    "batch_generate_topics",
    "batch_generate_topics_from_tracked_articles",
)
DEFAULT_ASSETS_POLISH_INSTRUCTION = (
    "请执行原创增强精修，目标是把当前正文改到更像真实公众号作者手写稿，而不是AI顺滑稿。"
    "保留主题和结构主线，但重写大部分句子，不做同义替换式改写。"
    "开头继续从具体生活场景切入，减少标准模板式起笔。"
    "全文加强人的犹疑、停顿、转念和回看感，句子长短不要过于整齐。"
    "降低概念化总结腔，少用机械排比和高频套话，尤其压低“一”“很多”“真正”“不是……而是……”这类重复结构。"
    "不要写成鸡汤腔或网文腔，要保持当代中文公众号的自然表达。"
    "结尾收得安静、含蓄、有人味，不要喊话式总结。"
)
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
    "preset_key": DEFAULT_TONE_PROFILE_PRESET.preset_key,
    "name": DEFAULT_TONE_PROFILE_PRESET.name,
    "opening_style": DEFAULT_TONE_PROFILE_PRESET.opening_style,
    "paragraph_rhythm": DEFAULT_TONE_PROFILE_PRESET.paragraph_rhythm,
    "closing_style": DEFAULT_TONE_PROFILE_PRESET.closing_style,
    "forbidden_phrases": DEFAULT_TONE_PROFILE_PRESET.forbidden_phrases,
    "value_constraints": DEFAULT_TONE_PROFILE_PRESET.value_constraints,
    "target_word_count": DEFAULT_TONE_PROFILE_PRESET.target_word_count,
    "default_polish_instruction": DEFAULT_TONE_PROFILE_PRESET.default_polish_instruction,
}


@dataclass(frozen=True)
class _InitialDraftCandidateResult:
    title: str
    body_markdown: str
    reference_title: str
    reference_body_markdown: str
    cleanup_applied: bool
    cleanup_changed_steps: int


@dataclass(frozen=True)
class _DirectionalPolishContext:
    diagnosis_report_version: int | None
    objective_key: str
    objective_summary: str


def _apply_initial_draft_candidate_cleanups(
    *,
    title: str,
    body_markdown: str,
    source_type: str,
) -> tuple[str, int]:
    current_body = body_markdown
    changed_steps = 0

    cleanup_fns = [_collapse_short_judgment_residue]
    if source_type == "tracked_article":
        cleanup_fns.extend(
            (
                _collapse_time_chain_shell_residue,
                _collapse_embedded_banner_shell_residue,
                _collapse_explanatory_bridge_residue,
                _collapse_leading_short_long_cadence_residue,
                _collapse_short_long_cadence_residue,
                _soften_structural_ladder_residue,
                _soften_direct_address_lecture_residue,
                _collapse_over_segmented_shell_residue,
                _collapse_light_segmented_shell_residue,
                _soften_not_ab_residue,
                _strip_rebound_explainer_tail_residue,
                _strip_orphaned_rebound_tail_residue,
                _collapse_isolated_quote_example_residue,
                _soften_connector_residue,
            )
        )

    for cleanup_fn in cleanup_fns:
        collapsed_body = cleanup_fn(
            title=title,
            body_markdown=current_body,
        )
        if collapsed_body != current_body:
            changed_steps += 1
        current_body = collapsed_body

    return current_body, changed_steps


def _build_initial_draft_candidate_result(
    *,
    title: str,
    body_markdown: str,
    source_type: str,
) -> _InitialDraftCandidateResult:
    reference_title = title
    reference_body_markdown = body_markdown
    current_body, changed_steps = _apply_initial_draft_candidate_cleanups(
        title=title,
        body_markdown=body_markdown,
        source_type=source_type,
    )

    if source_type == "tracked_article":
        stabilized_body, _ = _prefer_less_smoothed_tracked_article_variant(
            preferred_title=title,
            preferred_markdown=current_body,
            fallback_title=reference_title,
            fallback_markdown=reference_body_markdown,
        )
        if stabilized_body == reference_body_markdown:
            current_body = reference_body_markdown
            changed_steps = 0

    return _InitialDraftCandidateResult(
        title=title,
        body_markdown=current_body,
        reference_title=reference_title,
        reference_body_markdown=reference_body_markdown,
        cleanup_applied=current_body != reference_body_markdown,
        cleanup_changed_steps=changed_steps,
    )


def _should_prefer_retried_candidate_after_cleanup_preview(
    *,
    current_title: str,
    current_markdown: str,
    retried_title: str,
    retried_markdown: str,
    source_type: str,
) -> bool:
    current_candidate = _build_initial_draft_candidate_result(
        title=current_title,
        body_markdown=current_markdown,
        source_type=source_type,
    )
    retried_candidate = _build_initial_draft_candidate_result(
        title=retried_title,
        body_markdown=retried_markdown,
        source_type=source_type,
    )
    return _should_prefer_retried_ai_flavor_candidate(
        current_title=current_candidate.title,
        current_markdown=current_candidate.body_markdown,
        retried_title=retried_candidate.title,
        retried_markdown=retried_candidate.body_markdown,
        current_reference_title=current_candidate.reference_title,
        current_reference_markdown=current_candidate.reference_body_markdown,
        retried_reference_title=retried_candidate.reference_title,
        retried_reference_markdown=retried_candidate.reference_body_markdown,
        current_cleanup_applied=current_candidate.cleanup_applied,
        current_cleanup_changed_steps=current_candidate.cleanup_changed_steps,
        retried_cleanup_applied=retried_candidate.cleanup_applied,
        retried_cleanup_changed_steps=retried_candidate.cleanup_changed_steps,
        source_type=source_type,
    )


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
    if "created_at" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN created_at TEXT DEFAULT NULL"
        )
    if "origin" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN origin TEXT DEFAULT NULL"
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
    if "created_at" not in columns:
        connection.execute(
            "ALTER TABLE outlines ADD COLUMN created_at TEXT DEFAULT NULL"
        )
    if "origin" not in columns:
        connection.execute(
            "ALTER TABLE outlines ADD COLUMN origin TEXT DEFAULT NULL"
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
    if "created_at" not in columns:
        connection.execute(
            "ALTER TABLE drafts ADD COLUMN created_at TEXT DEFAULT NULL"
        )
    if "origin" not in columns:
        connection.execute(
            "ALTER TABLE drafts ADD COLUMN origin TEXT DEFAULT NULL"
        )


def _ensure_tone_profiles_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "tone_profiles")
    if "preset_key" not in columns:
        connection.execute(
            "ALTER TABLE tone_profiles ADD COLUMN preset_key TEXT DEFAULT NULL"
        )
    connection.execute(
        "UPDATE tone_profiles SET preset_key = ? WHERE name = ? AND COALESCE(preset_key, '') = ''",
        (DEFAULT_TONE_PROFILE["preset_key"], DEFAULT_TONE_PROFILE["name"]),
    )
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
    if "default_polish_instruction" not in columns:
        connection.execute(
            "ALTER TABLE tone_profiles ADD COLUMN default_polish_instruction TEXT NOT NULL DEFAULT ''"
        )
        connection.execute(
            "UPDATE tone_profiles SET default_polish_instruction = ? WHERE COALESCE(default_polish_instruction, '') = ''",
            (DEFAULT_TONE_PROFILE["default_polish_instruction"],),
        )
    for preset in list_builtin_tone_profile_presets():
        existing = connection.execute(
            "SELECT id FROM tone_profiles WHERE preset_key = ? OR name = ? ORDER BY id ASC LIMIT 1",
            (preset.preset_key, preset.name),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE tone_profiles
                SET preset_key = ?,
                    name = ?,
                    opening_style = ?,
                    paragraph_rhythm = ?,
                    closing_style = ?,
                    forbidden_phrases = ?,
                    value_constraints = ?,
                    target_word_count = ?,
                    default_polish_instruction = ?
                WHERE id = ?
                """,
                (
                    preset.preset_key,
                    preset.name,
                    preset.opening_style,
                    preset.paragraph_rhythm,
                    preset.closing_style,
                    json.dumps(preset.forbidden_phrases, ensure_ascii=False),
                    preset.value_constraints,
                    preset.target_word_count,
                    preset.default_polish_instruction,
                    existing["id"],
                ),
            )
            continue
        next_sort_order = int(
            connection.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS sort_order FROM tone_profiles"
            ).fetchone()["sort_order"]
        ) + 1
        connection.execute(
            """
            INSERT INTO tone_profiles (
                preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count, default_polish_instruction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset.preset_key,
                1 if preset.is_active else 0,
                next_sort_order,
                preset.name,
                preset.opening_style,
                preset.paragraph_rhythm,
                preset.closing_style,
                json.dumps(preset.forbidden_phrases, ensure_ascii=False),
                preset.value_constraints,
                preset.target_word_count,
                preset.default_polish_instruction,
            ),
        )


def _ensure_projects_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "projects")
    if "preferred_tone_profile_id" not in columns:
        connection.execute(
            "ALTER TABLE projects ADD COLUMN preferred_tone_profile_id INTEGER DEFAULT NULL"
        )
    if "domain_pack_key" not in columns:
        connection.execute(
            "ALTER TABLE projects ADD COLUMN domain_pack_key TEXT DEFAULT NULL"
        )


def _ensure_trends_schema(connection: sqlite3.Connection) -> None:
    columns = _get_table_columns(connection, "trends")
    if "link" not in columns:
        connection.execute("ALTER TABLE trends ADD COLUMN link TEXT NOT NULL DEFAULT ''")
    if "summary" not in columns:
        connection.execute("ALTER TABLE trends ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
    if "published_at" not in columns:
        connection.execute("ALTER TABLE trends ADD COLUMN published_at TEXT DEFAULT NULL")
    if "fetched_at" not in columns:
        connection.execute("ALTER TABLE trends ADD COLUMN fetched_at TEXT DEFAULT NULL")


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
    if "created_at" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN created_at TEXT DEFAULT NULL"
        )
    if "origin" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN origin TEXT DEFAULT NULL"
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


def _ensure_creative_workflow_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS problem_briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            version INTEGER NOT NULL,
            source_mode TEXT NOT NULL,
            raw_goal TEXT NOT NULL,
            clarified_problem TEXT NOT NULL,
            observed_phenomenon TEXT NOT NULL DEFAULT '',
            writing_goal TEXT NOT NULL DEFAULT '',
            target_reader_situation TEXT NOT NULL,
            core_conflict TEXT NOT NULL,
            constraints TEXT NOT NULL DEFAULT '[]',
            feedback_entry TEXT NOT NULL DEFAULT '',
            problem_statement_markdown TEXT NOT NULL DEFAULT '',
            unknowns TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            created_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            version INTEGER NOT NULL,
            problem_brief_version INTEGER NOT NULL,
            reader_situation TEXT NOT NULL,
            point_of_view TEXT NOT NULL,
            conflict_frame TEXT NOT NULL,
            emotional_path TEXT NOT NULL,
            structure_mode TEXT NOT NULL DEFAULT '',
            opening_move TEXT NOT NULL DEFAULT '',
            body_shift TEXT NOT NULL DEFAULT '',
            ending_move TEXT NOT NULL DEFAULT '',
            expression_constraints TEXT NOT NULL DEFAULT '[]',
            divergence_axes TEXT NOT NULL DEFAULT '[]',
            execution_checklist TEXT NOT NULL DEFAULT '[]',
            benchmark_summary TEXT NOT NULL,
            strategy_markdown TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT DEFAULT NULL,
            adopted_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            strategy_version INTEGER NOT NULL,
            reference_kind TEXT NOT NULL,
            reference_label TEXT NOT NULL,
            reference_pointer TEXT NOT NULL,
            borrow_focus TEXT NOT NULL,
            avoid_focus TEXT NOT NULL,
            rationale TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnosis_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            draft_version INTEGER NOT NULL,
            version INTEGER NOT NULL,
            opening_strength TEXT NOT NULL,
            scene_specificity TEXT NOT NULL,
            viewpoint_clarity TEXT NOT NULL,
            progression_efficiency TEXT NOT NULL,
            ending_quality TEXT NOT NULL,
            ai_fingerprint_level TEXT NOT NULL,
            upstream_findings TEXT NOT NULL DEFAULT '[]',
            downstream_findings TEXT NOT NULL DEFAULT '[]',
            recommended_next_action TEXT NOT NULL,
            objective_summary TEXT NOT NULL DEFAULT '',
            recommended_polish_instruction TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS directional_polish_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            source_draft_version INTEGER NOT NULL,
            target_draft_version INTEGER NOT NULL,
            diagnosis_version INTEGER DEFAULT NULL,
            objective_key TEXT NOT NULL,
            objective_summary TEXT NOT NULL,
            created_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creative_review_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            version INTEGER NOT NULL,
            strategy_version INTEGER DEFAULT NULL,
            draft_version INTEGER DEFAULT NULL,
            summary_markdown TEXT NOT NULL,
            retained_lessons TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reusable_patterns (
            id TEXT PRIMARY KEY,
            source_project_slug TEXT NOT NULL,
            source_report_version INTEGER NOT NULL,
            pattern_type TEXT NOT NULL,
            title TEXT NOT NULL,
            intended_use TEXT NOT NULL,
            pattern_content TEXT NOT NULL,
            caution_notes TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT NULL
        )
        """
    )
    problem_brief_columns = _get_table_columns(connection, "problem_briefs")
    if "observed_phenomenon" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN observed_phenomenon TEXT NOT NULL DEFAULT ''"
        )
    if "writing_goal" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN writing_goal TEXT NOT NULL DEFAULT ''"
        )
    if "constraints" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN constraints TEXT NOT NULL DEFAULT '[]'"
        )
    if "feedback_entry" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN feedback_entry TEXT NOT NULL DEFAULT ''"
        )
    if "problem_statement_markdown" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN problem_statement_markdown TEXT NOT NULL DEFAULT ''"
        )
    strategy_card_columns = _get_table_columns(connection, "strategy_cards")
    if "opening_move" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN opening_move TEXT NOT NULL DEFAULT ''"
        )
    if "body_shift" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN body_shift TEXT NOT NULL DEFAULT ''"
        )
    if "ending_move" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN ending_move TEXT NOT NULL DEFAULT ''"
        )
    if "structure_mode" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN structure_mode TEXT NOT NULL DEFAULT ''"
        )
    if "divergence_axes" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN divergence_axes TEXT NOT NULL DEFAULT '[]'"
        )
    if "execution_checklist" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN execution_checklist TEXT NOT NULL DEFAULT '[]'"
        )
    if "strategy_markdown" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN strategy_markdown TEXT NOT NULL DEFAULT ''"
        )
    diagnosis_columns = _get_table_columns(connection, "diagnosis_reports")
    if "objective_summary" not in diagnosis_columns:
        connection.execute(
            "ALTER TABLE diagnosis_reports ADD COLUMN objective_summary TEXT NOT NULL DEFAULT ''"
        )
    if "recommended_polish_instruction" not in diagnosis_columns:
        connection.execute(
            "ALTER TABLE diagnosis_reports ADD COLUMN recommended_polish_instruction TEXT NOT NULL DEFAULT ''"
        )


def _ensure_tracked_articles_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_articles (
            slug TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL DEFAULT 'manual',
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            author TEXT NOT NULL,
            summary TEXT NOT NULL,
            body_markdown TEXT NOT NULL DEFAULT '',
            body_source TEXT NOT NULL DEFAULT 'missing',
            structure_notes TEXT NOT NULL,
            created_at TEXT DEFAULT NULL,
            tags TEXT NOT NULL
        )
        """
    )
    columns = _get_table_columns(connection, "tracked_articles")
    if "source_kind" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'manual'"
        )
    if "body_markdown" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN body_markdown TEXT NOT NULL DEFAULT ''"
        )
    if "body_source" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN body_source TEXT NOT NULL DEFAULT 'missing'"
        )
    if "created_at" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN created_at TEXT DEFAULT NULL"
        )


def _ensure_source_ingestion_runs_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_count INTEGER NOT NULL,
            created_count INTEGER NOT NULL,
            skipped_count INTEGER NOT NULL,
            failed_count INTEGER NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT NOT NULL
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


def _backfill_version_metadata_row(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    project_slug: str,
    version: int,
    created_at: str,
    origin: str,
) -> None:
    connection.execute(
        f"""
        UPDATE {table_name}
        SET
            created_at = COALESCE(created_at, ?),
            origin = COALESCE(origin, ?)
        WHERE
            project_slug = ?
            AND version = ?
            AND (created_at IS NULL OR origin IS NULL)
        """,
        (created_at, origin, project_slug, version),
    )


def _backfill_project_version_metadata(connection: sqlite3.Connection, project_slug: str) -> None:
    task_rows = connection.execute(
        """
        SELECT task_type, status, created_at
        FROM task_logs
        WHERE entity_slug = ? AND entity_type = 'project'
        ORDER BY id ASC
        """,
        (project_slug,),
    ).fetchall()
    if not task_rows:
        return

    version_counters = {
        "outlines": 0,
        "drafts": 0,
        "assets": 0,
        "publish_packages": 0,
    }
    pending_review_regeneration = False

    for task_row in task_rows:
        task_type = str(task_row["task_type"])
        status = str(task_row["status"])

        if task_type == "publish_review":
            pending_review_regeneration = status == "needs_revision"
            continue
        if task_type == "project_retro_recorded":
            continue

        table_name: str | None = None
        origin: str | None = None

        if task_type == "outline_generation":
            table_name = "outlines"
            origin = "generate"
        elif task_type == "outline_restored":
            table_name = "outlines"
            origin = "restore"
        elif task_type == "draft_generation":
            table_name = "drafts"
            origin = "review_regeneration" if pending_review_regeneration else "generate"
        elif task_type == "draft_polished":
            table_name = "drafts"
            origin = "polish"
        elif task_type == "draft_restored":
            table_name = "drafts"
            origin = "restore"
        elif task_type == "assets_generation":
            table_name = "assets"
            origin = "review_regeneration" if pending_review_regeneration else "generate"
        elif task_type == "assets_restored":
            table_name = "assets"
            origin = "restore"
        elif task_type == "publish_package_built":
            table_name = "publish_packages"
            origin = "review_regeneration" if pending_review_regeneration else "generate"
        elif task_type == "publish_package_restored":
            table_name = "publish_packages"
            origin = "restore"

        if not table_name or not origin:
            continue

        version_counters[table_name] += 1
        _backfill_version_metadata_row(
            connection,
            table_name=table_name,
            project_slug=project_slug,
            version=version_counters[table_name],
            created_at=str(task_row["created_at"]),
            origin=origin,
        )


def _backfill_version_metadata(connection: sqlite3.Connection) -> None:
    project_rows = connection.execute(
        """
        SELECT DISTINCT project_slug
        FROM (
            SELECT project_slug FROM outlines WHERE created_at IS NULL OR origin IS NULL
            UNION
            SELECT project_slug FROM drafts WHERE created_at IS NULL OR origin IS NULL
            UNION
            SELECT project_slug FROM assets WHERE created_at IS NULL OR origin IS NULL
            UNION
            SELECT project_slug FROM publish_packages WHERE created_at IS NULL OR origin IS NULL
        )
        """
    ).fetchall()
    for project_row in project_rows:
        _backfill_project_version_metadata(connection, str(project_row["project_slug"]))


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
                status TEXT NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                published_at TEXT DEFAULT NULL,
                fetched_at TEXT DEFAULT NULL
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
                preferred_tone_profile_id INTEGER DEFAULT NULL,
                domain_pack_key TEXT DEFAULT NULL
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
                outline_body TEXT NOT NULL,
                created_at TEXT DEFAULT NULL,
                origin TEXT DEFAULT NULL
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
                word_count INTEGER NOT NULL,
                created_at TEXT DEFAULT NULL,
                origin TEXT DEFAULT NULL
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
                cover_image_url TEXT NOT NULL,
                created_at TEXT DEFAULT NULL,
                origin TEXT DEFAULT NULL
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
                reviewed_at TEXT DEFAULT NULL,
                created_at TEXT DEFAULT NULL,
                origin TEXT DEFAULT NULL
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
                preset_key TEXT DEFAULT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                opening_style TEXT NOT NULL,
                paragraph_rhythm TEXT NOT NULL,
                closing_style TEXT NOT NULL,
                forbidden_phrases TEXT NOT NULL,
                value_constraints TEXT NOT NULL,
                target_word_count INTEGER NOT NULL,
                default_polish_instruction TEXT NOT NULL DEFAULT ''
            )
            """
        )
        _ensure_projects_schema(connection)
        _ensure_trends_schema(connection)
        _ensure_topics_schema(connection)
        _ensure_creative_workflow_schema(connection)
        _ensure_outlines_schema(connection)
        _ensure_drafts_schema(connection)
        _ensure_assets_schema(connection)
        _ensure_tone_profiles_schema(connection)
        _ensure_publish_packages_schema(connection)
        _ensure_project_retros_schema(connection)
        _ensure_tracked_articles_schema(connection)
        _ensure_source_ingestion_runs_schema(connection)
        _ensure_background_tasks_schema(connection)
        _ensure_task_logs_schema(connection)

        if reset:
            connection.execute("DELETE FROM trends")
            connection.execute("DELETE FROM topics")
            connection.execute("DELETE FROM projects")
            connection.execute("DELETE FROM problem_briefs")
            connection.execute("DELETE FROM strategy_cards")
            connection.execute("DELETE FROM benchmark_references")
            connection.execute("DELETE FROM diagnosis_reports")
            connection.execute("DELETE FROM directional_polish_links")
            connection.execute("DELETE FROM creative_review_reports")
            connection.execute("DELETE FROM reusable_patterns")
            connection.execute("DELETE FROM outlines")
            connection.execute("DELETE FROM drafts")
            connection.execute("DELETE FROM assets")
            connection.execute("DELETE FROM publish_packages")
            connection.execute("DELETE FROM project_retros")
            connection.execute("DELETE FROM tracked_articles")
            connection.execute("DELETE FROM source_ingestion_runs")
            connection.execute("DELETE FROM task_logs")
            connection.execute("DELETE FROM tone_profiles")
            connection.execute("DELETE FROM background_tasks")
            connection.execute("DELETE FROM app_meta")
            connection.commit()
            for asset_file in GENERATED_ASSETS_DIR.glob("*"):
                if asset_file.is_file():
                    asset_file.unlink()

        _backfill_version_metadata(connection)
        connection.commit()

        initialized = connection.execute("SELECT value FROM app_meta WHERE key = 'seeded'").fetchone()
        if initialized:
            return

        connection.executemany(
            """
            INSERT INTO trends (slug, title, source, heat_score, status, link, summary, published_at, fetched_at)
            VALUES (:slug, :title, :source, :heat_score, :status, :link, :summary, :published_at, :fetched_at)
            """,
            [
                {
                    **trend,
                    "link": "",
                    "summary": "",
                    "published_at": None,
                    "fetched_at": None,
                }
                for trend in TREND_SEEDS
            ],
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
        for sort_order, preset in enumerate(list_builtin_tone_profile_presets(), start=1):
            connection.execute(
                """
                INSERT INTO tone_profiles (
                    preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count, default_polish_instruction
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preset.preset_key,
                    1 if preset.is_active else 0,
                    sort_order,
                    preset.name,
                    preset.opening_style,
                    preset.paragraph_rhythm,
                    preset.closing_style,
                    json.dumps(preset.forbidden_phrases, ensure_ascii=False),
                    preset.value_constraints,
                    preset.target_word_count,
                    preset.default_polish_instruction,
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
            SELECT slug, title, source, heat_score, status, link, summary, published_at, fetched_at
            FROM trends
            ORDER BY COALESCE(datetime(published_at), datetime(fetched_at)) DESC, heat_score DESC, rowid DESC
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
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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
                preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count, default_polish_instruction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.preset_key,
                0,
                next_sort_order,
                payload.name,
                payload.opening_style,
                payload.paragraph_rhythm,
                payload.closing_style,
                json.dumps(payload.forbidden_phrases, ensure_ascii=False),
                payload.value_constraints,
                payload.target_word_count,
                payload.default_polish_instruction,
            ),
        )
        profile_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        row = connection.execute(
            """
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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
            SET preset_key = ?, name = ?, opening_style = ?, paragraph_rhythm = ?, closing_style = ?, forbidden_phrases = ?, value_constraints = ?, target_word_count = ?, default_polish_instruction = ?
            WHERE id = ?
            """,
            (
                payload.preset_key,
                payload.name,
                payload.opening_style,
                payload.paragraph_rhythm,
                payload.closing_style,
                json.dumps(payload.forbidden_phrases, ensure_ascii=False),
                payload.value_constraints,
                payload.target_word_count,
                payload.default_polish_instruction,
                profile_id,
            ),
        )
        connection.commit()
        row = connection.execute(
            """
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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


def get_project_domain_pack(project_row: sqlite3.Row) -> dict[str, object]:
    domain_pack_key = str(project_row["domain_pack_key"]).strip() if project_row["domain_pack_key"] is not None else ""
    pack = get_domain_prompt_pack(domain_pack_key) if domain_pack_key else None
    resolved = pack or DEFAULT_DOMAIN_PROMPT_PACK
    return {
        "key": resolved.key,
        "label": resolved.label,
        "audience": resolved.audience,
        "voice": resolved.voice,
        "constraints": resolved.constraints,
    }


def duplicate_tone_profile(profile_id: int) -> ToneProfileItem:
    with _get_connection() as connection:
        source_row = connection.execute(
            """
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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
                preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count, default_polish_instruction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                0,
                next_sort_order,
                f"{source_row['name']} 副本",
                source_row["opening_style"],
                source_row["paragraph_rhythm"],
                source_row["closing_style"],
                source_row["forbidden_phrases"],
                source_row["value_constraints"],
                source_row["target_word_count"],
                source_row["default_polish_instruction"],
            ),
        )
        duplicated_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()
        row = connection.execute(
            """
            SELECT id, preset_key, is_active, sort_order, name, opening_style, paragraph_rhythm, closing_style, forbidden_phrases, value_constraints, target_word_count
                , default_polish_instruction
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


def _hydrate_tracked_article_row(row: sqlite3.Row) -> TrackedArticleItem:
    summary = str(row["summary"])
    body_markdown = str(row["body_markdown"]) if "body_markdown" in row.keys() else ""
    body_source = str(row["body_source"]) if "body_source" in row.keys() else ("dom" if body_markdown else "missing")
    return TrackedArticleItem(
        slug=str(row["slug"]),
        source_kind=str(row["source_kind"]) if "source_kind" in row.keys() else "manual",
        source_name=_normalize_tracked_article_source_name(str(row["source_name"])),
        title=str(row["title"]),
        url=str(row["url"]),
        author=str(row["author"]),
        summary=_normalize_wechat_text(summary, preserve_paragraphs=False),
        body_markdown=_normalize_wechat_text(body_markdown, preserve_paragraphs=True) if body_markdown else "",
        body_source=body_source,
        structure_notes=str(row["structure_notes"]),
        created_at=str(row["created_at"]) if "created_at" in row.keys() and row["created_at"] is not None else None,
        tags=json.loads(str(row["tags"])),
    )


def _get_tracked_article_row_by_slug(connection: sqlite3.Connection, article_slug: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes, created_at, tags
        FROM tracked_articles
        WHERE slug = ?
        """,
        (article_slug,),
    ).fetchone()


def _find_tracked_article_by_url(connection: sqlite3.Connection, url: str) -> TrackedArticleItem | None:
    normalized_url = url.strip()
    if not normalized_url:
        return None
    row = connection.execute(
        """
        SELECT slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes, created_at, tags
        FROM tracked_articles
        WHERE url = ?
        """,
        (normalized_url,),
    ).fetchone()
    if not row:
        return None
    return _hydrate_tracked_article_row(row)


def _create_tracked_article_in_connection(
    connection: sqlite3.Connection,
    payload: TrackedArticleCreate,
    *,
    source_kind: str = "manual",
) -> TrackedArticleItem:
    source_name = _normalize_tracked_article_source_name(payload.source_name)
    created_at = _utc_now_iso()
    body_source = (
        payload.body_source
        if payload.body_source and payload.body_source != "missing"
        else ("manual" if payload.body_markdown else "missing")
    )
    connection.execute(
        """
        INSERT INTO tracked_articles (slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes, created_at, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.slug,
            source_kind,
            source_name,
            payload.title,
            payload.url.strip(),
            payload.author,
            payload.summary,
            payload.body_markdown,
            body_source,
            payload.structure_notes,
            created_at,
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
    return TrackedArticleItem(
        **{
            **payload.model_dump(),
            "source_kind": source_kind,
            "source_name": source_name,
            "url": payload.url.strip(),
            "body_source": body_source,
            "created_at": created_at,
        }
    )


def _summarize_source_ingestion(source_kind: str, created_count: int, skipped_count: int, failed_count: int) -> str:
    labels = {
        "trend_import": "热点导入",
        "trend_fetch": "实时热点抓取",
        "wechat_mp_import": "公众号文章导入",
    }
    prefix = labels.get(source_kind, source_kind)
    return f"{prefix}：新增 {created_count}，跳过 {skipped_count}，失败 {failed_count}"


def _resolve_source_ingestion_status(*, requested_count: int, created_count: int, skipped_count: int, failed_count: int) -> str:
    if requested_count == 0:
        return "done"
    if failed_count == requested_count:
        return "failed"
    if failed_count > 0:
        return "partial"
    if created_count == 0 and skipped_count > 0:
        return "skipped"
    return "done"


def _record_source_ingestion_run(
    connection: sqlite3.Connection,
    *,
    source_kind: str,
    requested_count: int,
    created_count: int,
    skipped_count: int,
    failed_count: int,
) -> int:
    created_at = _utc_now_iso()
    status = _resolve_source_ingestion_status(
        requested_count=requested_count,
        created_count=created_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )
    summary = _summarize_source_ingestion(source_kind, created_count, skipped_count, failed_count)
    connection.execute(
        """
        INSERT INTO source_ingestion_runs (
            source_kind, status, requested_count, created_count, skipped_count, failed_count, summary, created_at, completed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_kind,
            status,
            requested_count,
            created_count,
            skipped_count,
            failed_count,
            summary,
            created_at,
            created_at,
        ),
    )
    run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
    _record_task(
        connection,
        task_type=source_kind,
        status=status,
        entity_slug=str(run_id),
        entity_type="source_ingestion_run",
    )
    return run_id


def create_trend(payload: TrendCreate) -> TrendItem:
    with _get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO trends (slug, title, source, heat_score, status, link, summary, published_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.slug,
                    payload.title,
                    payload.source,
                    payload.heat_score,
                    payload.status,
                    payload.link,
                    payload.summary,
                    payload.published_at,
                    payload.fetched_at,
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


def _normalize_feed_text(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(raw))
    normalized = re.sub(r"\s+", " ", without_tags)
    return normalized.strip()


def _normalize_feed_datetime(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    iso_candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _find_child_text_by_local_names(node: ET.Element, local_names: set[str]) -> str:
    for child in list(node):
        tag_name = str(child.tag).split("}")[-1]
        if tag_name in local_names:
            text = "".join(child.itertext())
            if text.strip():
                return text.strip()
    return ""


def _fetch_trend_feed_xml(source_url: str) -> bytes:
    with httpx.Client(timeout=settings.trend_fetch_request_timeout_seconds) as client:
        response = client.get(source_url)
        response.raise_for_status()
        return response.content


def _get_trend_source_label(source_url: str, root: ET.Element) -> str:
    channel_title = root.findtext(".//channel/title")
    if channel_title and channel_title.strip():
        return channel_title.strip()
    atom_title = root.findtext(".//{*}title")
    if atom_title and atom_title.strip():
        return atom_title.strip()
    return urlparse(source_url).netloc or source_url


def _extract_trend_feed_items(root: ET.Element) -> list[dict[str, str | None]]:
    items: list[dict[str, str | None]] = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        summary = _normalize_feed_text(
            item.findtext("description")
            or _find_child_text_by_local_names(item, {"encoded", "summary", "content"})
        )
        published_at = _normalize_feed_datetime(
            item.findtext("pubDate")
            or item.findtext("published")
            or item.findtext("updated")
        )
        items.append(
            {
                "title": title,
                "link": link,
                "summary": summary,
                "published_at": published_at,
            }
        )

    if items:
        return items

    for entry in root.findall(".//{*}entry"):
        title = (entry.findtext("{*}title") or "").strip()
        if not title:
            continue
        link = ""
        link_node = entry.find("{*}link")
        if link_node is not None:
            link = str(link_node.attrib.get("href") or "").strip()
        summary = _normalize_feed_text(
            entry.findtext("{*}summary")
            or entry.findtext("{*}content")
            or _find_child_text_by_local_names(entry, {"summary", "content"})
        )
        published_at = _normalize_feed_datetime(
            entry.findtext("{*}published") or entry.findtext("{*}updated")
        )
        items.append(
            {
                "title": title,
                "link": link,
                "summary": summary,
                "published_at": published_at,
            }
        )

    return items


def fetch_trends_from_live_sources() -> dict[str, object]:
    source_urls = [url.strip() for url in settings.trend_feed_urls if url.strip()]
    if not source_urls:
        raise HTTPException(status_code=400, detail="No trend feed sources configured")

    existing_titles = {trend.title for trend in list_trends()}
    title_counts: dict[str, int] = {}
    results: list[TrendFetchSourceResult] = []
    created_count = 0
    skipped_count = 0
    failed_count = 0
    processed_source_count = 0

    for source_url in source_urls:
        try:
            root = ET.fromstring(_fetch_trend_feed_xml(source_url))
            source_label = _get_trend_source_label(source_url, root)
            feed_items = _extract_trend_feed_items(root)[: settings.trend_fetch_max_items_per_feed]
        except httpx.HTTPError as exc:
            failed_count += 1
            results.append(
                TrendFetchSourceResult(
                    source_url=source_url,
                    source_label=urlparse(source_url).netloc or source_url,
                    status="failed",
                    fetched_count=0,
                    created_count=0,
                    skipped_count=0,
                    failed_count=1,
                    error=str(exc),
                )
            )
            continue
        except ET.ParseError as exc:
            failed_count += 1
            results.append(
                TrendFetchSourceResult(
                    source_url=source_url,
                    source_label=urlparse(source_url).netloc or source_url,
                    status="failed",
                    fetched_count=0,
                    created_count=0,
                    skipped_count=0,
                    failed_count=1,
                    error=f"Malformed feed XML: {exc}",
                )
            )
            continue

        processed_source_count += 1
        source_created_count = 0
        source_skipped_count = 0
        source_failed_count = 0

        fetched_at = datetime.now(timezone.utc).isoformat()
        for item in feed_items:
            title = str(item["title"])
            if title in existing_titles:
                source_skipped_count += 1
                skipped_count += 1
                continue

            base_slug = _slugify_text(title)
            title_counts[base_slug] = title_counts.get(base_slug, 0) + 1
            slug = f"{base_slug}-{title_counts[base_slug]}"

            try:
                create_trend(
                    TrendCreate(
                        slug=slug,
                        title=title,
                        source=source_label,
                        heat_score=50,
                        status="screening",
                        link=str(item.get("link") or ""),
                        summary=str(item.get("summary") or ""),
                        published_at=str(item.get("published_at")) if item.get("published_at") else None,
                        fetched_at=fetched_at,
                    )
                )
                source_created_count += 1
                created_count += 1
                existing_titles.add(title)
            except HTTPException:
                source_failed_count += 1
                failed_count += 1

        results.append(
            TrendFetchSourceResult(
                source_url=source_url,
                source_label=source_label,
                status="done" if source_failed_count == 0 else "partial",
                fetched_count=len(feed_items),
                created_count=source_created_count,
                skipped_count=source_skipped_count,
                failed_count=source_failed_count,
            )
        )

    with _get_connection() as connection:
        run_id = _record_source_ingestion_run(
            connection,
            source_kind="trend_fetch",
            requested_count=len(source_urls),
            created_count=created_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
        connection.commit()

    return TrendFetchResponse(
        run_id=run_id,
        requested_source_count=len(source_urls),
        processed_source_count=processed_source_count,
        created_count=created_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    ).model_dump()


def import_trends(raw_text: str) -> TrendImportResponse:
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    results: list[TrendImportResult] = []
    created_count = 0
    skipped_count = 0
    failed_count = 0
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
            skipped_count += 1
            results.append(
                TrendImportResult(
                    line_number=line_number,
                    raw_line=raw_line,
                    status="skipped",
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
            failed_count += 1
            results.append(
                TrendImportResult(
                    line_number=line_number,
                    raw_line=raw_line,
                    status="failed",
                    error=str(exc.detail),
                )
            )

    with _get_connection() as connection:
        run_id = _record_source_ingestion_run(
            connection,
            source_kind="trend_import",
            requested_count=len(raw_lines),
            created_count=created_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
        connection.commit()

    return TrendImportResponse(
        run_id=run_id,
        requested_count=len(raw_lines),
        created_count=created_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    )


def update_trend(trend_slug: str, payload: TrendUpdate) -> TrendItem:
    with _get_connection() as connection:
        existing = connection.execute(
            """
            SELECT slug, source, link, summary, published_at, fetched_at
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
        link=str(existing["link"] or ""),
        summary=str(existing["summary"] or ""),
        published_at=str(existing["published_at"]) if existing["published_at"] else None,
        fetched_at=str(existing["fetched_at"]) if existing["fetched_at"] else None,
    )


def list_tracked_articles() -> list[TrackedArticleItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes, created_at, tags
            FROM tracked_articles
            ORDER BY rowid DESC
            """
        ).fetchall()
    return [_hydrate_tracked_article_row(row) for row in rows]


def create_tracked_article(payload: TrackedArticleCreate) -> TrackedArticleItem:
    with _get_connection() as connection:
        existing_by_url = _find_tracked_article_by_url(connection, payload.url)
        if existing_by_url:
            raise HTTPException(status_code=409, detail="Tracked article already exists for this URL")
        try:
            created = _create_tracked_article_in_connection(connection, payload, source_kind="manual")
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Tracked article slug already exists") from exc
    return created


def import_tracked_articles(
    payloads: list[TrackedArticleCreate],
    *,
    source_kind: str,
) -> dict[str, object]:
    created_items: list[TrackedArticleItem] = []
    results: list[dict[str, object]] = []
    skipped_count = 0
    failed_count = 0

    with _get_connection() as connection:
        for payload in payloads:
            existing_by_url = _find_tracked_article_by_url(connection, payload.url)
            if existing_by_url:
                skipped_count += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": "Tracked article already exists for this URL",
                        "article": existing_by_url.model_dump(),
                    }
                )
                continue

            try:
                created = _create_tracked_article_in_connection(connection, payload, source_kind=source_kind)
            except sqlite3.IntegrityError:
                failed_count += 1
                results.append(
                    {
                        "status": "failed",
                        "reason": "Tracked article slug already exists",
                        "article": None,
                    }
                )
                continue

            created_items.append(created)
            results.append(
                {
                    "status": "created",
                    "reason": None,
                    "article": created.model_dump(),
                }
            )

        run_id = _record_source_ingestion_run(
            connection,
            source_kind=source_kind,
            requested_count=len(payloads),
            created_count=len(created_items),
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
        connection.commit()

    return {
        "run_id": run_id,
        "requested_count": len(payloads),
        "imported_count": len(created_items),
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "created": [item.model_dump() for item in created_items],
        "results": results,
    }


def refresh_tracked_article_body(
    article_slug: str,
    *,
    body_markdown: str,
    body_source: str,
) -> TrackedArticleItem:
    with _get_connection() as connection:
        row = _get_tracked_article_row_by_slug(connection, article_slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Tracked article not found")

        connection.execute(
            """
            UPDATE tracked_articles
            SET body_markdown = ?, body_source = ?
            WHERE slug = ?
            """,
            (body_markdown, body_source, article_slug),
        )
        connection.commit()

        refreshed_row = _get_tracked_article_row_by_slug(connection, article_slug)
        if refreshed_row is None:
            raise HTTPException(status_code=404, detail="Tracked article not found")
    return _hydrate_tracked_article_row(refreshed_row)


def _normalize_tracked_article_tags(tags: object) -> list[str]:
    if not isinstance(tags, list):
        return []

    normalized: list[str] = []
    for tag in tags:
        value = str(tag).strip()
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


_ABSTRACT_PRESSURE_TOPIC_ANGLE_TOKENS = (
    "自我调度",
    "很多女性",
    "很多人",
    "怎样",
    "如何",
    "持续撤掉",
    "直到身体和情绪",
    "体面之间",
    "自我照料",
    "生活顺序",
    "身体和情绪",
    "一起追债",
)

_ABSTRACT_PRESSURE_TOPIC_TITLE_TOKENS = (
    "开始怀念",
    "病本身",
    "复查一再改期的人",
    "总把自己",
    "总把休息",
    "排在最后",
    "排到最后",
    "放最后",
    "迟早",
    "怀念那个",
    "只是有点累",
    "失序的生活",
    "善待自己",
    "好好爱自己",
    "人生",
    "遗憾",
    "拖得太晚",
    "内耗",
    "生活排序",
    "自我照料",
    "自我关照",
)

_PRESSURE_TOPIC_TITLE_INTERFACE_TOKENS = (
    "体检",
    "复查",
    "尿毒症",
    "褥疮",
    "透析",
    "轮椅",
    "没力气",
    "不想回",
    "改期",
    "往后推",
    "往后改",
    "钝",
    "吃饭",
    "睡",
    "提醒",
    "信号",
)
_ABSTRACT_EMOTIONAL_RELEASE_RELATIONSHIP_TOKENS = (
    "坏关系",
    "感情诚意",
    "沉没成本",
    "输不起",
    "离不开",
    "关系",
    "再坚持一下",
    "止损",
)
_ABSTRACT_EVERYDAY_WARMTH_PRESSURE_TOKENS = (
    "体检",
    "复查",
    "身体提醒",
    "身体信号",
    "求救信号",
    "排在待办清单最后",
    "排在最后",
    "压后",
    "追债",
    "自我照料",
)


def _compact_pressure_topic_cue(sentence: str) -> str:
    compact = re.sub(r"\s+", "", sentence).strip("。！？!?；;")
    if not compact:
        return ""
    compact = re.sub(r"^(后来|几年后|又过了一些年|又过了几年|又过些年|前两年|当初|刚得|要|便|又开始|开始)", "", compact)
    compact = re.sub(r"^(得了|长了)", "", compact)
    compact = re.sub(r"^(又|再|便)", "", compact)
    compact = compact.lstrip("，,、")
    return compact


def _should_rewrite_pressure_topic_angle(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _infer_tracked_article_pressure_guard(payload) != "internal_pressure":
        return False
    angle = str(ai_result.get("angle") or "").strip()
    if not angle:
        return False
    if any(token in angle for token in ("体检", "尿毒症", "褥疮", "透析", "轮椅", "身体提醒", "身体信号", "没回", "改期")):
        return False
    return any(token in angle for token in _ABSTRACT_PRESSURE_TOPIC_ANGLE_TOKENS)


def _should_rewrite_pressure_topic_title(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _infer_tracked_article_pressure_guard(payload) != "internal_pressure":
        return False
    title = str(ai_result.get("title") or "").strip()
    if not title:
        return False
    if any(token in title for token in _ABSTRACT_PRESSURE_TOPIC_TITLE_TOKENS):
        return True
    if any(token in title for token in _PRESSURE_TOPIC_TITLE_INTERFACE_TOKENS):
        return False
    return False


def _summarize_pressure_topic_title_cue(sentence: str) -> str:
    compact = _compact_pressure_topic_cue(sentence)
    if not compact:
        return ""
    if "透析" in compact:
        return "透析"
    if "尿毒症" in compact:
        return "尿毒症"
    if "长褥疮" in compact:
        return "长褥疮"
    if "轮椅" in compact:
        return "坐上轮椅"
    if "体检" in compact and any(token in compact for token in ("改", "推", "拖", "往后")):
        return "体检一改再改"
    if "复查" in compact and any(token in compact for token in ("改", "推", "拖", "往后")):
        return "复查一拖再拖"
    if "回家吃饭" in compact and any(token in compact for token in ("改", "推", "拖", "往后")):
        return "回家吃饭也往后推"
    if "越来越钝" in compact or "变钝" in compact:
        return "整个人越来越钝"
    if "不想回" in compact or "懒得回" in compact:
        return "连消息都不想回"
    if "没力气" in compact:
        return "已经没力气回应"
    if "睡" in compact and any(token in compact for token in ("改", "推", "拖", "晚", "欠")):
        return "连睡觉都往后拖"
    return compact[:10]


def _select_pressure_topic_rewrite_cues(body_cues: list[str]) -> list[str]:
    summarized_cues: list[str] = []
    for cue in body_cues:
        summarized = _summarize_pressure_topic_title_cue(cue)
        if summarized and summarized not in summarized_cues:
            summarized_cues.append(summarized)
    if len(summarized_cues) <= 1:
        return summarized_cues
    return [summarized_cues[0], summarized_cues[-1]]


def _rewrite_pressure_topic_title(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> str:
    original_title = str(ai_result.get("title") or "").strip()
    body_cues = _extract_tracked_article_body_cues(payload)
    if not body_cues:
        return original_title

    summarized_cues = _select_pressure_topic_rewrite_cues(body_cues)
    if not summarized_cues:
        return original_title

    primary = summarized_cues[0]
    secondary = summarized_cues[1] if len(summarized_cues) > 1 else ""
    if primary and secondary:
        if primary == "复查一拖再拖":
            return "那张“建议复查”的单子，被你压了多久"
        if primary == "体检一改再改":
            return "那次体检被你改到第几回了"
        if primary == "回家吃饭也往后推":
            return "连回家吃饭都在往后推的时候，人已经累成什么样了"
        if primary == "连睡觉都往后拖":
            return "连睡觉都要往后拖的时候，人已经撑到哪一步了"
        if any(token in {primary, secondary} for token in ("透析", "尿毒症", "长褥疮", "坐上轮椅")):
            return f"从{primary}到{secondary}，身体到底替你扛了多少"
        if secondary in ("整个人越来越钝", "连消息都不想回", "已经没力气回应"):
            return f"{primary}之后，人为什么会变成{secondary}"
        return f"{primary}之后，很多事为什么会越拖越重"
    if primary:
        if any(token in primary for token in ("体检", "复查", "透析", "尿毒症", "褥疮", "轮椅")):
            if primary == "复查一拖再拖":
                return "那张“建议复查”的单子，被你压了多久"
            if primary == "体检一改再改":
                return "那次体检被你改到第几回了"
            return f"当{primary}开始反复出现时，你到底还想往后拖多久"
        if any(token in primary for token in ("不想回", "吃饭", "睡", "没力气", "越来越钝")):
            return f"当{primary}时，人已经在失去什么"
        return f"{primary}开始冒头以后，很多代价就已经上路了"
    return original_title


def _rewrite_pressure_topic_angle(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    title = str(ai_result.get("title") or "").strip()
    body_cues = _extract_tracked_article_body_cues(payload)
    if not body_cues:
        return {"title": title, "angle": str(ai_result.get("angle") or "").strip()}

    summarized_cues = _select_pressure_topic_rewrite_cues(body_cues)
    primary = summarized_cues[0] if summarized_cues else ""
    secondary = summarized_cues[1] if len(summarized_cues) > 1 else ""
    if primary and secondary:
        angle = f"从{primary}一路拖到{secondary}的身体代价链切入，写人为什么总把自己的求救信号继续压后，不先抛人生答案。"
    elif primary:
        angle = f"从{primary}这种已经冒头的身体代价切入，写人为什么总把这样的求救信号继续压后，不先抛人生答案。"
    else:
        angle = str(ai_result.get("angle") or "").strip()
    return {"title": title, "angle": angle}


def _should_rewrite_emotional_release_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if _has_everyday_warmth_return_focus(payload):
        return False
    if not _has_broad_emotional_release_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    return any(token in combined for token in _ABSTRACT_EMOTIONAL_RELEASE_RELATIONSHIP_TOKENS)


def _rewrite_emotional_release_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    cues = _extract_tracked_article_emotional_cues(payload, max_items=3)
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not cues:
        return {"title": title, "angle": angle}

    joined_cues = " ".join(cues)
    if "幸福" in joined_cues and any(token in joined_cues for token in ("放下", "不再强求", "强求")):
        new_title = "你以为幸福是得到，后来才懂有些幸福叫放下"
    elif any(token in joined_cues for token in ("不再强求", "强求", "放手")):
        new_title = "人最容易错过的幸福，往往藏在不再强求以后"
    else:
        new_title = title

    if any(token in joined_cues for token in ("珍惜", "知足", "拥有")):
        new_angle = "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。"
    else:
        new_angle = "从人为什么总在得不到的东西上反复拉扯切入，写强求怎样一点点耗尽自己，以及放下为什么反而让人更接近真正的幸福。"
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_everyday_warmth_return_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_everyday_warmth_return_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    return any(token in combined for token in _ABSTRACT_EVERYDAY_WARMTH_PRESSURE_TOKENS)


def _rewrite_everyday_warmth_return_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()

    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if any(token in corpus for token in ("宏大叙事", "微小", "细碎", "平淡的日常")):
        new_title = "很多“大事”最后都会祛魅，留下你的反而是这些小事"
    elif any(token in corpus for token in ("最重要的事", "做大事", "大事")):
        new_title = "原来一生里最重要的，常常都是那些不起眼的小事"
    elif any(token in corpus for token in ("人间烟火", "陪在爱的人身边")):
        new_title = "人这一生，最后会被什么真正留下来"
    else:
        new_title = "原来一生里最重要的，常常都是那些不起眼的小事"

    if any(token in corpus for token in ("晚饭", "接孩子", "父母", "爱人", "一家老小", "晚安")):
        new_angle = "从人为什么总把重要感押在更大的目标上切入，写我们往前赶了很久以后，才怎样被一顿晚饭、一次接孩子、几句家常话重新提醒：真正托住生活的，往往是那些最普通的陪伴。"
    else:
        new_angle = "从成就叙事为什么总会在某个阶段突然祛魅切入，写人慢下来以后，怎样重新看见那些不起眼却最能托住生活的小事和陪伴。"
    return {"title": new_title, "angle": new_angle}


def enrich_tracked_article_metadata(article_slug: str) -> TrackedArticleItem:
    with _get_connection() as connection:
        row = _get_tracked_article_row_by_slug(connection, article_slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Tracked article not found")

        article = _hydrate_tracked_article_row(row)
        ai_result = get_ai_generator().generate_tracked_article_metadata(
            {
                "source_kind": article.source_kind,
                "source_name": article.source_name,
                "article_title": article.title,
                "article_url": article.url,
                "author": article.author,
                "summary": article.summary,
                "body_markdown": article.body_markdown,
                "body_source": article.body_source,
                "structure_notes": article.structure_notes,
                "tags": article.tags,
            }
        )

        updated_author = article.author.strip() or str(ai_result.get("author") or "").strip()
        updated_summary = str(ai_result.get("summary") or "").strip() or article.summary
        updated_structure_notes = str(ai_result.get("structure_notes") or "").strip() or article.structure_notes
        updated_tags = _normalize_tracked_article_tags(ai_result.get("tags")) or article.tags

        connection.execute(
            """
            UPDATE tracked_articles
            SET author = ?, summary = ?, structure_notes = ?, tags = ?
            WHERE slug = ?
            """,
            (
                updated_author,
                updated_summary,
                updated_structure_notes,
                json.dumps(updated_tags, ensure_ascii=False),
                article_slug,
            ),
        )
        _record_task(
            connection,
            task_type="tracked_article_metadata_enriched",
            status="done",
            entity_slug=article_slug,
            entity_type="tracked_article",
        )
        connection.commit()

        refreshed_row = _get_tracked_article_row_by_slug(connection, article_slug)
        if refreshed_row is None:
            raise HTTPException(status_code=404, detail="Tracked article not found")
    return _hydrate_tracked_article_row(refreshed_row)


def batch_enrich_tracked_articles_metadata(article_slugs: list[str] | None = None) -> TrackedArticleBatchEnrichResponse:
    requested_slugs = [str(slug).strip() for slug in (article_slugs or []) if str(slug).strip()]
    processed_count = 0
    skipped_count = 0
    failed_count = 0
    results: list[TrackedArticleBatchEnrichResult] = []

    for article_slug in requested_slugs:
        try:
            article = enrich_tracked_article_metadata(article_slug)
            processed_count += 1
            results.append(
                TrackedArticleBatchEnrichResult(
                    article_slug=article_slug,
                    status="done",
                    article=article,
                )
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                skipped_count += 1
                results.append(
                    TrackedArticleBatchEnrichResult(
                        article_slug=article_slug,
                        status="skipped",
                        error=str(exc.detail),
                    )
                )
                continue
            failed_count += 1
            results.append(
                TrackedArticleBatchEnrichResult(
                    article_slug=article_slug,
                    status="failed",
                    error=str(exc.detail),
                )
            )
        except Exception as exc:
            failed_count += 1
            results.append(
                TrackedArticleBatchEnrichResult(
                    article_slug=article_slug,
                    status="failed",
                    error=str(exc),
                )
            )

    return TrackedArticleBatchEnrichResponse(
        requested_count=len(requested_slugs),
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        results=results,
    )


def list_topics() -> list[TopicItem]:
    with _get_connection() as connection:
        rows = connection.execute(
            """
            SELECT slug, trend_slug, source_type, source_ref_slug, title, angle, status
            FROM topics
            ORDER BY rowid DESC
            """
        ).fetchall()
    return [_hydrate_topic_row(row) for row in rows]


def _hydrate_topic_row(row: sqlite3.Row) -> TopicItem:
    trend_slug = row["trend_slug"]
    return TopicItem(
        slug=str(row["slug"]),
        trend_slug=str(trend_slug) if trend_slug not in (None, "") else None,
        source_type=str(row["source_type"]),
        source_ref_slug=str(row["source_ref_slug"]),
        title=str(row["title"]),
        angle=str(row["angle"]),
        status=str(row["status"]),
    )


def create_manual_topic(payload: TopicCreate) -> TopicItem:
    with _get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (payload.slug, "", "manual", payload.slug, payload.title, payload.angle, "pending"),
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

    return _hydrate_topic_row(
        {
            "slug": payload.slug,
            "trend_slug": "",
            "source_type": "manual",
            "source_ref_slug": payload.slug,
            "title": payload.title,
            "angle": payload.angle,
            "status": "pending",
        }
    )


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
    return _hydrate_topic_row(
        {
            "slug": payload.slug,
            "trend_slug": trend_slug,
            "source_type": "trend",
            "source_ref_slug": trend_slug,
            "title": payload.title,
            "angle": payload.angle,
            "status": "pending",
        }
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
    return _hydrate_topic_row(
        {
            "slug": payload.slug,
            "trend_slug": article_slug,
            "source_type": "tracked_article",
            "source_ref_slug": article_slug,
            "title": payload.title,
            "angle": payload.angle,
            "status": "pending",
        }
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
    return _hydrate_topic_row(
        {
            "slug": topic_slug,
            "trend_slug": existing["trend_slug"],
            "source_type": existing["source_type"],
            "source_ref_slug": existing["source_ref_slug"],
            "title": payload.title,
            "angle": payload.angle,
            "status": payload.status,
        }
    )


def generate_topic_from_trend(trend_slug: str) -> TopicItem:
    tone_profile = get_active_tone_profile()
    with _get_connection() as connection:
        trend = connection.execute(
            """
            SELECT slug, title, source, heat_score, status, link, summary, published_at, fetched_at
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
                "link": trend["link"],
                "summary": trend["summary"],
                "published_at": trend["published_at"],
                "fetched_at": trend["fetched_at"],
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

    return _hydrate_topic_row(
        {
            "slug": slug,
            "trend_slug": trend_slug,
            "source_type": "trend",
            "source_ref_slug": trend_slug,
            "title": str(ai_result["title"]),
            "angle": str(ai_result["angle"]),
            "status": "pending",
        }
    )


def generate_topic_from_tracked_article(article_slug: str) -> TopicItem:
    tone_profile = get_active_tone_profile()
    with _get_connection() as connection:
        article = connection.execute(
            """
            SELECT slug, source_kind, source_name, title, author, summary, body_markdown, structure_notes, created_at, tags
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
        topic_payload = {
            "source_type": "tracked_article",
            "source_ref_slug": article["slug"],
            "source_name": _normalize_tracked_article_source_name(str(article["source_name"])),
            "article_title": article["title"],
            "author": article["author"],
            "summary": article["summary"],
            "body_markdown": article["body_markdown"],
            "structure_notes": article["structure_notes"],
            "tags": json.loads(str(article["tags"])),
            "tone_profile": tone_profile.model_dump(),
        }
        ai_result = get_ai_generator().generate_topic(topic_payload)
        if _should_rewrite_pressure_topic_title(topic_payload, ai_result):
            ai_result = {
                "title": _rewrite_pressure_topic_title(topic_payload, ai_result),
                "angle": str(ai_result.get("angle") or "").strip(),
            }
        if _should_rewrite_pressure_topic_angle(topic_payload, ai_result):
            ai_result = _rewrite_pressure_topic_angle(topic_payload, ai_result)
        if _should_rewrite_everyday_warmth_return_topic(topic_payload, ai_result):
            ai_result = _rewrite_everyday_warmth_return_topic(topic_payload, ai_result)
        if _should_rewrite_emotional_release_topic(topic_payload, ai_result):
            ai_result = _rewrite_emotional_release_topic(topic_payload, ai_result)
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

    return _hydrate_topic_row(
        {
            "slug": slug,
            "trend_slug": article_slug,
            "source_type": "tracked_article",
            "source_ref_slug": article_slug,
            "title": str(ai_result["title"]),
            "angle": str(ai_result["angle"]),
            "status": "pending",
        }
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
                p.domain_pack_key,
                tp.name AS preferred_tone_profile_name,
                t.source_type
            FROM projects p
            LEFT JOIN tone_profiles tp ON tp.id = p.preferred_tone_profile_id
            JOIN topics t ON t.slug = p.topic_slug
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

        if payload.domain_pack_key is not None and get_domain_prompt_pack(payload.domain_pack_key) is None:
            raise HTTPException(status_code=404, detail="Domain pack not found")

        try:
            connection.execute(
                """
                INSERT INTO projects (slug, topic_slug, title, stage, owner, preferred_tone_profile_id, domain_pack_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.slug,
                    topic_slug,
                    payload.title,
                    "outline",
                    payload.owner,
                    payload.preferred_tone_profile_id,
                    payload.domain_pack_key,
                ),
            )
            connection.execute(
                "UPDATE topics SET status = ? WHERE slug = ?",
                ("drafting", topic_slug),
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
            SELECT slug, topic_slug, title, stage, owner, preferred_tone_profile_id, domain_pack_key
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

        if payload.domain_pack_key is not None and get_domain_prompt_pack(payload.domain_pack_key) is None:
            raise HTTPException(status_code=404, detail="Domain pack not found")

        next_preferred_tone_profile_id = existing["preferred_tone_profile_id"]
        if "preferred_tone_profile_id" in payload.model_fields_set:
            next_preferred_tone_profile_id = payload.preferred_tone_profile_id

        next_domain_pack_key = existing["domain_pack_key"]
        if "domain_pack_key" in payload.model_fields_set:
            next_domain_pack_key = payload.domain_pack_key

        connection.execute(
            "UPDATE projects SET stage = ?, preferred_tone_profile_id = ?, domain_pack_key = ? WHERE slug = ?",
            (payload.stage, next_preferred_tone_profile_id, next_domain_pack_key, project_slug),
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
                p.domain_pack_key,
                tp.name AS preferred_tone_profile_name,
                t.source_type
            FROM projects p
            LEFT JOIN tone_profiles tp ON tp.id = p.preferred_tone_profile_id
            JOIN topics t ON t.slug = p.topic_slug
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
                p.domain_pack_key,
                tp.name AS preferred_tone_profile_name,
                t.source_type,
                t.source_ref_slug,
                t.title AS topic_title,
                t.angle AS topic_angle,
                ta.title AS reference_article_title,
                ta.author AS reference_article_author,
                COALESCE(NULLIF(TRIM(ta.source_name), ''), '手动录入') AS reference_article_source_name,
                ta.summary AS reference_article_summary,
                ta.body_markdown AS reference_article_body_markdown,
                ta.structure_notes AS reference_article_structure_notes,
                ta.tags AS reference_article_tags,
                CASE
                    WHEN t.source_type = 'trend' THEN tr.title
                    WHEN t.source_type = 'tracked_article' THEN '参考文章 / ' || COALESCE(NULLIF(TRIM(ta.source_name), ''), '手动录入')
                    WHEN t.source_type = 'manual' THEN '原创选题 / 手动录入'
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


def _build_reference_article_payload(
    project: sqlite3.Row,
    *,
    hide_details: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_type": str(project["source_type"]),
    }
    if str(project["source_type"]) != "tracked_article":
        return payload
    if hide_details:
        payload["reference_article_hidden"] = True
        return payload

    tags: list[str] = []
    raw_tags = project["reference_article_tags"]
    if raw_tags not in (None, ""):
        try:
            parsed_tags = json.loads(str(raw_tags))
            if isinstance(parsed_tags, list):
                tags = [str(tag) for tag in parsed_tags]
        except json.JSONDecodeError:
            tags = []

    payload.update(
        {
            "reference_article_title": str(project["reference_article_title"] or ""),
            "reference_article_author": str(project["reference_article_author"] or ""),
            "reference_article_source_name": str(project["reference_article_source_name"] or "手动录入"),
            "reference_article_summary": str(project["reference_article_summary"] or ""),
            "reference_article_body_markdown": str(project["reference_article_body_markdown"] or ""),
            "reference_article_structure_notes": str(project["reference_article_structure_notes"] or ""),
            "reference_article_tags": tags,
        }
    )
    return payload


def _build_project_reference_originality_report(
    project: sqlite3.Row,
    draft_row: sqlite3.Row | None,
) -> dict[str, object] | None:
    if str(project["source_type"]) != "tracked_article" or not draft_row:
        return None
    source_markdown = str(project["reference_article_body_markdown"] or "").strip()
    if not source_markdown:
        return None
    report = build_reference_originality_report(
        source_title=str(project["reference_article_title"] or ""),
        source_markdown=source_markdown,
        draft_title=str(draft_row["title"] or ""),
        draft_markdown=str(draft_row["body_markdown"] or ""),
    )
    return report.to_dict()


def _build_strategy_bundle_payload(
    *,
    problem_brief: ProblemBriefItem | None,
    strategy_card: StrategyCardItem | None,
    benchmarks: list[BenchmarkReferenceItem],
) -> dict[str, object]:
    return {
        "problem_brief": problem_brief.model_dump() if problem_brief and strategy_card else None,
        "strategy_card": strategy_card.model_dump() if strategy_card else None,
        "benchmarks": [benchmark.model_dump() for benchmark in benchmarks] if strategy_card else None,
    }


def _hydrate_problem_brief_row(row: sqlite3.Row) -> ProblemBriefItem:
    payload = dict(row)
    payload["unknowns"] = json.loads(str(payload["unknowns"]))
    payload["constraints"] = json.loads(str(payload["constraints"]))
    return ProblemBriefItem(**payload)


def _hydrate_benchmark_reference_row(row: sqlite3.Row) -> BenchmarkReferenceItem:
    return BenchmarkReferenceItem(**dict(row))


def _hydrate_strategy_card_row(row: sqlite3.Row) -> StrategyCardItem:
    payload = dict(row)
    payload["expression_constraints"] = json.loads(str(payload["expression_constraints"]))
    payload["divergence_axes"] = json.loads(str(payload["divergence_axes"]))
    payload["execution_checklist"] = json.loads(str(payload["execution_checklist"]))
    return StrategyCardItem(**payload)


def _load_json_string_list(raw_value: object) -> list[str]:
    if raw_value in (None, ""):
        return []
    try:
        parsed = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]


def _hydrate_diagnosis_report_row(row: sqlite3.Row) -> DraftDiagnosisReportItem:
    payload = dict(row)
    payload["upstream_findings"] = _load_json_string_list(payload["upstream_findings"])
    payload["downstream_findings"] = _load_json_string_list(payload["downstream_findings"])
    return DraftDiagnosisReportItem(**payload)


def _hydrate_directional_polish_link_row(row: sqlite3.Row) -> DirectionalPolishLinkItem:
    return DirectionalPolishLinkItem(**dict(row))


def _hydrate_creative_review_report_row(row: sqlite3.Row) -> CreativeReviewReportItem:
    payload = dict(row)
    try:
        retained_lessons = json.loads(str(payload["retained_lessons"]))
    except json.JSONDecodeError:
        retained_lessons = []
    payload["retained_lessons"] = retained_lessons if isinstance(retained_lessons, list) else []
    return CreativeReviewReportItem(**payload)


def _hydrate_reusable_pattern_row(row: sqlite3.Row) -> ReusablePatternItem:
    return ReusablePatternItem(**dict(row))


def _get_latest_problem_brief_row(connection: sqlite3.Connection, project_slug: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            project_slug,
            version,
            source_mode,
            raw_goal,
            clarified_problem,
            observed_phenomenon,
            writing_goal,
            target_reader_situation,
            core_conflict,
            constraints,
            feedback_entry,
            problem_statement_markdown,
            unknowns,
            status,
            created_at
        FROM problem_briefs
        WHERE project_slug = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()


def _get_problem_brief_row_for_version(
    connection: sqlite3.Connection,
    project_slug: str,
    version: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            project_slug,
            version,
            source_mode,
            raw_goal,
            clarified_problem,
            observed_phenomenon,
            writing_goal,
            target_reader_situation,
            core_conflict,
            constraints,
            feedback_entry,
            problem_statement_markdown,
            unknowns,
            status,
            created_at
        FROM problem_briefs
        WHERE project_slug = ? AND version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug, version),
    ).fetchone()


def _get_latest_strategy_card_row(connection: sqlite3.Connection, project_slug: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            project_slug,
            version,
            problem_brief_version,
            reader_situation,
            point_of_view,
            conflict_frame,
            emotional_path,
            structure_mode,
            opening_move,
            body_shift,
            ending_move,
            expression_constraints,
            divergence_axes,
            execution_checklist,
            benchmark_summary,
            strategy_markdown,
            status,
            created_at,
            adopted_at
        FROM strategy_cards
        WHERE project_slug = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()


def _get_adopted_strategy_card_row(connection: sqlite3.Connection, project_slug: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            project_slug,
            version,
            problem_brief_version,
            reader_situation,
            point_of_view,
            conflict_frame,
            emotional_path,
            structure_mode,
            opening_move,
            body_shift,
            ending_move,
            expression_constraints,
            divergence_axes,
            execution_checklist,
            benchmark_summary,
            strategy_markdown,
            status,
            created_at,
            adopted_at
        FROM strategy_cards
        WHERE project_slug = ? AND adopted_at IS NOT NULL
        ORDER BY datetime(adopted_at) DESC, version DESC, id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()


def _get_strategy_card_row_by_version(
    connection: sqlite3.Connection,
    project_slug: str,
    version: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            project_slug,
            version,
            problem_brief_version,
            reader_situation,
            point_of_view,
            conflict_frame,
            emotional_path,
            structure_mode,
            opening_move,
            body_shift,
            ending_move,
            expression_constraints,
            divergence_axes,
            execution_checklist,
            benchmark_summary,
            strategy_markdown,
            status,
            created_at,
            adopted_at
        FROM strategy_cards
        WHERE project_slug = ? AND version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug, version),
    ).fetchone()


def _get_current_strategy_card_row(connection: sqlite3.Connection, project_slug: str) -> sqlite3.Row | None:
    return _get_adopted_strategy_card_row(connection, project_slug) or _get_latest_strategy_card_row(connection, project_slug)


def _get_diagnosis_report_select_sql() -> str:
    return """
        SELECT
            project_slug,
            draft_version,
            version,
            opening_strength,
            scene_specificity,
            viewpoint_clarity,
            progression_efficiency,
            ending_quality,
            ai_fingerprint_level,
            upstream_findings,
            downstream_findings,
            recommended_next_action,
            objective_summary,
            recommended_polish_instruction,
            created_at
        FROM diagnosis_reports
    """


def _get_latest_diagnosis_report_row(
    connection: sqlite3.Connection,
    project_slug: str,
    *,
    draft_version: int | None = None,
) -> sqlite3.Row | None:
    if draft_version is None:
        return connection.execute(
            _get_diagnosis_report_select_sql()
            + """
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
            LIMIT 1
            """,
            (project_slug,),
        ).fetchone()
    return connection.execute(
        _get_diagnosis_report_select_sql()
        + """
        WHERE project_slug = ? AND draft_version = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (project_slug, draft_version),
    ).fetchone()


def _get_diagnosis_report_row_by_version(
    connection: sqlite3.Connection,
    project_slug: str,
    version: int,
) -> sqlite3.Row | None:
    return connection.execute(
        _get_diagnosis_report_select_sql()
        + """
        WHERE project_slug = ? AND version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug, version),
    ).fetchone()


def _get_creative_review_report_select_sql() -> str:
    return """
        SELECT
            project_slug,
            version,
            strategy_version,
            draft_version,
            summary_markdown,
            retained_lessons,
            created_at
        FROM creative_review_reports
    """


def _get_latest_creative_review_report_row(
    connection: sqlite3.Connection,
    project_slug: str,
) -> sqlite3.Row | None:
    return connection.execute(
        _get_creative_review_report_select_sql()
        + """
        WHERE project_slug = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()


def _get_creative_review_report_row_by_version(
    connection: sqlite3.Connection,
    project_slug: str,
    version: int,
) -> sqlite3.Row | None:
    return connection.execute(
        _get_creative_review_report_select_sql()
        + """
        WHERE project_slug = ? AND version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug, version),
    ).fetchone()


def _get_benchmark_reference_rows(
    connection: sqlite3.Connection,
    project_slug: str,
    strategy_version: int,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            project_slug,
            strategy_version,
            reference_kind,
            reference_label,
            reference_pointer,
            borrow_focus,
            avoid_focus,
            rationale,
            sort_order
        FROM benchmark_references
        WHERE project_slug = ? AND strategy_version = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (project_slug, strategy_version),
    ).fetchall()


def _load_project_strategy_bundle(
    connection: sqlite3.Connection,
    project_slug: str,
    *,
    adopted_only: bool = False,
) -> tuple[ProblemBriefItem | None, list[BenchmarkReferenceItem], StrategyCardItem | None]:
    strategy_card_row = (
        _get_adopted_strategy_card_row(connection, project_slug)
        if adopted_only
        else _get_current_strategy_card_row(connection, project_slug)
    )
    if not strategy_card_row:
        problem_brief_row = _get_latest_problem_brief_row(connection, project_slug)
        return (
            _hydrate_problem_brief_row(problem_brief_row) if problem_brief_row else None,
            [],
            None,
        )

    problem_brief_row = _get_problem_brief_row_for_version(
        connection,
        project_slug,
        int(strategy_card_row["problem_brief_version"]),
    )
    benchmark_rows = _get_benchmark_reference_rows(
        connection,
        project_slug,
        int(strategy_card_row["version"]),
    )
    return (
        _hydrate_problem_brief_row(problem_brief_row) if problem_brief_row else None,
        [_hydrate_benchmark_reference_row(row) for row in benchmark_rows],
        _hydrate_strategy_card_row(strategy_card_row),
    )


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
        SELECT project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name
        FROM outlines
        WHERE project_slug = ?
        ORDER BY version DESC, id DESC
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
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ? AND outline_version = ?
            ORDER BY version DESC, id DESC
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
                created_at,
                origin,
                tone_profile_id,
                tone_profile_name
            FROM assets
            WHERE project_slug = ? AND draft_version = ?
            ORDER BY version DESC, id DESC
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
                created_at,
                origin,
                tone_profile_id,
                tone_profile_name
            FROM publish_packages
            WHERE project_slug = ? AND draft_version = ? AND assets_version = ?
            ORDER BY version DESC, id DESC
            LIMIT 1
            """,
            (project_slug, draft_row["version"], assets_row["version"]),
        ).fetchone()

    return outline_row, draft_row, assets_row, publish_package_row


def _derive_project_chain_state(
    *,
    stage: str,
    source_type: str,
    has_strategy_package: bool,
    has_adopted_strategy: bool,
    outline_row: sqlite3.Row | None,
    draft_row: sqlite3.Row | None,
    assets_row: sqlite3.Row | None,
    publish_package_row: sqlite3.Row | None,
) -> dict[str, object]:
    current_outline_version = int(outline_row["version"]) if outline_row else None
    current_draft_version = int(draft_row["version"]) if draft_row else None
    current_assets_version = int(assets_row["version"]) if assets_row else None
    current_publish_package_version = int(publish_package_row["version"]) if publish_package_row else None

    if source_type == "tracked_article" and not has_strategy_package:
        chain_status = "missing"
        current_chain_state = "missing_strategy"
        next_required_step = "generate_strategy_package"
    elif source_type == "tracked_article" and not has_adopted_strategy:
        chain_status = "stale"
        current_chain_state = "strategy_ready"
        next_required_step = None
    elif not outline_row:
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
    source_type: str,
    has_strategy_package: bool,
    has_adopted_strategy: bool,
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
            source_type=source_type,
            has_strategy_package=has_strategy_package,
            has_adopted_strategy=has_adopted_strategy,
            outline_row=outline_row,
            draft_row=draft_row,
            assets_row=assets_row,
            publish_package_row=publish_package_row,
        )
    )
    return ProjectItem(**payload)


def _build_project_item(connection: sqlite3.Connection, project_row: sqlite3.Row) -> ProjectItem:
    project_slug = str(project_row["slug"])
    outline_row, draft_row, assets_row, publish_package_row = _get_project_chain_rows(
        connection, project_slug
    )
    retro_row = _get_project_retro_row(
        connection,
        project_slug,
        publish_package_row=publish_package_row,
    )
    problem_brief, _, strategy_card = _load_project_strategy_bundle(connection, project_slug)
    has_strategy_package = problem_brief is not None and strategy_card is not None
    has_adopted_strategy = bool(strategy_card and strategy_card.adopted_at)
    return _build_project_item_from_rows(
        project_row,
        source_type=str(project_row["source_type"] or "trend"),
        has_strategy_package=has_strategy_package,
        has_adopted_strategy=has_adopted_strategy,
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


def generate_strategy_package(project_slug: str) -> StrategyPackageResult:
    project = _get_project_context(project_slug)
    created_at = _utc_now_iso()
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            problem_brief_current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM problem_briefs WHERE project_slug = ?",
                (project_slug,),
            ).fetchone()
            strategy_card_current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM strategy_cards WHERE project_slug = ?",
                (project_slug,),
            ).fetchone()
            problem_brief_version = int(problem_brief_current["version"]) + 1
            strategy_version = int(strategy_card_current["version"]) + 1

            package = build_strategy_package(
                project=project,
                problem_brief_version=problem_brief_version,
                strategy_version=strategy_version,
                created_at=created_at,
            )

            connection.execute(
                """
                INSERT INTO problem_briefs (
                    project_slug,
                    version,
                    source_mode,
                    raw_goal,
                    clarified_problem,
                    observed_phenomenon,
                    writing_goal,
                    target_reader_situation,
                    core_conflict,
                    constraints,
                    feedback_entry,
                    problem_statement_markdown,
                    unknowns,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package.problem_brief.project_slug,
                    package.problem_brief.version,
                    package.problem_brief.source_mode,
                    package.problem_brief.raw_goal,
                    package.problem_brief.clarified_problem,
                    package.problem_brief.observed_phenomenon,
                    package.problem_brief.writing_goal,
                    package.problem_brief.target_reader_situation,
                    package.problem_brief.core_conflict,
                    json.dumps(package.problem_brief.constraints, ensure_ascii=False),
                    package.problem_brief.feedback_entry,
                    package.problem_brief.problem_statement_markdown,
                    json.dumps(package.problem_brief.unknowns, ensure_ascii=False),
                    package.problem_brief.status,
                    package.problem_brief.created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO strategy_cards (
                    project_slug,
                    version,
                    problem_brief_version,
                    reader_situation,
                    point_of_view,
                    conflict_frame,
                    emotional_path,
                    structure_mode,
                    opening_move,
                    body_shift,
                    ending_move,
                    expression_constraints,
                    divergence_axes,
                    execution_checklist,
                    benchmark_summary,
                    strategy_markdown,
                    status,
                    created_at,
                    adopted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package.strategy_card.project_slug,
                    package.strategy_card.version,
                    package.strategy_card.problem_brief_version,
                    package.strategy_card.reader_situation,
                    package.strategy_card.point_of_view,
                    package.strategy_card.conflict_frame,
                    package.strategy_card.emotional_path,
                    package.strategy_card.structure_mode,
                    package.strategy_card.opening_move,
                    package.strategy_card.body_shift,
                    package.strategy_card.ending_move,
                    json.dumps(package.strategy_card.expression_constraints, ensure_ascii=False),
                    json.dumps(package.strategy_card.divergence_axes, ensure_ascii=False),
                    json.dumps(package.strategy_card.execution_checklist, ensure_ascii=False),
                    package.strategy_card.benchmark_summary,
                    package.strategy_card.strategy_markdown,
                    package.strategy_card.status,
                    package.strategy_card.created_at,
                    package.strategy_card.adopted_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO benchmark_references (
                    project_slug,
                    strategy_version,
                    reference_kind,
                    reference_label,
                    reference_pointer,
                    borrow_focus,
                    avoid_focus,
                    rationale,
                    sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        benchmark.project_slug,
                        benchmark.strategy_version,
                        benchmark.reference_kind,
                        benchmark.reference_label,
                        benchmark.reference_pointer,
                        benchmark.borrow_focus,
                        benchmark.avoid_focus,
                        benchmark.rationale,
                        benchmark.sort_order,
                    )
                    for benchmark in package.benchmarks
                ],
            )
            _record_task(
                connection,
                task_type="strategy_package_generated",
                status="done",
                entity_slug=project_slug,
                entity_type="project",
            )
            connection.commit()

    return package


def adopt_strategy_card(project_slug: str, version: int) -> AdoptStrategyCardResponse:
    _get_project_row(project_slug)
    adopted_at = _utc_now_iso()
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            strategy_card_row = _get_strategy_card_row_by_version(connection, project_slug, version)
            if not strategy_card_row:
                raise HTTPException(status_code=404, detail="Strategy card version not found")

            connection.execute(
                "UPDATE strategy_cards SET adopted_at = NULL WHERE project_slug = ?",
                (project_slug,),
            )
            connection.execute(
                "UPDATE strategy_cards SET adopted_at = ? WHERE project_slug = ? AND version = ?",
                (adopted_at, project_slug, version),
            )
            _record_task(
                connection,
                task_type="strategy_card_adopted",
                status="done",
                entity_slug=project_slug,
                entity_type="project",
            )
            connection.commit()

            adopted_row = _get_strategy_card_row_by_version(connection, project_slug, version)

    if not adopted_row:
        raise HTTPException(status_code=404, detail="Strategy card version not found")
    return AdoptStrategyCardResponse(
        project_slug=project_slug,
        strategy_card=_hydrate_strategy_card_row(adopted_row),
        project=get_project_detail(project_slug).project.model_dump(),
    )


def get_project_detail(project_slug: str) -> ProjectDetail:
    project_row = _get_project_context(project_slug)
    with _get_connection() as connection:
        outline_row, draft_row, assets_row, publish_package_row = _get_project_chain_rows(
            connection, project_slug
        )
        retro_row = _get_project_retro_row(
            connection,
            project_slug,
            publish_package_row=publish_package_row,
        )
        problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(connection, project_slug)
        diagnosis_report_row = _get_latest_diagnosis_report_row(
            connection,
            project_slug,
            draft_version=int(draft_row["version"]) if draft_row else None,
        ) if draft_row else None
        creative_review_report_row = _get_latest_creative_review_report_row(connection, project_slug)
        reusable_pattern_rows = connection.execute(
            """
            SELECT
                id,
                source_project_slug,
                source_report_version,
                pattern_type,
                title,
                intended_use,
                pattern_content,
                caution_notes,
                status,
                created_at
            FROM reusable_patterns
            WHERE status = ?
            ORDER BY datetime(created_at) DESC, rowid DESC
            """,
            ("active",),
        ).fetchall()
    has_strategy_package = problem_brief is not None and strategy_card is not None
    has_adopted_strategy = bool(strategy_card and strategy_card.adopted_at)

    return ProjectDetail(
        project=_build_project_item_from_rows(
            project_row,
            source_type=str(project_row["source_type"] or "trend"),
            has_strategy_package=has_strategy_package,
            has_adopted_strategy=has_adopted_strategy,
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
        problem_brief=problem_brief,
        benchmarks=benchmarks,
        strategy_card=strategy_card,
        diagnosis_report=_hydrate_diagnosis_report_row(diagnosis_report_row) if diagnosis_report_row else None,
        creative_review_report=(
            _hydrate_creative_review_report_row(creative_review_report_row)
            if creative_review_report_row
            else None
        ),
        reusable_patterns=[_hydrate_reusable_pattern_row(row) for row in reusable_pattern_rows],
        reference_originality_report=_build_project_reference_originality_report(project_row, draft_row),
    )


def get_project_versions(project_slug: str) -> ProjectVersions:
    _get_project_row(project_slug)
    with _get_connection() as connection:
        outline_rows = connection.execute(
            """
            SELECT project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name
            FROM outlines
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
            """,
            (project_slug,),
        ).fetchall()
        draft_rows = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
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
                created_at,
                origin,
                tone_profile_id,
                tone_profile_name
            FROM assets
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
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
                created_at,
                origin,
                tone_profile_id,
                tone_profile_name
            FROM publish_packages
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
            """,
            (project_slug,),
        ).fetchall()
        strategy_card_rows = connection.execute(
            """
            SELECT
                project_slug,
                version,
                problem_brief_version,
                reader_situation,
                point_of_view,
                conflict_frame,
                emotional_path,
                opening_move,
                body_shift,
                ending_move,
                expression_constraints,
                divergence_axes,
                execution_checklist,
                benchmark_summary,
                strategy_markdown,
                status,
                created_at,
                adopted_at
            FROM strategy_cards
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
            """,
            (project_slug,),
        ).fetchall()
        diagnosis_report_rows = connection.execute(
            _get_diagnosis_report_select_sql()
            + """
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
            """,
            (project_slug,),
        ).fetchall()
        directional_polish_link_rows = connection.execute(
            """
            SELECT
                project_slug,
                source_draft_version,
                target_draft_version,
                diagnosis_version,
                objective_key,
                objective_summary,
                created_at
            FROM directional_polish_links
            WHERE project_slug = ?
            ORDER BY id DESC
            """,
            (project_slug,),
        ).fetchall()
        creative_review_report_rows = connection.execute(
            _get_creative_review_report_select_sql()
            + """
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
            """,
            (project_slug,),
        ).fetchall()

    return ProjectVersions(
        project_slug=project_slug,
        outlines=[OutlineItem(**dict(row)) for row in outline_rows],
        drafts=[DraftItem(**dict(row)) for row in draft_rows],
        assets=[_hydrate_asset_row(row) for row in assets_rows],
        publish_packages=[_hydrate_publish_package_row(row) for row in publish_package_rows],
        strategy_cards=[_hydrate_strategy_card_row(row) for row in strategy_card_rows],
        diagnosis_reports=[_hydrate_diagnosis_report_row(row) for row in diagnosis_report_rows],
        directional_polish_links=[_hydrate_directional_polish_link_row(row) for row in directional_polish_link_rows],
        creative_review_reports=[_hydrate_creative_review_report_row(row) for row in creative_review_report_rows],
    )


def generate_creative_review_report(project_slug: str) -> CreativeReviewReportItem:
    project_row = _get_project_context(project_slug)
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            outline_row, draft_row, assets_row, publish_package_row = _get_project_chain_rows(
                connection,
                project_slug,
            )
            retro_row = _get_project_retro_row(
                connection,
                project_slug,
                publish_package_row=publish_package_row,
            )
            problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(connection, project_slug)
            has_strategy_package = problem_brief is not None and strategy_card is not None
            has_adopted_strategy = bool(strategy_card and strategy_card.adopted_at)
            project_item = _build_project_item_from_rows(
                project_row,
                source_type=str(project_row["source_type"] or "trend"),
                has_strategy_package=has_strategy_package,
                has_adopted_strategy=has_adopted_strategy,
                outline_row=outline_row,
                draft_row=draft_row,
                assets_row=assets_row,
                publish_package_row=publish_package_row,
                retro_row=retro_row,
            )
            draft_rows = connection.execute(
                """
                SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
                FROM drafts
                WHERE project_slug = ?
                ORDER BY version DESC, id DESC
                """,
                (project_slug,),
            ).fetchall()
            latest_publish_package_row = connection.execute(
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
                    created_at,
                    origin,
                    tone_profile_id,
                    tone_profile_name
                FROM publish_packages
                WHERE project_slug = ?
                ORDER BY version DESC, id DESC
                LIMIT 1
                """,
                (project_slug,),
            ).fetchone()
            latest_publish_retro_row = _get_project_retro_row(
                connection,
                project_slug,
                publish_package_row=latest_publish_package_row,
            ) if latest_publish_package_row else None
            diagnosis_report_rows = connection.execute(
                _get_diagnosis_report_select_sql()
                + """
                WHERE project_slug = ?
                ORDER BY version DESC, id DESC
                """,
                (project_slug,),
            ).fetchall()
            directional_polish_link_rows = connection.execute(
                """
                SELECT
                    project_slug,
                    source_draft_version,
                    target_draft_version,
                    diagnosis_version,
                    objective_key,
                    objective_summary,
                    created_at
                FROM directional_polish_links
                WHERE project_slug = ?
                ORDER BY id DESC
                """,
                (project_slug,),
            ).fetchall()
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM creative_review_reports WHERE project_slug = ?",
                (project_slug,),
            ).fetchone()
            version = int(current["version"]) + 1
            created_at = _utc_now_iso()
            report = build_creative_review_report(
                project_slug=project_slug,
                version=version,
                created_at=created_at,
                project=project_item.model_dump(),
                problem_brief=problem_brief.model_dump() if problem_brief else None,
                benchmarks=[benchmark.model_dump() for benchmark in benchmarks],
                strategy_card=strategy_card.model_dump() if strategy_card else None,
                diagnosis_reports=[
                    _hydrate_diagnosis_report_row(row).model_dump()
                    for row in diagnosis_report_rows
                ],
                directional_polish_links=[
                    _hydrate_directional_polish_link_row(row).model_dump()
                    for row in directional_polish_link_rows
                ],
                drafts=[DraftItem(**dict(row)).model_dump() for row in draft_rows],
                publish_package=(
                    _hydrate_publish_package_row(latest_publish_package_row).model_dump()
                    if latest_publish_package_row
                    else None
                ),
                retro=(
                    _hydrate_project_retro_row(latest_publish_retro_row).model_dump()
                    if latest_publish_retro_row
                    else None
                ),
            )
            connection.execute(
                """
                INSERT INTO creative_review_reports (
                    project_slug,
                    version,
                    strategy_version,
                    draft_version,
                    summary_markdown,
                    retained_lessons,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.project_slug,
                    report.version,
                    report.strategy_version,
                    report.draft_version,
                    report.summary_markdown,
                    json.dumps(
                        [lesson.model_dump() for lesson in report.retained_lessons],
                        ensure_ascii=False,
                    ),
                    report.created_at,
                ),
            )
            _record_task(
                connection,
                task_type="creative_review_report_generated",
                status="done",
                entity_slug=project_slug,
                entity_type="project",
            )
            connection.commit()

    return report


def list_reusable_patterns(
    *,
    pattern_type: str | None = None,
    source_project_slug: str | None = None,
    include_archived: bool = False,
) -> list[ReusablePatternItem]:
    conditions: list[str] = []
    params: list[object] = []
    if not include_archived:
        conditions.append("status = ?")
        params.append("active")
    if pattern_type:
        conditions.append("pattern_type = ?")
        params.append(pattern_type)
    if source_project_slug:
        conditions.append("source_project_slug = ?")
        params.append(source_project_slug)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                id,
                source_project_slug,
                source_report_version,
                pattern_type,
                title,
                intended_use,
                pattern_content,
                caution_notes,
                status,
                created_at
            FROM reusable_patterns
            {where_clause}
            ORDER BY datetime(created_at) DESC, rowid DESC
            """,
            tuple(params),
        ).fetchall()
    return [_hydrate_reusable_pattern_row(row) for row in rows]


def promote_creative_pattern(project_slug: str, payload: PromoteCreativePatternAction) -> ReusablePatternItem:
    _get_project_row(project_slug)
    created_at = _utc_now_iso()
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            report_row = _get_creative_review_report_row_by_version(
                connection,
                project_slug,
                payload.report_version,
            )
            if not report_row:
                raise HTTPException(status_code=404, detail="Creative review report version not found")
            report = _hydrate_creative_review_report_row(report_row)
            if payload.lesson_index < 0 or payload.lesson_index >= len(report.retained_lessons):
                raise HTTPException(status_code=400, detail="Lesson index is out of range")
            selected_lesson = report.retained_lessons[payload.lesson_index]
            pattern_id = build_reusable_pattern_id(
                source_project_slug=project_slug,
                source_report_version=report.version,
                lesson_index=payload.lesson_index,
                title=(payload.title or selected_lesson.title),
            )
            existing_row = connection.execute(
                """
                SELECT
                    id,
                    source_project_slug,
                    source_report_version,
                    pattern_type,
                    title,
                    intended_use,
                    pattern_content,
                    caution_notes,
                    status,
                    created_at
                FROM reusable_patterns
                WHERE id = ?
                """,
                (pattern_id,),
            ).fetchone()
            if existing_row:
                return _hydrate_reusable_pattern_row(existing_row)

            pattern = build_reusable_pattern_from_lesson(
                pattern_id=pattern_id,
                source_project_slug=project_slug,
                source_report_version=report.version,
                retained_lessons=report.retained_lessons,
                payload=payload,
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO reusable_patterns (
                    id,
                    source_project_slug,
                    source_report_version,
                    pattern_type,
                    title,
                    intended_use,
                    pattern_content,
                    caution_notes,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern.id,
                    pattern.source_project_slug,
                    pattern.source_report_version,
                    pattern.pattern_type,
                    pattern.title,
                    pattern.intended_use,
                    pattern.pattern_content,
                    pattern.caution_notes,
                    pattern.status,
                    pattern.created_at,
                ),
            )
            _record_task(
                connection,
                task_type="creative_pattern_promoted",
                status="done",
                entity_slug=project_slug,
                entity_type="project",
            )
            connection.commit()

    return pattern


def generate_outline(project_slug: str) -> OutlineItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    domain_pack = get_project_domain_pack(project)
    created_at = _utc_now_iso()
    origin = _resolve_version_origin()
    with _get_connection() as connection:
        problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(
            connection,
            project_slug,
            adopted_only=True,
        )
    if str(project["source_type"]) == "tracked_article" and not (problem_brief and strategy_card):
        raise HTTPException(
            status_code=409,
            detail="Tracked article projects require an adopted strategy card before outline generation",
        )
    reference_article_payload = _build_reference_article_payload(
        project,
        hide_details=str(project["source_type"]) == "tracked_article" and bool(problem_brief and strategy_card),
    )
    ai_payload: dict[str, object] = {
        "trend_title": project["trend_title"],
        "topic_title": project["topic_title"],
        "topic_angle": project["topic_angle"],
        "project_title": project["title"],
        "tone_profile": tone_profile.model_dump(),
        "domain_pack": domain_pack,
        **reference_article_payload,
    }
    if strategy_card and problem_brief:
        ai_payload["problem_brief"] = problem_brief.model_dump()
        ai_payload["strategy_card"] = strategy_card.model_dump()
        ai_payload["benchmarks"] = [benchmark.model_dump() for benchmark in benchmarks]
    ai_result = get_ai_generator().generate_outline(
        ai_payload
    )
    with _get_project_version_lock(project_slug):
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
                INSERT INTO outlines (project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_slug, version, hook, outline_body, created_at, origin, tone_profile.id, tone_profile.name),
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
        created_at=created_at,
        origin=origin,
        tone_profile_id=tone_profile.id,
        tone_profile_name=tone_profile.name,
    )


def restore_outline_version(project_slug: str, version: int) -> OutlineItem:
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            outline_row = connection.execute(
                """
                SELECT project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name
                FROM outlines
                WHERE project_slug = ? AND version = ?
                ORDER BY id DESC
                LIMIT 1
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
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(restored=True)
            connection.execute(
                """
                INSERT INTO outlines (project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    next_version,
                    outline_row["hook"],
                    outline_row["outline_body"],
                    created_at,
                    origin,
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
        created_at=created_at,
        origin=origin,
        tone_profile_id=int(outline_row["tone_profile_id"]) if outline_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(outline_row["tone_profile_name"]) if outline_row["tone_profile_name"] is not None else None,
    )


def generate_draft(project_slug: str) -> DraftItem:
    return _generate_draft(project_slug)


def diagnose_draft(project_slug: str, *, draft_version: int | None = None) -> DraftDiagnosisReportItem:
    project = _get_project_context(project_slug)
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            if draft_version is None:
                _, draft_row, _, _ = _get_project_chain_rows(connection, project_slug)
            else:
                draft_row = connection.execute(
                    """
                    SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
                    FROM drafts
                    WHERE project_slug = ? AND version = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project_slug, draft_version),
                ).fetchone()
            if not draft_row:
                raise HTTPException(status_code=409, detail="Draft not generated")

            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM diagnosis_reports WHERE project_slug = ?",
                (project_slug,),
            ).fetchone()
            version = int(current["version"]) + 1
            created_at = _utc_now_iso()
            problem_brief, _, strategy_card = _load_project_strategy_bundle(connection, project_slug)
            reference_originality_report = _build_project_reference_originality_report(project, draft_row)
            report = build_draft_diagnosis_report(
                project_slug=project_slug,
                draft_version=int(draft_row["version"]),
                version=version,
                title=str(draft_row["title"]),
                body_markdown=str(draft_row["body_markdown"]),
                created_at=created_at,
                reference_originality_report=reference_originality_report,
                has_strategy_card=problem_brief is not None and strategy_card is not None,
            )
            connection.execute(
                """
                INSERT INTO diagnosis_reports (
                    project_slug,
                    draft_version,
                    version,
                    opening_strength,
                    scene_specificity,
                    viewpoint_clarity,
                    progression_efficiency,
                    ending_quality,
                    ai_fingerprint_level,
                    upstream_findings,
                    downstream_findings,
                    recommended_next_action,
                    objective_summary,
                    recommended_polish_instruction,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.project_slug,
                    report.draft_version,
                    report.version,
                    report.opening_strength,
                    report.scene_specificity,
                    report.viewpoint_clarity,
                    report.progression_efficiency,
                    report.ending_quality,
                    report.ai_fingerprint_level,
                    json.dumps(report.upstream_findings, ensure_ascii=False),
                    json.dumps(report.downstream_findings, ensure_ascii=False),
                    report.recommended_next_action,
                    report.objective_summary,
                    report.recommended_polish_instruction,
                    report.created_at,
                ),
            )
            _record_task(
                connection,
                task_type="draft_diagnosed",
                status="done",
                entity_slug=project_slug,
                entity_type="project",
            )
            connection.commit()

    return DraftDiagnosisReportItem(**report.to_dict())


def polish_draft(
    project_slug: str,
    instruction: str | None = None,
    *,
    diagnosis_report_version: int | None = None,
    objective_key: str | None = None,
) -> DraftItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    normalized_instruction = (instruction or "").strip()
    directional_context: _DirectionalPolishContext | None = None

    if objective_key and diagnosis_report_version is None:
        raise HTTPException(status_code=400, detail="Diagnosis report version is required for diagnosis-driven polish")

    if diagnosis_report_version is not None:
        with _get_connection() as connection:
            diagnosis_row = _get_diagnosis_report_row_by_version(connection, project_slug, diagnosis_report_version)
        if not diagnosis_row:
            raise HTTPException(status_code=404, detail="Diagnosis report version not found")
        diagnosis_report = _hydrate_diagnosis_report_row(diagnosis_row)
        resolved_objective_key = (objective_key or diagnosis_report.recommended_next_action).strip()
        objective_summary = resolve_diagnosis_objective_summary(resolved_objective_key)
        directional_context = _DirectionalPolishContext(
            diagnosis_report_version=diagnosis_report.version,
            objective_key=resolved_objective_key,
            objective_summary=objective_summary,
        )
        effective_instruction = normalized_instruction or build_diagnosis_polish_instruction(
            diagnosis_report.model_dump(),
            objective_key=resolved_objective_key,
        )
    else:
        effective_instruction = normalized_instruction or tone_profile.default_polish_instruction.strip()

    return _generate_draft(
        project_slug,
        polish_instruction=effective_instruction,
        directional_polish_context=directional_context,
    )


def _generate_draft(
    project_slug: str,
    *,
    review_comment: str | None = None,
    polish_instruction: str | None = None,
    directional_polish_context: _DirectionalPolishContext | None = None,
) -> DraftItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    domain_pack = get_project_domain_pack(project)
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(
                connection,
                project_slug,
                adopted_only=True,
            )
            if str(project["source_type"]) == "tracked_article" and not (problem_brief and strategy_card):
                raise HTTPException(
                    status_code=409,
                    detail="Tracked article projects require an adopted strategy card before draft generation",
                )
            reference_article_payload = _build_reference_article_payload(
                project,
                hide_details=str(project["source_type"]) == "tracked_article" and bool(problem_brief and strategy_card),
            )
            strategy_bundle_payload = _build_strategy_bundle_payload(
                problem_brief=problem_brief,
                strategy_card=strategy_card,
                benchmarks=benchmarks,
            )
            outline_row = connection.execute(
                """
                SELECT project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name
                FROM outlines
                WHERE project_slug = ?
                ORDER BY version DESC, id DESC
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
                    SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
                    FROM drafts
                    WHERE project_slug = ?
                    ORDER BY version DESC, id DESC
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
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(
                review_comment=review_comment,
                polish_instruction=polish_instruction,
            )
            generator = get_ai_generator()
            draft_payload: dict[str, object] = {
                "trend_title": project["trend_title"],
                "topic_title": project["topic_title"],
                "topic_angle": project["topic_angle"],
                "project_title": project["title"],
                "outline": {
                    "hook": outline_row["hook"],
                    "outline_body": outline_row["outline_body"],
                },
                "tone_profile": tone_profile.model_dump(),
                "domain_pack": domain_pack,
                "review_comment": review_comment,
                "polish_instruction": polish_instruction,
                "draft": {
                    "title": latest_draft_row["title"],
                    "body_markdown": latest_draft_row["body_markdown"],
                }
                if polish_instruction and latest_draft_row
                else None,
                **strategy_bundle_payload,
                **reference_article_payload,
            }
            initial_candidates = _generate_initial_draft_candidates(
                project=project,
                generator=generator,
                draft_payload=draft_payload,
            )
            has_multiple_initial_candidates = len(initial_candidates) > 1
            title = ""
            body_markdown = ""
            best_title = ""
            best_body_markdown = ""
            best_reference_title = ""
            best_reference_body_markdown = ""
            best_cleanup_applied = False
            best_cleanup_changed_steps = 0
            for candidate_title, candidate_body_markdown in initial_candidates:
                candidate_reference_title = candidate_title
                candidate_reference_body_markdown = candidate_body_markdown
                current_title = candidate_title
                current_body_markdown = candidate_body_markdown
                current_cleanup_applied = False
                current_cleanup_changed_steps = 0
                if not polish_instruction:
                    finalized_candidate = _finalize_initial_draft_candidate(
                        project_slug=project_slug,
                        tone_profile=tone_profile,
                        project=project,
                        outline_row=outline_row,
                        review_comment=review_comment,
                        reference_article_payload=reference_article_payload,
                        strategy_bundle_payload=strategy_bundle_payload,
                        polish_instruction=polish_instruction,
                        generator=generator,
                        title=current_title,
                        body_markdown=current_body_markdown,
                        skip_nested_compact_polish=has_multiple_initial_candidates,
                    )
                    current_title = finalized_candidate.title
                    current_body_markdown = finalized_candidate.body_markdown
                    candidate_reference_title = finalized_candidate.reference_title
                    candidate_reference_body_markdown = finalized_candidate.reference_body_markdown
                    current_cleanup_applied = finalized_candidate.cleanup_applied
                    current_cleanup_changed_steps = finalized_candidate.cleanup_changed_steps
                if not best_title:
                    best_title = current_title
                    best_body_markdown = current_body_markdown
                    best_reference_title = candidate_reference_title
                    best_reference_body_markdown = candidate_reference_body_markdown
                    best_cleanup_applied = current_cleanup_applied
                    best_cleanup_changed_steps = current_cleanup_changed_steps
                    continue
                if _should_prefer_retried_ai_flavor_candidate(
                    current_title=best_title,
                    current_markdown=best_body_markdown,
                    retried_title=current_title,
                    retried_markdown=current_body_markdown,
                    current_reference_title=best_reference_title,
                    current_reference_markdown=best_reference_body_markdown,
                    retried_reference_title=candidate_reference_title,
                    retried_reference_markdown=candidate_reference_body_markdown,
                    current_cleanup_applied=best_cleanup_applied,
                    current_cleanup_changed_steps=best_cleanup_changed_steps,
                    retried_cleanup_applied=current_cleanup_applied,
                    retried_cleanup_changed_steps=current_cleanup_changed_steps,
                    source_type=str(project["source_type"]),
                ):
                    best_body_markdown = current_body_markdown
                    best_title = current_title
                    best_reference_title = candidate_reference_title
                    best_reference_body_markdown = candidate_reference_body_markdown
                    best_cleanup_applied = current_cleanup_applied
                    best_cleanup_changed_steps = current_cleanup_changed_steps
            title = best_title
            body_markdown = best_body_markdown
            if polish_instruction and latest_draft_row:
                body_markdown, title = _maybe_retry_polish_for_structure_drift(
                    project=project,
                    outline_row=outline_row,
                    tone_profile=tone_profile,
                    review_comment=review_comment,
                    polish_instruction=polish_instruction,
                    strategy_bundle_payload=strategy_bundle_payload,
                    reference_article_payload=reference_article_payload,
                    generator=generator,
                    source_draft_title=str(latest_draft_row["title"]),
                    source_draft_body_markdown=str(latest_draft_row["body_markdown"]),
                    candidate_title=title,
                    candidate_body_markdown=body_markdown,
                )
                body_markdown, title = _maybe_retry_polish_for_over_smoothing(
                    project=project,
                    outline_row=outline_row,
                    tone_profile=tone_profile,
                    review_comment=review_comment,
                    polish_instruction=polish_instruction,
                    strategy_bundle_payload=strategy_bundle_payload,
                    reference_article_payload=reference_article_payload,
                    generator=generator,
                    source_draft_title=str(latest_draft_row["title"]),
                    source_draft_body_markdown=str(latest_draft_row["body_markdown"]),
                    candidate_title=title,
                    candidate_body_markdown=body_markdown,
                )
                body_markdown, title = _maybe_retry_polish_for_article_shell_cleanup(
                    project=project,
                    outline_row=outline_row,
                    tone_profile=tone_profile,
                    review_comment=review_comment,
                    polish_instruction=polish_instruction,
                    strategy_bundle_payload=strategy_bundle_payload,
                    reference_article_payload=reference_article_payload,
                    generator=generator,
                    source_draft_title=str(latest_draft_row["title"]),
                    source_draft_body_markdown=str(latest_draft_row["body_markdown"]),
                    candidate_title=title,
                    candidate_body_markdown=body_markdown,
                )
                body_markdown, title = _maybe_retry_polish_for_remaining_ai_flavor(
                    project=project,
                    outline_row=outline_row,
                    tone_profile=tone_profile,
                    review_comment=review_comment,
                    polish_instruction=polish_instruction,
                    strategy_bundle_payload=strategy_bundle_payload,
                    reference_article_payload=reference_article_payload,
                    generator=generator,
                    source_draft_title=str(latest_draft_row["title"]),
                    source_draft_body_markdown=str(latest_draft_row["body_markdown"]),
                    candidate_title=title,
                    candidate_body_markdown=body_markdown,
                )
                body_markdown, title = _maybe_retry_polish_for_final_ai_flavor_cleanup(
                    project=project,
                    outline_row=outline_row,
                    tone_profile=tone_profile,
                    review_comment=review_comment,
                    polish_instruction=polish_instruction,
                    strategy_bundle_payload=strategy_bundle_payload,
                    reference_article_payload=reference_article_payload,
                    generator=generator,
                    source_draft_title=str(latest_draft_row["title"]),
                    source_draft_body_markdown=str(latest_draft_row["body_markdown"]),
                    candidate_title=title,
                    candidate_body_markdown=body_markdown,
                )
            if polish_instruction:
                finalized_candidate = _finalize_initial_draft_candidate(
                    project_slug=project_slug,
                    tone_profile=tone_profile,
                    project=project,
                    outline_row=outline_row,
                    review_comment=review_comment,
                    reference_article_payload=reference_article_payload,
                    strategy_bundle_payload=strategy_bundle_payload,
                    polish_instruction=polish_instruction,
                    generator=generator,
                    title=title,
                    body_markdown=body_markdown,
                    skip_nested_compact_polish=has_multiple_initial_candidates,
                )
                body_markdown = finalized_candidate.body_markdown
                title = finalized_candidate.title
            word_count = len(body_markdown)
            connection.execute(
                """
                INSERT INTO drafts (
                    project_slug, outline_version, version, title, body_markdown, word_count,
                    created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    outline_row["version"],
                    version,
                    title,
                    body_markdown,
                    word_count,
                    created_at,
                    origin,
                    tone_profile.id,
                    tone_profile.name,
                ),
            )
            if polish_instruction and latest_draft_row and directional_polish_context:
                connection.execute(
                    """
                    INSERT INTO directional_polish_links (
                        project_slug,
                        source_draft_version,
                        target_draft_version,
                        diagnosis_version,
                        objective_key,
                        objective_summary,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_slug,
                        int(latest_draft_row["version"]),
                        version,
                        directional_polish_context.diagnosis_report_version,
                        directional_polish_context.objective_key,
                        directional_polish_context.objective_summary,
                        created_at,
                    ),
                )
            _record_task(
                connection,
                task_type=(
                    "draft_polished_from_diagnosis"
                    if polish_instruction and directional_polish_context
                    else "draft_polished"
                    if polish_instruction
                    else "draft_generation"
                ),
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
        created_at=created_at,
        origin=origin,
        tone_profile_id=tone_profile.id,
        tone_profile_name=tone_profile.name,
    )


def _generate_initial_draft_candidates(
    *,
    project: sqlite3.Row,
    generator,
    draft_payload: dict[str, object],
) -> list[tuple[str, str]]:
    is_tracked_article = str(project["source_type"]) == "tracked_article"
    is_polish_mode = bool(draft_payload.get("polish_instruction"))
    uses_custom_base_url = bool(getattr(generator, "uses_custom_base_url", False))

    if not is_tracked_article or is_polish_mode or not uses_custom_base_url:
        initial_result = generator.generate_draft(draft_payload)
        return [
            (
                str(initial_result["title"]),
                str(initial_result["body_markdown"]),
            )
        ]

    compact_payload = dict(draft_payload)
    compact_payload["compact_strategy_mode"] = True

    try:
        compact_result = generator.generate_draft(compact_payload)
    except Exception as exc:
        logger.warning(
            "Compact strategy draft branch failed for project %s: %s",
            project["slug"],
            exc,
        )
        recovery_payload = _build_draft_timeout_recovery_payload(
            project=project,
            draft_payload=draft_payload,
        )
        try:
            recovery_result = generator.generate_draft(recovery_payload)
        except Exception as recovery_exc:
            logger.warning(
                "Timeout recovery draft branch failed for project %s: %s",
                project["slug"],
                recovery_exc,
            )
            full_fallback_payload = dict(draft_payload)
            full_fallback_payload["full_fallback_single_attempt_mode"] = True
            initial_result = generator.generate_draft(full_fallback_payload)
            return [
                (
                    str(initial_result["title"]),
                    str(initial_result["body_markdown"]),
                )
            ]
        return [
            (
                str(recovery_result["title"]),
                str(recovery_result["body_markdown"]),
            )
        ]

    compact_title = str(compact_result["title"])
    compact_body_markdown = str(compact_result["body_markdown"])
    candidates = [(compact_title, compact_body_markdown)]

    compact_summary = evaluate_ai_flavor_risk(
        title=compact_title,
        body_markdown=compact_body_markdown,
    )
    if compact_summary.level == "低" and compact_summary.score <= 18:
        if not _looks_like_over_smoothed_tracked_article_candidate(compact_body_markdown):
            return candidates
    if _looks_like_tracked_article_fragment_chain_candidate(compact_body_markdown):
        return candidates

    try:
        full_comparison_payload = dict(draft_payload)
        full_comparison_payload["full_fallback_single_attempt_mode"] = True
        initial_result = generator.generate_draft(full_comparison_payload)
    except Exception as exc:
        logger.warning(
            "Full strategy draft branch failed for project %s: %s",
            project["slug"],
            exc,
        )
        return candidates

    candidates.append(
        (
            str(initial_result["title"]),
            str(initial_result["body_markdown"]),
        )
    )
    return candidates


def _build_draft_timeout_recovery_payload(
    *,
    project: sqlite3.Row,
    draft_payload: Mapping[str, object],
) -> dict[str, object]:
    recovery_payload = dict(draft_payload)
    for key in ("problem_brief", "strategy_card", "benchmarks", "reference_article_hidden"):
        recovery_payload.pop(key, None)
    recovery_payload.update(_build_reference_article_payload(project, hide_details=False))
    recovery_payload["compact_strategy_mode"] = True
    recovery_payload["timeout_recovery_mode"] = True
    return recovery_payload


def _finalize_initial_draft_candidate(
    *,
    project_slug: str,
    tone_profile: ToneProfileItem,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    review_comment: str | None,
    reference_article_payload: dict[str, object],
    strategy_bundle_payload: dict[str, object],
    polish_instruction: str | None,
    generator,
    title: str,
    body_markdown: str,
    skip_nested_compact_polish: bool = False,
) -> _InitialDraftCandidateResult:
    def _finish(body: str, current_title: str) -> _InitialDraftCandidateResult:
        reference_title = current_title
        reference_body_markdown = body
        current_body, changed_steps = _apply_initial_draft_candidate_cleanups(
            title=current_title,
            body_markdown=body,
            source_type=str(project["source_type"]),
        )
        return _InitialDraftCandidateResult(
            title=current_title,
            body_markdown=current_body,
            reference_title=reference_title,
            reference_body_markdown=reference_body_markdown,
            cleanup_applied=current_body != reference_body_markdown,
            cleanup_changed_steps=changed_steps,
        )

    compressed_body_markdown, compressed_title = _maybe_compress_draft_output(
        project_slug=project_slug,
        tone_profile=tone_profile,
        title=title,
        body_markdown=body_markdown,
        project=project,
        outline_row=outline_row,
        review_comment=review_comment,
        reference_article_payload=reference_article_payload,
        generator=generator,
    )
    try:
        finalized_body_markdown, finalized_title = _maybe_auto_polish_ai_flavor_draft_output(
            title=compressed_title,
            body_markdown=compressed_body_markdown,
            project=project,
            outline_row=outline_row,
            tone_profile=tone_profile,
            review_comment=review_comment,
            polish_instruction=polish_instruction,
            strategy_bundle_payload=strategy_bundle_payload,
            reference_article_payload=reference_article_payload,
            generator=generator,
            skip_nested_compact_polish=skip_nested_compact_polish,
        )
        finalized_body_markdown, finalized_title = _maybe_compress_draft_output(
            project_slug=project_slug,
            tone_profile=tone_profile,
            title=finalized_title,
            body_markdown=finalized_body_markdown,
            project=project,
            outline_row=outline_row,
            review_comment=review_comment,
            reference_article_payload=reference_article_payload,
            generator=generator,
        )
        if str(project["source_type"]) == "tracked_article":
            finalized_body_markdown, finalized_title = _prefer_less_smoothed_tracked_article_variant(
                preferred_title=finalized_title,
                preferred_markdown=finalized_body_markdown,
                fallback_title=title,
                fallback_markdown=body_markdown,
            )
        return _finish(finalized_body_markdown, finalized_title)
    except Exception as exc:
        logger.warning(
            "Draft branch finalize failed for project %s with title %s: %s",
            project_slug,
            title,
            exc,
        )
        return _finish(compressed_body_markdown, compressed_title)


def _maybe_compress_draft_output(
    *,
    project_slug: str,
    tone_profile: ToneProfileItem,
    title: str,
    body_markdown: str,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    review_comment: str | None,
    reference_article_payload: dict[str, object],
    generator,
) -> tuple[str, str]:
    target_word_count = tone_profile.target_word_count
    if target_word_count <= 0:
        return body_markdown, title

    max_allowed_length = int(target_word_count * 1.5)
    if len(body_markdown) <= max_allowed_length:
        return body_markdown, title

    try:
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
                "domain_pack": get_project_domain_pack(project),
                "review_comment": review_comment,
                "polish_instruction": "请在不改变核心观点和结构顺序的前提下，压缩这篇草稿，删除重复表达与重复场景，把正文控制回目标字数附近。",
                "draft": {
                    "title": title,
                    "body_markdown": body_markdown,
                },
                **reference_article_payload,
            }
        )
    except Exception as exc:
        logger.warning(
            "Draft compression failed for project %s with title %s: %s",
            project_slug,
            title,
            exc,
        )
        return body_markdown, title

    compressed_body_markdown = str(compressed_result.get("body_markdown") or "").strip()
    compressed_title = str(compressed_result.get("title") or "").strip()
    if not compressed_body_markdown or not compressed_title:
        logger.warning(
            "Draft compression returned incomplete output for project %s with title %s",
            project_slug,
            title,
        )
        return body_markdown, title

    return compressed_body_markdown, compressed_title


def _split_markdown_blocks(markdown: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", markdown) if block.strip()]


def _strip_markdown_heading_prefix(block: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", block.strip())


def _normalize_structure_heading_label(block: str) -> str:
    return _strip_markdown_heading_prefix(block).strip().rstrip("。！？!?；;：:").strip()


def _looks_like_structure_heading(block: str) -> bool:
    raw = _strip_markdown_heading_prefix(block).replace("\n", " ").strip()
    normalized = _normalize_structure_heading_label(block)
    if not normalized:
        return False
    if len(normalized) > 24:
        return False
    if re.search(r"[，,]", normalized):
        return False
    if re.search(r"[。！？!?；;：:]", normalized):
        return False
    if re.match(r"^\d+[.)、]\s*", normalized):
        return False
    if raw.endswith(("。", "！", "？", "!", "?", "；", ";", "：", ":")):
        return normalized.startswith(("别", "不要", "先", "学会", "记得", "关于", "停止", "少", "多", "把"))
    return True


def _extract_first_sentence_fragment(block: str, *, max_length: int = 36) -> str:
    normalized = _strip_markdown_heading_prefix(block).replace("\n", " ").strip()
    if not normalized:
        return ""
    sentence = re.split(r"[。！？!?；;\n]", normalized, maxsplit=1)[0].strip()
    if len(sentence) > max_length:
        return sentence[:max_length].rstrip() + "..."
    return sentence


def _extract_structure_headings(markdown: str) -> list[str]:
    blocks = _split_markdown_blocks(markdown)
    if blocks and blocks[0].lstrip().startswith("#"):
        blocks = blocks[1:]

    headings: list[str] = []
    for block in blocks:
        if _looks_like_structure_heading(block):
            label = _normalize_structure_heading_label(block)
            if label and label not in headings:
                headings.append(label)
    return headings


def _extract_structure_heading_anchors(markdown: str) -> list[tuple[str, str]]:
    blocks = _split_markdown_blocks(markdown)
    if blocks and blocks[0].lstrip().startswith("#"):
        blocks = blocks[1:]

    anchors: list[tuple[str, str]] = []
    pending_heading: str | None = None
    for block in blocks:
        if _looks_like_structure_heading(block):
            pending_heading = _normalize_structure_heading_label(block)
            continue

        if pending_heading:
            sentence = _extract_first_sentence_fragment(block)
            if sentence:
                anchors.append((pending_heading, sentence))
            pending_heading = None

        if len(anchors) >= 4:
            break

    return anchors


def _find_missing_structure_headings(
    *,
    source_markdown: str,
    candidate_markdown: str,
) -> list[str]:
    source_headings = _extract_structure_headings(source_markdown)
    if len(source_headings) < 2:
        return []

    candidate_headings = {
        _normalize_structure_heading_label(heading)
        for heading in _extract_structure_headings(candidate_markdown)
    }
    return [heading for heading in source_headings if _normalize_structure_heading_label(heading) not in candidate_headings]


def _preserves_structure_headings(*, source_markdown: str, candidate_markdown: str) -> bool:
    return not _find_missing_structure_headings(
        source_markdown=source_markdown,
        candidate_markdown=candidate_markdown,
    )


def _build_structure_retry_instruction(
    *,
    base_instruction: str,
    source_markdown: str,
    missing_headings: list[str],
) -> str:
    retry_notes = [
        "上一次改写发生了结构漂移，丢失了原稿中的小节标题。",
        f"这次必须原样保留以下小节标题：{' / '.join(missing_headings[:6])}。",
    ]

    heading_anchors = _extract_structure_heading_anchors(source_markdown)
    if heading_anchors:
        retry_notes.append(
            "并继续围绕这些原稿锚点推进："
            + "；".join(f"{heading} -> {anchor}" for heading, anchor in heading_anchors[:4])
            + "。"
        )

    retry_notes.append("不要把这篇原稿改写成新的总分总结构，不要另起新的标题组或新的陌生案例。")
    return base_instruction.strip() + " " + "".join(retry_notes)


def _find_excessive_generic_reflective_openers(
    *,
    source_markdown: str,
    candidate_markdown: str,
) -> list[str]:
    source_openers = extract_generic_reflective_openers(source_markdown)
    candidate_openers = extract_generic_reflective_openers(candidate_markdown)
    if len(candidate_openers) < 2 or len(candidate_openers) <= len(source_openers):
        return []

    source_counts = Counter(source_openers)
    candidate_counts = Counter(candidate_openers)
    excess: list[str] = []
    for opener, count in candidate_counts.items():
        overflow = count - source_counts.get(opener, 0)
        if overflow > 0:
            excess.extend([opener] * overflow)

    return excess[:4]


def _looks_like_tracked_article_fragment_chain_candidate(markdown: str) -> bool:
    summary = evaluate_ai_flavor_risk(title="tracked-fragment-chain-check", body_markdown=markdown)
    residual_not_ab = extract_not_ab_skeletons(markdown)
    residual_openers = extract_generic_reflective_openers(markdown)
    residual_cliches = extract_growth_cliches(markdown)
    residual_embedded_banners = extract_embedded_banner_paragraphs(markdown)
    residual_quote_paragraphs = extract_isolated_quote_paragraphs(markdown)
    residual_explanatory_paragraphs = extract_explanatory_bridge_paragraphs(markdown)
    residual_short_judgments = extract_short_judgment_paragraphs(markdown)
    residual_cadence_pairs = count_short_long_cadence_pairs(markdown)
    bridging_paragraphs = extract_bridging_summary_paragraphs(markdown)
    time_chain_leads = _count_time_chain_leads(markdown)
    paragraphs = _extract_non_heading_paragraphs(markdown)

    if len(paragraphs) < 12:
        return False
    if summary.score < 50 or summary.score > 80:
        return False
    if len(residual_not_ab) > 1 or residual_openers or residual_cliches:
        return False
    if residual_embedded_banners or residual_quote_paragraphs or residual_explanatory_paragraphs:
        return False
    if len(residual_short_judgments) < 6 or residual_cadence_pairs < 6:
        return False
    if len(bridging_paragraphs) < 5:
        return False
    if time_chain_leads >= 4:
        return False
    if any("命中：单句敲钟段偏多" in hit for hit in summary.hits) and any(
        "命中：短句敲钟后接长解释的固定节拍" in hit for hit in summary.hits
    ):
        return True
    return False


def _looks_like_over_smoothed_tracked_article_candidate(markdown: str) -> bool:
    paragraphs = _extract_non_heading_paragraphs(markdown)
    if len(paragraphs) < 10:
        return False

    short_paragraph_count = sum(
        1
        for paragraph in paragraphs
        if len(re.sub(r"\s+", "", paragraph)) <= 45
    )
    if short_paragraph_count > 2:
        return False

    if _count_time_chain_leads(markdown) > 1:
        return False

    if extract_not_ab_skeletons(markdown):
        return False

    if extract_generic_reflective_openers(markdown):
        return False

    summary = evaluate_ai_flavor_risk(title="tracked-over-smoothed-check", body_markdown=markdown)
    if summary.score > 18:
        return False

    return True


def _prefer_less_smoothed_tracked_article_variant(
    *,
    preferred_title: str,
    preferred_markdown: str,
    fallback_title: str,
    fallback_markdown: str,
) -> tuple[str, str]:
    preferred_over_smoothed = _looks_like_over_smoothed_tracked_article_candidate(preferred_markdown)
    fallback_over_smoothed = _looks_like_over_smoothed_tracked_article_candidate(fallback_markdown)
    if not preferred_over_smoothed or fallback_over_smoothed:
        return preferred_markdown, preferred_title

    fallback_summary = evaluate_ai_flavor_risk(
        title=fallback_title,
        body_markdown=fallback_markdown,
    )
    preferred_summary = evaluate_ai_flavor_risk(
        title=preferred_title,
        body_markdown=preferred_markdown,
    )
    fallback_lecture_hits = [
        hit for hit in fallback_summary.hits if "第二人称讲解台词偏显眼" in hit
    ]
    preferred_lecture_hits = [
        hit for hit in preferred_summary.hits if "第二人称讲解台词偏显眼" in hit
    ]
    if fallback_lecture_hits and not preferred_lecture_hits and preferred_summary.score <= fallback_summary.score:
        return preferred_markdown, preferred_title
    if fallback_summary.score <= max(26, preferred_summary.score + 12):
        return fallback_markdown, fallback_title
    return preferred_markdown, preferred_title


def _build_over_smoothing_retry_instruction(
    *,
    base_instruction: str,
    source_markdown: str,
    excessive_openers: list[str],
) -> str:
    retry_notes = [
        "上一次改写虽然保住了结构，但把原稿磨得太顺，出现了偏统一的公众号成稿腔。",
        f"这次不要再补这些泛感慨过渡句：{' / '.join(excessive_openers[:4])}。",
    ]

    heading_anchors = _extract_structure_heading_anchors(source_markdown)
    if heading_anchors:
        retry_notes.append(
            "继续围绕这些原稿锚点推进："
            + "；".join(f"{heading} -> {anchor}" for heading, anchor in heading_anchors[:4])
            + "。"
        )

    retry_notes.append("不要用“很多时候”“说到底”“人总是这样”“我们总以为”先做总括再解释。")
    retry_notes.append("宁可保留原稿里更直一点的判断，也不要把每段都磨成成熟顺滑的总结句。")
    return base_instruction.strip() + " " + "".join(retry_notes)


def _should_retry_for_remaining_ai_flavor(
    *,
    source_title: str,
    source_markdown: str,
    candidate_title: str,
    candidate_markdown: str,
) -> bool:
    if _looks_like_tracked_article_fragment_chain_candidate(candidate_markdown):
        return False

    source_summary = evaluate_ai_flavor_risk(title=source_title, body_markdown=source_markdown)
    candidate_summary = evaluate_ai_flavor_risk(title=candidate_title, body_markdown=candidate_markdown)
    residual_not_ab = extract_not_ab_skeletons(candidate_markdown)
    residual_openers = extract_generic_reflective_openers(candidate_markdown)
    residual_cliches = extract_growth_cliches(candidate_markdown)
    residual_rebound_tails = extract_rebound_explainer_tails(candidate_markdown)
    residual_short_judgments = extract_short_judgment_paragraphs(candidate_markdown)
    residual_cadence_pairs = count_short_long_cadence_pairs(candidate_markdown)
    residual_embedded_banners = extract_embedded_banner_paragraphs(candidate_markdown)
    residual_quote_paragraphs = extract_isolated_quote_paragraphs(candidate_markdown)
    residual_explanatory_paragraphs = extract_explanatory_bridge_paragraphs(candidate_markdown)
    explainer_shell_hits = [
        hit
        for hit in candidate_summary.hits
        if "第二人称整篇讲解密度偏高" in hit or "中长段整篇过于齐整" in hit
    ]
    opening_explainer_hits = [
        hit for hit in candidate_summary.hits if "开头讲稿式先答后证" in hit
    ]
    if candidate_summary.score < 20:
        if opening_explainer_hits and candidate_summary.score >= 16:
            return True
        if len(explainer_shell_hits) >= 2 and candidate_summary.score >= 28:
            return True
        return False
    if len(candidate_summary.hits) < 2:
        if (
            not residual_not_ab
            and len(residual_openers) < 2
            and not residual_cliches
            and not residual_rebound_tails
            and len(residual_short_judgments) < 3
            and residual_cadence_pairs < 2
            and len(residual_embedded_banners) < 2
            and len(residual_quote_paragraphs) < 2
            and len(residual_explanatory_paragraphs) < 2
        ):
            return False
    if len(explainer_shell_hits) >= 2 and candidate_summary.score >= 28:
        return True
    if (
        any("第二人称讲理腔偏重" in hit for hit in candidate_summary.hits)
        and any("中长段标准讲理排布" in hit for hit in candidate_summary.hits)
        and candidate_summary.score >= 26
    ):
        return True
    if len(residual_not_ab) >= 4:
        return True
    if len(residual_rebound_tails) >= 2:
        return True
    if len(residual_short_judgments) >= 4:
        return True
    if residual_cadence_pairs >= 2:
        return True
    if len(residual_embedded_banners) >= 2:
        return True
    if len(residual_quote_paragraphs) >= 2 or len(residual_explanatory_paragraphs) >= 2:
        return True
    if source_summary.score >= 45:
        return True
    if (residual_not_ab or len(residual_openers) >= 2 or residual_cliches or residual_rebound_tails) and (
        candidate_summary.score >= 20 and candidate_summary.score >= source_summary.score + 8
    ):
        return True
    if (
        len(residual_short_judgments) >= 3
        or residual_cadence_pairs >= 1
        or len(residual_embedded_banners) >= 2
        or len(residual_quote_paragraphs) >= 2
        or len(residual_explanatory_paragraphs) >= 2
    ) and (
        candidate_summary.score >= 20 and candidate_summary.score >= source_summary.score + 6
    ):
        return True
    if candidate_summary.score >= 35 and candidate_summary.score >= source_summary.score + 10:
        return True
    return False


def _should_retry_for_final_ai_flavor_cleanup(
    *,
    candidate_title: str,
    candidate_markdown: str,
) -> bool:
    candidate_summary = evaluate_ai_flavor_risk(title=candidate_title, body_markdown=candidate_markdown)
    residual_not_ab = extract_not_ab_skeletons(candidate_markdown)
    residual_openers = extract_generic_reflective_openers(candidate_markdown)
    residual_cliches = extract_growth_cliches(candidate_markdown)
    residual_rebound_tails = extract_rebound_explainer_tails(candidate_markdown)
    residual_short_judgments = extract_short_judgment_paragraphs(candidate_markdown)
    residual_cadence_pairs = count_short_long_cadence_pairs(candidate_markdown)
    residual_embedded_banners = extract_embedded_banner_paragraphs(candidate_markdown)
    residual_quote_paragraphs = extract_isolated_quote_paragraphs(candidate_markdown)
    residual_explanatory_paragraphs = extract_explanatory_bridge_paragraphs(candidate_markdown)
    repeated_quote_paragraphs = len(residual_quote_paragraphs) if len(residual_quote_paragraphs) >= 2 else 0
    repeated_explanatory_paragraphs = (
        len(residual_explanatory_paragraphs) if len(residual_explanatory_paragraphs) >= 2 else 0
    )
    residual_total = len(residual_not_ab) + len(residual_openers) + len(residual_cliches) + len(residual_rebound_tails)
    residual_shape_total = residual_total + repeated_quote_paragraphs + repeated_explanatory_paragraphs
    explainer_shell_hits = [
        hit
        for hit in candidate_summary.hits
        if "第二人称整篇讲解密度偏高" in hit or "中长段整篇过于齐整" in hit
    ]
    opening_explainer_hits = [
        hit for hit in candidate_summary.hits if "开头讲稿式先答后证" in hit
    ]
    lecture_line_hits = [
        hit for hit in candidate_summary.hits if "第二人称讲解台词偏显眼" in hit
    ]
    explainer_shell_only_residue = (
        len(explainer_shell_hits) >= 2
        and residual_shape_total == 0
        and len(residual_short_judgments) <= 1
        and residual_cadence_pairs == 0
        and len(residual_embedded_banners) == 0
        and candidate_summary.score >= 28
    )
    lecture_line_only_residue = (
        bool(lecture_line_hits)
        and residual_shape_total == 0
        and len(residual_short_judgments) <= 2
        and residual_cadence_pairs == 0
        and len(residual_embedded_banners) == 0
        and candidate_summary.score >= 16
    )
    opening_explainer_only_residue = (
        bool(opening_explainer_hits)
        and residual_shape_total == 0
        and len(residual_short_judgments) <= 1
        and residual_cadence_pairs == 0
        and len(residual_embedded_banners) == 0
        and candidate_summary.score >= 16
    )
    connector_only_residue = (
        residual_shape_total == 0
        and not residual_short_judgments
        and residual_cadence_pairs == 0
        and not residual_embedded_banners
        and any("解释连接词偏多" in hit for hit in candidate_summary.hits)
        and candidate_summary.score <= 18
    )
    minor_residue_only = (
        residual_shape_total == 0
        and len(residual_embedded_banners) == 0
        and len(residual_short_judgments) <= 2
        and residual_cadence_pairs <= 2
        and candidate_summary.score <= 22
    )
    allow_four_not_ab_only = (
        residual_total == 4
        and len(residual_not_ab) == 4
        and not residual_openers
        and not residual_cliches
        and not residual_rebound_tails
        and candidate_summary.score <= 42
    )
    allow_five_not_ab_only = (
        residual_total == 5
        and len(residual_not_ab) == 5
        and not residual_openers
        and not residual_cliches
        and not residual_rebound_tails
        and candidate_summary.score <= 36
    )

    if candidate_summary.score > 50:
        return False
    if explainer_shell_only_residue:
        return True
    if lecture_line_only_residue:
        return True
    if opening_explainer_only_residue:
        return True
    if connector_only_residue or minor_residue_only:
        return False
    if (
        residual_shape_total == 0
        and len(residual_rebound_tails) == 0
        and len(residual_short_judgments) < 2
        and residual_cadence_pairs == 0
        and len(residual_embedded_banners) == 0
    ):
        return False
    if residual_shape_total > 3 and not (allow_four_not_ab_only or allow_five_not_ab_only):
        return False
    if len(residual_not_ab) > 3 and not (allow_four_not_ab_only or allow_five_not_ab_only):
        return False
    if len(residual_openers) > 2 or len(residual_cliches) > 2 or len(residual_rebound_tails) > 4:
        return False
    if len(residual_short_judgments) > 4 or residual_cadence_pairs > 2:
        return False
    if len(residual_embedded_banners) > 2:
        return False
    if repeated_quote_paragraphs > 2 or repeated_explanatory_paragraphs > 2:
        return False
    return True


def _extract_non_heading_paragraphs(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    for part in re.split(r"\n\s*\n", markdown):
        normalized = part.strip()
        if not normalized or normalized.startswith("#"):
            continue
        paragraphs.append(normalized)
    return paragraphs


def _collapse_short_judgment_residue(*, title: str, body_markdown: str) -> str:
    original_short_paragraphs = extract_short_judgment_paragraphs(body_markdown)
    if len(original_short_paragraphs) <= 2:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    def _is_short_judgment_block(block: str) -> bool:
        normalized = block.strip()
        if _looks_like_structure_heading(normalized):
            return False
        return extract_short_judgment_paragraphs(normalized) == [normalized]

    def _short_judgment_count(items: list[str]) -> int:
        return sum(1 for item in items if _is_short_judgment_block(item))

    short_count = _short_judgment_count(body_blocks)
    if short_count <= 2:
        return body_markdown

    changed = False
    index = len(body_blocks) - 1
    while short_count > 2 and index >= 0:
        current_block = body_blocks[index].strip()
        if not _is_short_judgment_block(current_block):
            index -= 1
            continue

        if index == len(body_blocks) - 1 and index > 0:
            body_blocks[index - 1] = body_blocks[index - 1].rstrip() + current_block
            del body_blocks[index]
            changed = True
        elif index + 1 < len(body_blocks):
            body_blocks[index] = current_block + body_blocks[index + 1].lstrip()
            del body_blocks[index + 1]
            changed = True
        elif index > 0:
            body_blocks[index - 1] = body_blocks[index - 1].rstrip() + current_block
            del body_blocks[index]
            changed = True
        else:
            break

        short_count = _short_judgment_count(body_blocks)
        index = min(index, len(body_blocks) - 1)

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + body_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)
    collapsed_short_paragraphs = extract_short_judgment_paragraphs(collapsed_markdown)
    if len(collapsed_short_paragraphs) >= len(original_short_paragraphs):
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_time_chain_shell_residue(*, title: str, body_markdown: str) -> str:
    original_burden = _article_shell_burden(body_markdown)
    if original_burden[0] < 8 or original_burden[1] < 10 or original_burden[6] < 4:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 3:
        return body_markdown

    time_chain_prefixes = (
        "电梯",
        "楼梯口",
        "中午",
        "饭局",
        "回家路上",
        "洗完澡",
        "夜里",
        "晚上",
        "周末",
        "早上",
    )

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    def _is_time_chain_lead(block: str) -> bool:
        return block.strip().startswith(time_chain_prefixes)

    def _is_ultra_short_single_line(block: str) -> bool:
        normalized = block.strip()
        compact = _compact_len(normalized)
        if not 4 <= compact <= 18:
            return False
        return len([item for item in re.split(r"[。！？!?；;\n]", normalized) if item.strip()]) == 1

    changed = False

    index = 1
    while index < len(body_blocks) - 1:
        current_block = body_blocks[index].strip()
        if not _is_ultra_short_single_line(current_block):
            index += 1
            continue

        previous_block = body_blocks[index - 1].strip()
        next_block = body_blocks[index + 1].strip()
        if _compact_len(previous_block) >= 30 or _compact_len(next_block) >= 30:
            body_blocks[index - 1] = body_blocks[index - 1].rstrip() + current_block
            del body_blocks[index]
            changed = True
            continue
        index += 1

    index = 1
    while index < len(body_blocks):
        current_block = body_blocks[index].strip()
        previous_block = body_blocks[index - 1].strip()
        if (
            _is_time_chain_lead(current_block)
            and not _is_time_chain_lead(previous_block)
            and 10 <= _compact_len(previous_block) <= 54
            and 35 <= _compact_len(current_block) <= 140
        ):
            body_blocks[index - 1] = body_blocks[index - 1].rstrip() + current_block
            del body_blocks[index]
            changed = True
            continue
        index += 1

    if len(body_blocks) >= 3:
        tail_block = body_blocks[-1].strip()
        tail_time_block = body_blocks[-2].strip()
        tail_anchor_block = body_blocks[-3].strip()
        if (
            _is_time_chain_lead(tail_time_block)
            and _compact_len(tail_time_block) <= 72
            and _compact_len(tail_block) <= 60
            and _compact_len(tail_anchor_block) >= 60
            and not _is_time_chain_lead(tail_anchor_block)
        ):
            body_blocks[-3] = tail_anchor_block.rstrip() + tail_time_block + tail_block
            del body_blocks[-1]
            del body_blocks[-1]
            changed = True

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + body_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)
    collapsed_burden = _article_shell_burden(collapsed_markdown)
    if (
        collapsed_burden[0] > original_burden[0]
        or (collapsed_burden[0] == original_burden[0] and collapsed_burden[1] >= original_burden[1])
    ):
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_embedded_banner_shell_residue(*, title: str, body_markdown: str) -> str:
    original_embedded_banners = extract_embedded_banner_paragraphs(body_markdown)
    if len(original_embedded_banners) < 3:
        return body_markdown

    original_burden = _article_shell_burden(body_markdown)
    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 5:
        return body_markdown

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    changed = False
    for index, block in enumerate(body_blocks):
        collapsed_block = _collapse_banner_lead_sentence_block(block)
        if collapsed_block is None:
            continue
        body_blocks[index] = collapsed_block
        changed = True

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + body_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)
    collapsed_embedded_banners = extract_embedded_banner_paragraphs(collapsed_markdown)
    if len(collapsed_embedded_banners) >= len(original_embedded_banners):
        return body_markdown

    collapsed_burden = _article_shell_burden(collapsed_markdown)
    if collapsed_burden[0] >= original_burden[0]:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_explanatory_bridge_residue(*, title: str, body_markdown: str) -> str:
    original_explanatory = extract_explanatory_bridge_paragraphs(body_markdown)
    original_bridging = extract_bridging_summary_paragraphs(body_markdown)
    bridge_lead_pattern = re.compile(
        r"^(?:更磨人的是|更麻烦的是|麻烦就在这里|难受的地方就在这儿|这也是为什么|问题也常常从这里变重|这种顺手往后放)",
        re.UNICODE,
    )

    def _count_lead_style_bridges(items: list[str]) -> int:
        count = 0
        for block in items:
            normalized = block.strip()
            compact = len(re.sub(r"\s+", "", normalized))
            sentences = len([item for item in re.split(r"[。！？!?；;\n]", normalized) if item.strip()])
            if compact <= 34 and sentences == 1 and bridge_lead_pattern.match(normalized.rstrip("。！？!?；;")) is not None:
                count += 1
        return count

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 3:
        return body_markdown

    lead_hits = _count_lead_style_bridges(body_blocks)

    if len(original_explanatory) + len(original_bridging) + lead_hits < 1:
        return body_markdown

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    def _is_bridge_block(block: str) -> bool:
        normalized = block.strip()
        if not normalized or _looks_like_structure_heading(normalized):
            return False
        sample = f"# 标题\n\n{normalized}"
        if (
            extract_explanatory_bridge_paragraphs(sample) == [normalized]
            or extract_bridging_summary_paragraphs(sample) == [normalized]
            or extract_short_judgment_paragraphs(sample) == [normalized]
        ):
            return True
        compact = _compact_len(normalized)
        sentences = len([item for item in re.split(r"[。！？!?；;\n]", normalized) if item.strip()])
        return compact <= 34 and sentences == 1 and bridge_lead_pattern.match(normalized.rstrip("。！？!?；;")) is not None

    changed = False
    index = 0
    while index < len(body_blocks):
        current = body_blocks[index].strip()
        if not _is_bridge_block(current):
            index += 1
            continue

        merged = False
        if index + 1 < len(body_blocks) and _compact_len(body_blocks[index + 1]) >= 36:
            body_blocks[index] = current.rstrip("。！？!?；;") + "，" + body_blocks[index + 1].lstrip()
            del body_blocks[index + 1]
            merged = True
        elif index > 0 and _compact_len(body_blocks[index - 1]) >= 24:
            body_blocks[index - 1] = body_blocks[index - 1].rstrip() + current
            del body_blocks[index]
            index -= 1
            merged = True

        if not merged:
            index += 1
            continue

        changed = True

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + body_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)

    collapsed_explanatory = extract_explanatory_bridge_paragraphs(collapsed_markdown)
    collapsed_bridging = extract_bridging_summary_paragraphs(collapsed_markdown)
    collapsed_lead_hits = _count_lead_style_bridges(body_blocks)
    if (
        len(collapsed_explanatory) + len(collapsed_bridging) + collapsed_lead_hits
        >= len(original_explanatory) + len(original_bridging) + lead_hits
    ):
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_banner_lead_sentence_block(block: str) -> str | None:
    normalized = block.strip()
    if not normalized:
        return None

    hits = extract_embedded_banner_paragraphs(f"# 标题\n\n{normalized}")
    if not hits:
        return None

    match = re.match(r"^\s*(.+?[。！？!?；;])\s*(.+)$", normalized, re.S)
    if not match:
        return None

    first_sentence = match.group(1).strip()
    rest = match.group(2).lstrip("，,、 \t\r\n")
    if first_sentence not in hits or not rest:
        return None

    first_len = len(re.sub(r"\s+", "", first_sentence.rstrip("。！？!?；;")))
    rest_len = len(re.sub(r"\s+", "", rest))
    if first_len > 28 or rest_len < 20:
        return None

    return first_sentence.rstrip("。！？!?；;") + "，" + rest


def _collapse_short_long_cadence_residue(*, title: str, body_markdown: str) -> str:
    original_pairs = count_short_long_cadence_pairs(body_markdown)
    if original_pairs < 2:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 3:
        return body_markdown

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    def _is_short_judgment_block(block: str) -> bool:
        normalized = block.strip()
        if _looks_like_structure_heading(normalized):
            return False
        return extract_short_judgment_paragraphs(normalized) == [normalized]

    changed = False
    index = 1
    while index < len(body_blocks) - 1:
        current_block = body_blocks[index].strip()
        previous_block = body_blocks[index - 1].strip()
        next_block = body_blocks[index + 1].strip()
        if not _is_short_judgment_block(current_block):
            index += 1
            continue
        if _compact_len(previous_block) < 60 or _compact_len(next_block) < 60:
            index += 1
            continue
        body_blocks[index - 1] = body_blocks[index - 1].rstrip() + current_block
        del body_blocks[index]
        changed = True
        continue

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + body_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)
    collapsed_pairs = count_short_long_cadence_pairs(collapsed_markdown)
    if collapsed_pairs >= original_pairs:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_leading_short_long_cadence_residue(*, title: str, body_markdown: str) -> str:
    original_pairs = count_short_long_cadence_pairs(body_markdown)
    if original_pairs < 1:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 2:
        return body_markdown

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    first_block = body_blocks[0].strip()
    second_block = body_blocks[1].strip()
    if extract_short_judgment_paragraphs(first_block) != [first_block]:
        return body_markdown
    if _compact_len(second_block) < 60:
        return body_markdown

    sentence_match = re.match(r"^\s*(.+?[。！？!?；;])\s*(.+)$", second_block, re.S)
    if not sentence_match:
        return body_markdown

    leading_sentence = sentence_match.group(1).strip()
    remaining_second_block = sentence_match.group(2).strip()
    if not 8 <= _compact_len(leading_sentence) <= 36:
        return body_markdown
    if _compact_len(remaining_second_block) < 40:
        return body_markdown

    candidate_blocks = body_blocks[:]
    candidate_blocks[0] = candidate_blocks[0].rstrip() + leading_sentence
    candidate_blocks[1] = remaining_second_block
    rebuilt_blocks = ([heading_block] if heading_block else []) + candidate_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)

    collapsed_pairs = count_short_long_cadence_pairs(collapsed_markdown)
    if collapsed_pairs >= original_pairs:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score >= original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_over_segmented_shell_residue(*, title: str, body_markdown: str) -> str:
    original_burden = _article_shell_burden(body_markdown)
    if original_burden[0] < 14 or original_burden[1] < 18 or original_burden[5] < 10:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 8:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    current_blocks = body_blocks[:]
    current_burden = original_burden
    current_summary = original_summary
    target_paragraph_count = 15 if original_burden[1] >= 20 else 16
    max_merges = min(8, max(3, original_burden[1] - target_paragraph_count))
    changed = False

    hinge_lead_pattern = re.compile(
        r"^(?:"
        r"可|但|只是|不过|因为|于是|所以|因此|其实|"
        r"先别问为什么|这句解释太顺手了|更麻烦的是|麻烦就麻烦在|"
        r"有时她也会察觉到不对|真正耗人的|这种消耗|这也是为什么|"
        r"原来不是|后面的事|屋里安静下来以后|能让人往回退半步的|"
        r"难的地方就在这儿|关系里的缺席|这条线常常就是这么出来的"
        r")"
    )

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    def _sentence_count(block: str) -> int:
        return len([item for item in re.split(r"[。！？!?；;\n]", block.strip()) if item.strip()])

    def _first_sentence(block: str) -> str:
        return re.split(r"[。！？!?；;\n]", block.strip(), maxsplit=1)[0].strip()

    def _is_ultra_short_block(block: str) -> bool:
        normalized = block.strip()
        compact = _compact_len(normalized)
        if not 1 <= compact <= 28:
            return False
        if _sentence_count(normalized) > 2:
            return False
        return not re.search(r"[：:]", normalized)

    def _is_mergeable_hinge_block(block: str) -> bool:
        normalized = block.strip()
        compact = _compact_len(normalized)
        sentences = _sentence_count(normalized)
        first_sentence = _first_sentence(normalized)
        first_sentence_len = _compact_len(first_sentence.rstrip("。！？!?；;"))
        if _is_ultra_short_block(normalized):
            return True
        if compact <= 55 and sentences <= 2:
            return True
        if compact <= 120 and sentences <= 3 and hinge_lead_pattern.match(first_sentence):
            return True
        if compact <= 170 and sentences <= 6 and first_sentence_len <= 28 and hinge_lead_pattern.match(first_sentence):
            return True
        return False

    for _ in range(max_merges):
        best_candidate: tuple[int, list[str], tuple[int, int, int, int, int, int, int], object] | None = None

        for index, block in enumerate(current_blocks):
            current_block = block.strip()
            if not _is_mergeable_hinge_block(current_block):
                continue

            current_len = _compact_len(current_block)
            prefers_right = hinge_lead_pattern.match(_first_sentence(current_block)) is not None

            for direction in (-1, 1):
                neighbor_index = index + direction
                if neighbor_index < 0 or neighbor_index >= len(current_blocks):
                    continue

                neighbor_block = current_blocks[neighbor_index].strip()
                neighbor_len = _compact_len(neighbor_block)
                if neighbor_len < 40 or current_len + neighbor_len > 300:
                    continue

                candidate_blocks = current_blocks[:]
                if direction == -1:
                    candidate_blocks[index - 1] = candidate_blocks[index - 1].rstrip() + current_block
                    del candidate_blocks[index]
                    merged_block = candidate_blocks[index - 1]
                else:
                    candidate_blocks[index] = current_block + candidate_blocks[index + 1].lstrip()
                    del candidate_blocks[index + 1]
                    merged_block = candidate_blocks[index]

                candidate_markdown = "\n\n".join(([heading_block] if heading_block else []) + candidate_blocks)
                candidate_burden = _article_shell_burden(candidate_markdown)
                if candidate_burden[0] > current_burden[0] or candidate_burden[1] >= current_burden[1]:
                    continue

                candidate_summary = evaluate_ai_flavor_risk(title=title, body_markdown=candidate_markdown)
                if candidate_summary.score > current_summary.score:
                    continue

                merged_len = _compact_len(merged_block)
                value = (current_summary.score - candidate_summary.score) * 1000
                value += (current_burden[0] - candidate_burden[0]) * 100
                value += (current_burden[1] - candidate_burden[1]) * 20
                value += max(0, 24 - abs(merged_len - 170) // 8)
                if _is_ultra_short_block(current_block):
                    value += 30
                if prefers_right and direction == 1:
                    value += 12
                if not prefers_right and direction == -1:
                    value += 6
                if candidate_burden[1] <= target_paragraph_count:
                    value += 200

                if best_candidate is None or value > best_candidate[0]:
                    best_candidate = (value, candidate_blocks, candidate_burden, candidate_summary)

        if best_candidate is None:
            break

        _, current_blocks, current_burden, current_summary = best_candidate
        changed = True
        if current_burden[1] <= target_paragraph_count:
            break

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + current_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)
    collapsed_burden = _article_shell_burden(collapsed_markdown)
    if (
        collapsed_burden[0] > original_burden[0]
        or collapsed_burden[1] >= original_burden[1]
        or collapsed_burden[1] > original_burden[1] - 2
    ):
        return body_markdown

    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown

    return collapsed_markdown


def _collapse_light_segmented_shell_residue(*, title: str, body_markdown: str) -> str:
    original_burden = _article_shell_burden(body_markdown)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    dense_explainer_shell = any("整篇解释壳偏密" in hit for hit in original_summary.hits)
    if original_burden[0] < 5 or original_burden[1] < 12:
        if not (dense_explainer_shell and original_burden[1] >= 10):
            return body_markdown
    elif original_burden[1] < 12 and not dense_explainer_shell:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 6:
        return body_markdown

    current_blocks = body_blocks[:]
    current_burden = original_burden
    current_summary = original_summary
    changed = False

    hinge_lead_pattern = re.compile(
        r"^(?:"
        r"因为|所以|可是|但|不过|只是|于是|而且|"
        r"更麻烦的是|真正耗人的|难的地方就在这儿|关系里的缺席|"
        r"很多人就是从这种地方开始变慢的|因为她还没有倒下|"
        r"有些代价是延迟出现的|后面的事|屋里安静下来以后|"
        r"这句话听上去很体谅|原来不是"
        r")",
        re.UNICODE,
    )

    def _compact_len(block: str) -> int:
        return len(re.sub(r"\s+", "", block.strip()))

    def _sentence_count(block: str) -> int:
        return len([item for item in re.split(r"[。！？!?；;\n]", block.strip()) if item.strip()])

    def _first_sentence(block: str) -> str:
        return re.split(r"[。！？!?；;\n]", block.strip(), maxsplit=1)[0].strip()

    def _is_short_judgment_block(block: str) -> bool:
        normalized = block.strip()
        return extract_short_judgment_paragraphs(normalized) == [normalized]

    def _is_mergeable_light_hinge(block: str, *, index: int, total: int) -> bool:
        normalized = block.strip()
        compact = _compact_len(normalized)
        if not normalized or compact > 120:
            return False

        if _is_short_judgment_block(normalized):
            return True

        if extract_explanatory_bridge_paragraphs(f"# 标题\n\n{normalized}") == [normalized]:
            return True

        if extract_bridging_summary_paragraphs(f"# 标题\n\n{normalized}") == [normalized]:
            return True

        sentences = _sentence_count(normalized)
        if index == total - 1 and compact <= 110 and sentences <= 3:
            return True

        if compact <= 60 and sentences <= 2:
            return True

        first_sentence = _first_sentence(normalized)
        return compact <= 140 and sentences <= 3 and hinge_lead_pattern.match(first_sentence) is not None

    def _is_mergeable_scene_shell(block: str) -> bool:
        normalized = block.strip()
        compact = _compact_len(normalized)
        if not normalized or not 68 <= compact <= 150:
            return False
        if _looks_like_structure_heading(normalized):
            return False
        if _is_short_judgment_block(normalized):
            return False
        if extract_explanatory_bridge_paragraphs(f"# 标题\n\n{normalized}") == [normalized]:
            return False
        if extract_bridging_summary_paragraphs(f"# 标题\n\n{normalized}") == [normalized]:
            return False
        if extract_embedded_banner_paragraphs(f"# 标题\n\n{normalized}"):
            return False

        sentences = _sentence_count(normalized)
        return 2 <= sentences <= 5

    def _is_dense_explainer_block(block: str) -> bool:
        normalized = block.strip()
        compact = _compact_len(normalized)
        if not 90 <= compact <= 240:
            return False
        if _looks_like_structure_heading(normalized):
            return False
        first_sentence = _first_sentence(normalized)
        first_len = _compact_len(first_sentence.rstrip("。！？!?；;"))
        if not 8 <= first_len <= 32:
            return False
        if normalized.count("；") + normalized.count(";") < 1:
            return False
        sentences = _sentence_count(normalized)
        return 3 <= sentences <= 7

    for _ in range(4):
        best_candidate: tuple[int, list[str], tuple[int, int, int, int, int, int, int], object] | None = None

        for index, block in enumerate(current_blocks):
            collapsed_block = _collapse_banner_lead_sentence_block(block)
            if collapsed_block is None or collapsed_block == block:
                continue

            candidate_blocks = current_blocks[:]
            candidate_blocks[index] = collapsed_block
            candidate_markdown = "\n\n".join(([heading_block] if heading_block else []) + candidate_blocks)
            candidate_burden = _article_shell_burden(candidate_markdown)
            candidate_summary = evaluate_ai_flavor_risk(title=title, body_markdown=candidate_markdown)

            if candidate_summary.score > current_summary.score:
                continue
            if candidate_burden[0] > current_burden[0] or candidate_burden[1] > current_burden[1]:
                continue
            if candidate_burden[0] == current_burden[0] and candidate_summary.score == current_summary.score:
                continue

            value = (current_summary.score - candidate_summary.score) * 1000
            value += (current_burden[0] - candidate_burden[0]) * 100
            value += 80
            if best_candidate is None or value > best_candidate[0]:
                best_candidate = (value, candidate_blocks, candidate_burden, candidate_summary)

        total_blocks = len(current_blocks)
        for index, block in enumerate(current_blocks):
            current_block = block.strip()
            if not _is_mergeable_light_hinge(current_block, index=index, total=total_blocks):
                continue

            current_len = _compact_len(current_block)
            for direction in (-1, 1):
                neighbor_index = index + direction
                if neighbor_index < 0 or neighbor_index >= len(current_blocks):
                    continue

                neighbor_block = current_blocks[neighbor_index].strip()
                neighbor_len = _compact_len(neighbor_block)
                if neighbor_len < 35 or current_len + neighbor_len > 320:
                    continue

                candidate_blocks = current_blocks[:]
                if direction == -1:
                    candidate_blocks[index - 1] = candidate_blocks[index - 1].rstrip() + current_block
                    del candidate_blocks[index]
                else:
                    candidate_blocks[index] = current_block + candidate_blocks[index + 1].lstrip()
                    del candidate_blocks[index + 1]

                candidate_markdown = "\n\n".join(([heading_block] if heading_block else []) + candidate_blocks)
                candidate_burden = _article_shell_burden(candidate_markdown)
                candidate_summary = evaluate_ai_flavor_risk(title=title, body_markdown=candidate_markdown)

                if candidate_summary.score > current_summary.score:
                    continue
                if candidate_burden[0] > current_burden[0] or candidate_burden[1] >= current_burden[1]:
                    continue

                value = (current_summary.score - candidate_summary.score) * 1000
                value += (current_burden[0] - candidate_burden[0]) * 100
                value += (current_burden[1] - candidate_burden[1]) * 25
                value += max(0, 18 - abs((current_len + neighbor_len) - 150) // 10)
                if _is_short_judgment_block(current_block):
                    value += 30
                if index == total_blocks - 1:
                    value += 20
                if direction == 1 and hinge_lead_pattern.match(_first_sentence(current_block)):
                    value += 12

                if best_candidate is None or value > best_candidate[0]:
                    best_candidate = (value, candidate_blocks, candidate_burden, candidate_summary)

        if dense_explainer_shell:
            for index in range(len(current_blocks) - 1):
                left_block = current_blocks[index].strip()
                right_block = current_blocks[index + 1].strip()
                if not _is_dense_explainer_block(left_block) or not _is_dense_explainer_block(right_block):
                    continue

                left_len = _compact_len(left_block)
                right_len = _compact_len(right_block)
                combined_len = left_len + right_len
                if combined_len < 180 or combined_len > 360:
                    continue

                candidate_blocks = current_blocks[:]
                candidate_blocks[index] = candidate_blocks[index].rstrip() + candidate_blocks[index + 1].lstrip()
                del candidate_blocks[index + 1]

                candidate_markdown = "\n\n".join(([heading_block] if heading_block else []) + candidate_blocks)
                candidate_burden = _article_shell_burden(candidate_markdown)
                candidate_summary = evaluate_ai_flavor_risk(title=title, body_markdown=candidate_markdown)

                if candidate_summary.score > current_summary.score:
                    continue
                if candidate_burden[0] > current_burden[0] or candidate_burden[1] >= current_burden[1]:
                    continue

                value = (current_summary.score - candidate_summary.score) * 1000
                value += (current_burden[0] - candidate_burden[0]) * 120
                value += (current_burden[1] - candidate_burden[1]) * 40
                value += max(0, 26 - abs(combined_len - 260) // 10)
                if candidate_burden[5] < current_burden[5]:
                    value += 60
                if candidate_summary.score == current_summary.score:
                    value += 30

                if best_candidate is None or value > best_candidate[0]:
                    best_candidate = (value, candidate_blocks, candidate_burden, candidate_summary)

        if current_burden[1] >= 14 and current_burden[5] >= 8:
            for index in range(len(current_blocks) - 1):
                left_block = current_blocks[index].strip()
                right_block = current_blocks[index + 1].strip()
                if not _is_mergeable_scene_shell(left_block) or not _is_mergeable_scene_shell(right_block):
                    continue

                left_len = _compact_len(left_block)
                right_len = _compact_len(right_block)
                combined_len = left_len + right_len
                if combined_len < 135 or combined_len > 255:
                    continue

                candidate_blocks = current_blocks[:]
                candidate_blocks[index] = candidate_blocks[index].rstrip() + current_blocks[index + 1].lstrip()
                del candidate_blocks[index + 1]

                candidate_markdown = "\n\n".join(([heading_block] if heading_block else []) + candidate_blocks)
                candidate_burden = _article_shell_burden(candidate_markdown)
                candidate_summary = evaluate_ai_flavor_risk(title=title, body_markdown=candidate_markdown)

                if candidate_summary.score > current_summary.score:
                    continue
                if candidate_burden[0] > current_burden[0] or candidate_burden[1] >= current_burden[1]:
                    continue

                value = (current_summary.score - candidate_summary.score) * 1000
                value += (current_burden[0] - candidate_burden[0]) * 100
                value += (current_burden[1] - candidate_burden[1]) * 35
                value += max(0, 24 - abs(combined_len - 195) // 8)
                if candidate_burden[5] < current_burden[5]:
                    value += 40
                if index <= 1:
                    value += 8

                if best_candidate is None or value > best_candidate[0]:
                    best_candidate = (value, candidate_blocks, candidate_burden, candidate_summary)

        if best_candidate is None:
            break

        _, current_blocks, current_burden, current_summary = best_candidate
        changed = True
        if current_burden[1] <= (10 if dense_explainer_shell else 12):
            break

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + current_blocks
    collapsed_markdown = "\n\n".join(rebuilt_blocks)
    collapsed_burden = _article_shell_burden(collapsed_markdown)
    collapsed_summary = evaluate_ai_flavor_risk(title=title, body_markdown=collapsed_markdown)
    if collapsed_summary.score > original_summary.score:
        return body_markdown
    if collapsed_burden[0] >= original_burden[0] or collapsed_burden[1] >= original_burden[1]:
        return body_markdown

    return collapsed_markdown


def _soften_structural_ladder_residue(*, title: str, body_markdown: str) -> str:
    pattern = re.compile(
        r"先是([^。！？!?；;\n]{1,80})。后来([^。！？!?；;\n]{1,80})。再后来[，,、]?([^。！？!?；;\n]{1,80})。",
        re.UNICODE,
    )
    if not pattern.search(body_markdown):
        return body_markdown

    softened_markdown = pattern.sub(
        lambda match: f"先是{match.group(1).strip()}，接着{match.group(2).strip()}，最后{match.group(3).strip()}。",
        body_markdown,
    )
    if softened_markdown == body_markdown:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    softened_summary = evaluate_ai_flavor_risk(title=title, body_markdown=softened_markdown)
    if softened_summary.score > original_summary.score:
        return body_markdown

    return softened_markdown


def _soften_direct_address_lecture_residue(*, title: str, body_markdown: str) -> str:
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    if original_summary.score > 20:
        return body_markdown
    original_lecture_hits = [
        hit for hit in original_summary.hits if "第二人称讲解台词偏显眼" in hit
    ]
    if not original_lecture_hits:
        return body_markdown
    if any("不是A，是B" in hit for hit in original_summary.hits):
        return body_markdown
    if any("解释连接词偏多" in hit for hit in original_summary.hits):
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if not body_blocks:
        return body_markdown

    question_prefix_pattern = re.compile(r"^你有没有过这种阶段[：:，,]?\s*", re.UNICODE)
    answer_prefix_pattern = re.compile(r"^答案我先(?:直接)?告诉你[，,]?\s*", re.UNICODE)
    if_you_pattern = re.compile(r"^如果你这段时间已经开始", re.UNICODE)
    remove_sentence_patterns = (
        re.compile(r"答案我先(?:直接)?告诉你[，,]?[^。！？!?]*[。！？!?]?", re.UNICODE),
        re.compile(r"你不需要先倒下，才有资格停[。！？!?]?", re.UNICODE),
    )
    scene_line_pattern = re.compile(r"^你看见了，也知道该回谁[，,]", re.UNICODE)
    compact_len = lambda value: len(re.sub(r"\s+", "", value))

    changed = False
    softened_blocks: list[str] = []
    for block in body_blocks:
        normalized = block.strip()
        softened_block = normalized

        softened_block = question_prefix_pattern.sub("", softened_block)
        softened_block = answer_prefix_pattern.sub("", softened_block)
        for pattern in remove_sentence_patterns:
            softened_block = pattern.sub("", softened_block)
        softened_block = scene_line_pattern.sub("", softened_block)
        if if_you_pattern.match(softened_block):
            softened_block = if_you_pattern.sub("已经开始", softened_block)

        softened_block = re.sub(r"(^|[。！？!?；;])\s*更常见的情况是[，,]?", lambda match: match.group(1), softened_block)
        softened_block = re.sub(r"(^|[。！？!?；;])\s*这通常不是[^。！？!?]*[。！？!?]?", lambda match: match.group(1), softened_block)
        softened_block = re.sub(r"(^|[。！？!?；;])\s*这就是为什么[，,]?", lambda match: match.group(1), softened_block)
        softened_block = re.sub(r"(^|[。！？!?；;])\s*就别再拿“还能撑”安慰自己了[。！？!?]?", lambda match: match.group(1), softened_block)
        softened_block = re.sub(r"(^|[。！？!?；;])\s*先把自己算进去[。！？!?]?", lambda match: match.group(1), softened_block)
        softened_block = re.sub(r"(^|[。！？!?；;])\s*它们早就在提醒[，,]?", lambda match: match.group(1), softened_block)
        softened_block = re.sub(r"^已经开始([^，。！？!?]{6,40})，", lambda match: f"{match.group(1)}的时候，", softened_block)

        softened_block = re.sub(r"[，,]{2,}", "，", softened_block)
        softened_block = re.sub(r"[。！？!?；;]{2,}", "。", softened_block)
        softened_block = re.sub(r"([。！？!?；;，,])\s*[。！？!?；;，,]+", r"\1", softened_block)
        softened_block = re.sub(r"\s+", " ", softened_block).strip(" ，,")
        softened_block = re.sub(r"^[；;，,]", "", softened_block).strip()
        if softened_block and softened_block[-1] not in "。！？!?":
            softened_block += "。"

        if not softened_block:
            continue
        if (
            softened_blocks
            and compact_len(softened_block) <= 16
            and compact_len(normalized) > compact_len(softened_block)
            and not _looks_like_structure_heading(softened_block)
        ):
            softened_blocks[-1] = softened_blocks[-1].rstrip() + softened_block
            changed = True
            continue
        if softened_block != normalized:
            changed = True
        softened_blocks.append(softened_block)

    if not changed:
        return body_markdown

    softened_markdown = "\n\n".join(([heading_block] if heading_block else []) + softened_blocks)
    softened_summary = evaluate_ai_flavor_risk(title=title, body_markdown=softened_markdown)
    softened_lecture_hits = [
        hit for hit in softened_summary.hits if "第二人称讲解台词偏显眼" in hit
    ]
    if softened_summary.score > original_summary.score:
        return body_markdown
    if softened_summary.score == original_summary.score and softened_lecture_hits:
        return body_markdown
    if any("不是A，是B" in hit for hit in softened_summary.hits):
        return body_markdown
    if any("解释连接词偏多" in hit for hit in softened_summary.hits):
        return body_markdown

    return softened_markdown


def _soften_not_ab_residue(*, title: str, body_markdown: str) -> str:
    original_not_ab = extract_not_ab_skeletons(body_markdown)
    if not original_not_ab or len(original_not_ab) > 3:
        return body_markdown

    pattern = re.compile(r"不是(.{1,24}?)[，,、]?\s*(?:而?是)([^。；\n]{1,80})", re.UNICODE)
    if not pattern.search(body_markdown):
        return body_markdown

    def _normalize_not_ab_left_fragment(text: str) -> str:
        normalized = text.strip()
        normalized = re.sub(r"^(因为|只是|就只是|并不是因为)", "", normalized).strip()
        normalized = re.sub(r"而$", "", normalized).strip()
        normalized = re.sub(r"^(她|他|你|我)(?=真的|没|不|总|还|先)", "", normalized).strip()
        return normalized

    def _build_not_ab_tail(left: str) -> str:
        normalized = _normalize_not_ab_left_fragment(left)
        if not normalized:
            return ""
        if normalized.startswith(("突然一下到了重症那一步", "最近没休息好", "病名本身", "不爱自己", "没感觉")):
            return ""
        if normalized.startswith(("故意", "刻意", "体贴", "逞强", "嘴硬")):
            return f"先说成{normalized}，反而太轻了"
        if normalized.startswith(("没发现", "不知道", "不在意", "不想管")):
            return f"真要这么说，也把事情说浅了"
        if normalized.startswith(("真的觉得自己没事", "觉得自己没事", "没事")):
            return "真要把它当成没事，后面那点拖延和硬撑反而更难解释"
        if normalized.startswith(("不爱惜自己", "不重视健康", "不重视自己")):
            return f"把它直接说成{normalized}，也把真实处境写窄了"
        if normalized.startswith(("故意藏着不说", "藏着不说")):
            return "真要说她是在藏，反而把那一下卡住写轻了"
        return f"真要把它算成{normalized}，反而把事情说浅了"

    def _rewrite_not_ab(match: re.Match[str]) -> str:
        left = match.group(1).strip()
        right = match.group(2).strip()
        tail = _build_not_ab_tail(left)
        if right.startswith("因为"):
            return f"{right}。{tail}" if tail else right
        return f"{right}。{tail}" if tail else right

    softened_markdown = pattern.sub(
        _rewrite_not_ab,
        body_markdown,
    )
    if softened_markdown == body_markdown:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    softened_summary = evaluate_ai_flavor_risk(title=title, body_markdown=softened_markdown)
    if softened_summary.score > original_summary.score:
        return body_markdown

    return softened_markdown


def _strip_rebound_explainer_tail_residue(*, title: str, body_markdown: str) -> str:
    original_tails = extract_rebound_explainer_tails(body_markdown)
    if len(original_tails) < 2:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    tail_pattern = re.compile(
        r"(?:^|[。！？!?])\s*(真要把它(?:算成|当成)[^。！？!?；;\n]{0,24}(?:。)?\s*(?:(?:更常见的情况|你还)[，,]\s*)?(?:反而把事情说浅了|后面那点拖延和硬撑反而更难解释)|真要这么说(?:，)?也把事情说浅了|先说成[^。！？!?；;\n]{0,18}反而太轻了|把它直接说成[^。！？!?；;\n]{0,18}也把真实处境写窄了|真要说她是在藏(?:，)?反而把那一下卡住写轻了)(?:。|$)",
        re.UNICODE,
    )

    changed = False
    cleaned_blocks: list[str] = []
    for block in body_blocks:
        normalized = block.strip()
        cleaned = tail_pattern.sub("。", normalized)
        cleaned = re.sub(r"([。！？!?])\s*([。！？!?])+", r"\1", cleaned)
        cleaned = re.sub(r"(^|[。！？!?；;，,])\s*只，", r"\1", cleaned)
        cleaned = re.sub(r"(^|[。！？!?；;，,])\s*都，", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = cleaned.strip("，,；; ")
        cleaned = re.sub(r"^[。！？!?]+", "", cleaned).strip()
        cleaned = re.sub(r"[，,]\s*(?=$)", "", cleaned)
        if cleaned and cleaned[-1] not in "。！？!?":
            cleaned += "。"
        if cleaned != normalized:
            changed = True
        if cleaned:
            cleaned_blocks.append(cleaned)

    if not changed:
        return body_markdown

    cleaned_markdown = "\n\n".join(([heading_block] if heading_block else []) + cleaned_blocks)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    return cleaned_markdown


def _strip_orphaned_rebound_tail_residue(*, title: str, body_markdown: str) -> str:
    orphaned_tails = extract_orphaned_rebound_tails(body_markdown)
    if not orphaned_tails:
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    orphaned_pattern = re.compile(
        r"(?:^|[。！？!?；;，,])\s*(?:真要把它(?:算成|当成)[^。！？!?；;\n]{0,24}[。！？!?；;，,]*\s*)?"
        r"(?:(?:它更常见的样子)|(?:更常见的情况|你还)[，,]\s*反而把事情说浅了|它代表的，反而把事情说浅了|后面那点拖延和硬撑反而更难解释|也把事情说浅了|反而把事情说浅了)"
        r"(?:[。！？!?；;]|$)",
        re.UNICODE,
    )

    changed = False
    cleaned_blocks: list[str] = []
    for block in body_blocks:
        normalized = block.strip()
        cleaned = orphaned_pattern.sub("。", normalized)
        cleaned = re.sub(r"(^|[。！？!?；;，,])\s*它，", r"\1", cleaned)
        cleaned = re.sub(r"(^|[。！？!?；;])\s*是(?=(?:明明|你把|对方|别人|场面|关系|问题|事情))", r"\1", cleaned)
        cleaned = re.sub(r"([。！？!?])\s*([。！？!?])+", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = cleaned.strip("，,；; ")
        cleaned = re.sub(r"^[。！？!?]+", "", cleaned).strip()
        if cleaned and cleaned[-1] not in "。！？!?":
            cleaned += "。"
        if cleaned != normalized:
            changed = True
        if cleaned:
            cleaned_blocks.append(cleaned)

    if not changed:
        return body_markdown

    cleaned_markdown = "\n\n".join(([heading_block] if heading_block else []) + cleaned_blocks)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    return cleaned_markdown


def _collapse_isolated_quote_example_residue(*, title: str, body_markdown: str) -> str:
    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if len(body_blocks) < 3:
        return body_markdown

    def _normalize_quote_terminal(block: str) -> str:
        normalized = block.strip()
        normalized = re.sub(r"([。！？!?])([”\"'’])\s*[。！？!?]+$", r"\1\2", normalized)
        return normalized

    def _is_quote_only_block(block: str) -> bool:
        normalized = _normalize_quote_terminal(block)
        return extract_isolated_quote_paragraphs(normalized) == [normalized]

    def _is_quote_example_lead(block: str) -> bool:
        normalized = _normalize_quote_terminal(block)
        return bool(re.match(r"^(?:比如|例如)[：:]\s*[“\"'‘’].+[”\"'‘’](?:[。！？!?])?$", normalized, re.UNICODE))

    original_quotes = extract_isolated_quote_paragraphs(body_markdown)
    normalized_blocks = [_normalize_quote_terminal(block) for block in body_blocks]
    changed = any(new_block != original_block.strip() for new_block, original_block in zip(normalized_blocks, body_blocks))

    collapsed_blocks: list[str] = []
    index = 0
    while index < len(normalized_blocks):
        block = normalized_blocks[index]
        if _is_quote_example_lead(block):
            quote_run = [block]
            lookahead = index + 1
            while lookahead < len(normalized_blocks) and _is_quote_only_block(normalized_blocks[lookahead]):
                quote_run.append(normalized_blocks[lookahead])
                lookahead += 1
            if len(quote_run) > 1:
                merged_quote_examples = "".join(quote_run)
                if collapsed_blocks:
                    collapsed_blocks[-1] = collapsed_blocks[-1].rstrip() + merged_quote_examples
                else:
                    collapsed_blocks.append(merged_quote_examples)
                changed = True
                index = lookahead
                continue

        if _is_quote_only_block(block) and collapsed_blocks and collapsed_blocks[-1].rstrip().endswith(("：", ":")):
            collapsed_blocks[-1] = collapsed_blocks[-1].rstrip() + block
            changed = True
            index += 1
            continue

        collapsed_blocks.append(block)
        index += 1

    if not changed:
        return body_markdown

    cleaned_markdown = "\n\n".join(([heading_block] if heading_block else []) + collapsed_blocks)
    cleaned_quotes = extract_isolated_quote_paragraphs(cleaned_markdown)
    if len(cleaned_quotes) > len(original_quotes):
        return body_markdown

    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown
    if cleaned_summary.score == original_summary.score and len(collapsed_blocks) >= len(body_blocks):
        return body_markdown

    return cleaned_markdown


def _soften_connector_residue(*, title: str, body_markdown: str) -> str:
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    if original_summary.score > 18:
        return body_markdown
    if len(original_summary.hits) != 1:
        return body_markdown
    if not any("解释连接词偏多" in hit for hit in original_summary.hits):
        return body_markdown

    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    if not body_blocks:
        return body_markdown

    def _strip_clause_connector(block: str, connector: str) -> str:
        return re.sub(
            rf"(^|[。！？!?；;，,、])\s*{re.escape(connector)}",
            lambda match: match.group(1),
            block,
        )

    changed = False
    softened_blocks: list[str] = []
    for block in body_blocks:
        softened_block = block
        for connector in ("其实", "所以", "因此", "然后", "换句话说", "也就是说", "比如"):
            softened_block = _strip_clause_connector(softened_block, connector)
        softened_block = re.sub(
            r"(^|[。！？!?；;，,、])\s*最后(?=还是)",
            lambda match: f"{match.group(1)}到头来",
            softened_block,
        )
        softened_block = re.sub(r"([。！？!?；;，,、])\s+", r"\1", softened_block)
        softened_block = softened_block.strip()
        if softened_block != block:
            changed = True
        softened_blocks.append(softened_block)

    if not changed:
        return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + softened_blocks
    softened_markdown = "\n\n".join(rebuilt_blocks)
    softened_summary = evaluate_ai_flavor_risk(title=title, body_markdown=softened_markdown)
    if softened_summary.score >= original_summary.score:
        return body_markdown

    return softened_markdown


def _count_time_chain_leads(markdown: str) -> int:
    time_chain_prefixes = (
        "电梯",
        "楼梯口",
        "中午",
        "饭局",
        "回家路上",
        "洗完澡",
        "夜里",
        "晚上",
        "周末",
        "早上",
    )
    count = 0
    for paragraph in _extract_non_heading_paragraphs(markdown):
        normalized = paragraph.strip()
        if not normalized:
            continue
        if normalized.startswith(time_chain_prefixes):
            count += 1
    return count


def _article_shell_burden(markdown: str) -> tuple[int, int, int, int, int, int, int]:
    paragraphs = _extract_non_heading_paragraphs(markdown)
    paragraph_count = len(paragraphs)
    announcing_count = len(extract_bridging_summary_paragraphs(markdown)) + len(
        extract_embedded_banner_paragraphs(markdown)
    )
    repeated_run = count_repeated_paragraph_starter_run(markdown)[1]
    generic_openers = len(extract_generic_reflective_openers(markdown))
    medium_paragraphs = sum(1 for paragraph in paragraphs if 70 <= len(re.sub(r"\s+", "", paragraph)) <= 220)
    time_chain_leads = _count_time_chain_leads(markdown)
    shell_like_blocks = medium_paragraphs if paragraph_count and medium_paragraphs / paragraph_count >= 0.7 else 0
    burden = (
        announcing_count * 3
        + max(0, repeated_run - 2) * 2
        + max(0, generic_openers - 1) * 2
        + max(0, paragraph_count - 8)
        + max(0, time_chain_leads - 2) * 2
        + (2 if shell_like_blocks else 0)
    )
    return (
        burden,
        paragraph_count,
        announcing_count,
        repeated_run,
        generic_openers,
        shell_like_blocks,
        time_chain_leads,
    )


def _should_retry_for_article_shell_cleanup(
    *,
    source_markdown: str,
    candidate_title: str,
    candidate_markdown: str,
) -> bool:
    candidate_summary = evaluate_ai_flavor_risk(title=candidate_title, body_markdown=candidate_markdown)
    source_paragraphs = _extract_non_heading_paragraphs(source_markdown)
    candidate_paragraphs = _extract_non_heading_paragraphs(candidate_markdown)
    if len(candidate_paragraphs) < 7:
        return False

    bridging_count = len(extract_bridging_summary_paragraphs(candidate_markdown))
    embedded_banner_count = len(extract_embedded_banner_paragraphs(candidate_markdown))
    repeated_run = count_repeated_paragraph_starter_run(candidate_markdown)[1]
    generic_openers = len(extract_generic_reflective_openers(candidate_markdown))
    burden, paragraph_count, _, _, _, shell_like_blocks, time_chain_leads = _article_shell_burden(candidate_markdown)
    source_heading_count = len(_extract_structure_headings(source_markdown))
    source_paragraph_count = len(source_paragraphs)
    over_smoothed_shell_signal = (
        _looks_like_over_smoothed_tracked_article_candidate(candidate_markdown)
        and (
            len(extract_short_judgment_paragraphs(candidate_markdown)) >= 2
            or count_short_long_cadence_pairs(candidate_markdown) >= 2
            or 7 <= paragraph_count <= 12
        )
    )
    shell_layout_hits = [
        hit
        for hit in candidate_summary.hits
        if "时间节点串珠式单线推进" in hit or "中长段匀速排布" in hit
    ]
    has_shell_signal = bool(
        shell_layout_hits
        or bridging_count >= 1
        or embedded_banner_count >= 1
        or repeated_run >= 3
        or generic_openers >= 1
        or time_chain_leads >= 4
        or over_smoothed_shell_signal
    )

    if candidate_summary.score > 24 and not shell_layout_hits:
        return False
    if paragraph_count > 14 and not (
        time_chain_leads >= 4
        or bridging_count >= 2
        or (shell_like_blocks and burden >= 12 and has_shell_signal)
        or (paragraph_count >= source_paragraph_count + 4 and burden >= 12 and has_shell_signal)
    ):
        return False
    if (
        source_heading_count >= 2
        and paragraph_count <= source_paragraph_count - 1
        and time_chain_leads >= 4
        and shell_like_blocks
    ):
        return True
    if paragraph_count >= max(9, len(source_paragraphs) + 2) and shell_like_blocks and has_shell_signal:
        return True
    if bridging_count >= 1 and paragraph_count >= 8:
        return True
    if repeated_run >= 3 and generic_openers >= 1 and paragraph_count >= 8:
        return True
    if source_heading_count >= 2 and paragraph_count >= 8 and time_chain_leads >= 5:
        return True
    return burden >= 6 and paragraph_count >= 8 and has_shell_signal


def _format_retry_examples(examples: list[str], *, max_items: int = 3, max_length: int = 36) -> list[str]:
    formatted: list[str] = []
    for item in examples:
        normalized = item.strip()
        if not normalized:
            continue
        if len(normalized) > max_length:
            normalized = normalized[:max_length].rstrip() + "..."
        if normalized not in formatted:
            formatted.append(normalized)
        if len(formatted) >= max_items:
            break
    return formatted


def _build_remaining_ai_flavor_retry_instruction(
    *,
    base_instruction: str,
    source_markdown: str,
    candidate_title: str,
    candidate_markdown: str,
) -> str:
    candidate_summary = evaluate_ai_flavor_risk(title=candidate_title, body_markdown=candidate_markdown)
    retry_notes = [
        "上一次精修后，模板风险还没压够。",
        f"当前仍命中：{' / '.join(candidate_summary.hits[:4])}。",
    ]

    suggestion_summary = "；".join(candidate_summary.suggestions[:3])
    if suggestion_summary:
        retry_notes.append(f"{suggestion_summary}。")

    if any("开头讲稿式先答后证" in hit for hit in candidate_summary.hits):
        retry_notes.append("开头不要再先替读者分类、下定义、给答案，再回头举例说明；直接从原稿里已经有的现实接口、动作后果或身体信号起笔。")
    if any("第二人称讲理腔偏重" in hit for hit in candidate_summary.hits):
        retry_notes.append("开头不要再用“你以为自己只是累吗”“有一类……”这种先分类、先替读者解释的讲稿起手，直接把现实接口、动作后果或身体反应顶上来。")
    if any("中长段标准讲理排布" in hit for hit in candidate_summary.hits):
        retry_notes.append("至少把前两段里的一个整段讲理解说段拆掉，改成同段里先发生动作、停顿、代价或身体反应，再让判断慢一点出来。")
    if any("第二人称整篇讲解密度偏高" in hit for hit in candidate_summary.hits):
        retry_notes.append("前两段不要连续对“你”讲理，至少抽掉两句第二人称解释，换成事实、后果、关系变化或身体信号自己说话。")

    residual_not_ab = _format_retry_examples(extract_not_ab_skeletons(candidate_markdown))
    if residual_not_ab:
        retry_notes.append(f"这次必须直接拆掉这些“不是……而是……”骨架：{' / '.join(residual_not_ab)}。")

    residual_openers = _format_retry_examples(extract_generic_reflective_openers(candidate_markdown), max_length=16)
    if residual_openers:
        retry_notes.append(f"这些泛感慨起手不要再保留：{' / '.join(residual_openers)}。")

    residual_cliches = _format_retry_examples(extract_growth_cliches(candidate_markdown), max_length=16)
    if residual_cliches:
        retry_notes.append(f"这些套话不要再保留：{' / '.join(residual_cliches)}。")

    residual_rebound_tails = _format_retry_examples(extract_rebound_explainer_tails(candidate_markdown), max_items=4, max_length=26)
    if residual_rebound_tails:
        retry_notes.append(f"这些回头补解释的尾句要直接拆掉：{' / '.join(residual_rebound_tails)}。")

    residual_short_judgments = _format_retry_examples(extract_short_judgment_paragraphs(candidate_markdown), max_items=4, max_length=18)
    if residual_short_judgments:
        retry_notes.append(f"这些独立短判断段要处理掉或并回前后段：{' / '.join(residual_short_judgments)}。")

    residual_cadence_pairs = count_short_long_cadence_pairs(candidate_markdown)
    if residual_cadence_pairs >= 2:
        retry_notes.append("这次必须打散“短句点一下，下一段再长解释”的固定节拍，不要继续一短一长轮着写。")

    residual_embedded_banners = _format_retry_examples(
        extract_embedded_banner_paragraphs(candidate_markdown),
        max_items=4,
        max_length=22,
    )
    if residual_embedded_banners:
        retry_notes.append(f"这些先总括再展开的长段起手要拆掉：{' / '.join(residual_embedded_banners)}。")

    residual_quote_paragraphs_raw = extract_isolated_quote_paragraphs(candidate_markdown)
    residual_quote_paragraphs = _format_retry_examples(
        residual_quote_paragraphs_raw,
        max_items=3,
        max_length=20,
    )
    if len(residual_quote_paragraphs_raw) >= 2 and residual_quote_paragraphs:
        retry_notes.append(f"这些独立引语段不要再单独站出来：{' / '.join(residual_quote_paragraphs)}。")

    residual_explanatory_paragraphs_raw = extract_explanatory_bridge_paragraphs(candidate_markdown)
    residual_explanatory_paragraphs = _format_retry_examples(
        residual_explanatory_paragraphs_raw,
        max_items=3,
        max_length=22,
    )
    if len(residual_explanatory_paragraphs_raw) >= 2 and residual_explanatory_paragraphs:
        retry_notes.append(f"这些独立解释段要并回过程里：{' / '.join(residual_explanatory_paragraphs)}。")

    heading_anchors = _extract_structure_heading_anchors(source_markdown)
    if heading_anchors:
        retry_notes.append(
            "继续围绕这些原稿锚点推进："
            + "；".join(f"{heading} -> {anchor}" for heading, anchor in heading_anchors[:4])
            + "。"
        )

    retry_notes.append("保留原稿结构、案例和人物关系，但把仍然偏模板的判断段继续往具体动作和处境上压。")
    retry_notes.append("不要把开头第一屏和各小节首段统一扩成新的氛围场景或散文式环境描写，优先沿用原稿已有的人物、案例、判断或并列例子起笔。")
    retry_notes.append("如果原稿本来是议论推进或并列展开，就继续保留这种推进方式，不要每一节都先铺场景再总结。")
    retry_notes.append("分析型或并列展开的段落，宁可直接写状态、动作后果、身体反应和关系变化，也不要再用新的“不是……而是……”对照句补解释。")
    retry_notes.append("如果情绪价值已经落在判断、动作后果或身体反应里，就直接推进，不要额外补一段没有信息增量的场景或气氛。")
    retry_notes.append("如果某个短段只是为了敲一下、点一下、提醒一下，优先并回相邻段落，不要再把这类短段写成固定节拍。")
    retry_notes.append("不要把一句消息、对话、短信或引用写成反复出现的展示段；如果全文只留一处且确实承担现场感，可以保留。")
    retry_notes.append("不要把“解释也来得很快：……”这类独立解释短段写成固定排版习惯；如果全文只留一处且确实承担心理跳转，可以保留。")
    retry_notes.append("至少留一段只停在观察、动作、关系变化或身体反应上，不必每段都补齐完整判断。")
    retry_notes.append("这轮改完以后，全文不要新增任何新的“不是……而是/是……”骨架；上面点名的残留句要逐句拆掉，而不是换个近义词继续保留结构。")
    retry_notes.append("不要只把句子改顺，要把还带统一解释腔的段落真正重写。")
    return base_instruction.strip() + " " + "".join(retry_notes)


def _build_final_ai_flavor_cleanup_instruction(
    *,
    base_instruction: str,
    source_markdown: str,
    candidate_title: str,
    candidate_markdown: str,
) -> str:
    candidate_summary = evaluate_ai_flavor_risk(title=candidate_title, body_markdown=candidate_markdown)
    retry_notes = [
        "最后只剩少量模板残留，这次不是整篇重写，而是最后一轮局部清理。",
        "只改仍然露出模板感的 1 到 4 句，其余段落结构、顺序、案例和信息尽量不动。",
    ]

    residual_not_ab = _format_retry_examples(extract_not_ab_skeletons(candidate_markdown))
    if residual_not_ab:
        retry_notes.append(f"把这些残留的“不是……而是/是……”骨架直接拆掉：{' / '.join(residual_not_ab)}。")

    residual_openers = _format_retry_examples(extract_generic_reflective_openers(candidate_markdown), max_length=16)
    if residual_openers:
        retry_notes.append(f"把这些残留的泛感慨起手改掉：{' / '.join(residual_openers)}。")

    residual_cliches = _format_retry_examples(extract_growth_cliches(candidate_markdown), max_length=16)
    if residual_cliches:
        retry_notes.append(f"把这些残留套话改掉：{' / '.join(residual_cliches)}。")

    residual_rebound_tails = _format_retry_examples(extract_rebound_explainer_tails(candidate_markdown), max_items=4, max_length=26)
    if residual_rebound_tails:
        retry_notes.append(f"把这些回头补解释的尾句直接拆掉：{' / '.join(residual_rebound_tails)}。")

    residual_short_judgments = _format_retry_examples(extract_short_judgment_paragraphs(candidate_markdown), max_items=4, max_length=18)
    if residual_short_judgments:
        retry_notes.append(f"把这些独立短判断段并回相邻段落或改成更具体的句子：{' / '.join(residual_short_judgments)}。")

    residual_cadence_pairs = count_short_long_cadence_pairs(candidate_markdown)
    if residual_cadence_pairs >= 1:
        retry_notes.append("如果这里还保留着“短句点一下，下一段长解释”的节拍，就打散至少一处，不要再维持一短一长的固定轮换。")

    residual_embedded_banners = _format_retry_examples(
        extract_embedded_banner_paragraphs(candidate_markdown),
        max_items=3,
        max_length=22,
    )
    if residual_embedded_banners:
        retry_notes.append(f"把这些长段前置总括句并回过程里，不要保留在段首：{' / '.join(residual_embedded_banners)}。")

    residual_quote_paragraphs_raw = extract_isolated_quote_paragraphs(candidate_markdown)
    residual_quote_paragraphs = _format_retry_examples(
        residual_quote_paragraphs_raw,
        max_items=3,
        max_length=20,
    )
    if len(residual_quote_paragraphs_raw) >= 2 and residual_quote_paragraphs:
        retry_notes.append(f"把这些独立引语段并回前后动作和反应里：{' / '.join(residual_quote_paragraphs)}。")

    residual_explanatory_paragraphs_raw = extract_explanatory_bridge_paragraphs(candidate_markdown)
    residual_explanatory_paragraphs = _format_retry_examples(
        residual_explanatory_paragraphs_raw,
        max_items=3,
        max_length=22,
    )
    if len(residual_explanatory_paragraphs_raw) >= 2 and residual_explanatory_paragraphs:
        retry_notes.append(f"把这些独立解释段并回过程里：{' / '.join(residual_explanatory_paragraphs)}。")

    if any("解释连接词偏多" in hit for hit in candidate_summary.hits):
        retry_notes.append("如果这几句里还在靠“比如 / 其实 / 所以 / 然后 / 也就是说”这类词硬接，就删掉部分解释连接词，让动作、停顿和前后句直接接上。")

    if any("“一”字节奏偏密" in hit for hit in candidate_summary.hits):
        retry_notes.append("如果这几句里还反复出现“一下 / 一遍 / 一个 / 一种”这类写法，替换一半以上的一字量词起手，改成更具体的动作、物件或时间推进。")

    if any("第二人称讲解台词偏显眼" in hit for hit in candidate_summary.hits):
        retry_notes.append("把“你有没有过这种阶段”“答案我先告诉你”“如果你这段时间已经开始”这类讲解台词拆掉，改成状态、动作后果或关系变化先发生。")
        retry_notes.append("改这些句子时，不要换成“不是……而是……”或“其实 / 所以”解释链，也不要补成新的标准答案句。")

    if any("开头讲稿式先答后证" in hit for hit in candidate_summary.hits):
        retry_notes.append("如果开头还在先替读者分类、下定义、给答案，就只改那一两句：先把现实接口、后果或身体信号顶上来，不要继续先讲理。")
    if any("第二人称整篇讲解密度偏高" in hit for hit in candidate_summary.hits):
        retry_notes.append("如果这几句还在连续对“你”解释，就把至少两句改成由事实、后果、身体反应或关系变化自己说话，不要句句都在教读者理解自己。")
    if any("第二人称讲理腔偏重" in hit for hit in candidate_summary.hits):
        retry_notes.append("把还在先替读者分类、下定义、解释原因的句子拆掉，尤其不要保留“你以为自己只是累吗”“有一类……”这种讲稿式起手。")
    if any("中长段标准讲理排布" in hit for hit in candidate_summary.hits):
        retry_notes.append("如果前两段还像一段判断、一段解释的标准答案壳，就只改其中一两句：让现实接口、代价或身体反应先顶上来，不要继续先讲道理。")

    if any("中长段整篇过于齐整" in hit for hit in candidate_summary.hits):
        retry_notes.append("如果这些段落还像标准答案壳，就只挑一到两段下手：合并一段、拆短一段，打破整篇一段一层、句句讲满的排布。")

    heading_anchors = _extract_structure_heading_anchors(source_markdown)
    if heading_anchors:
        retry_notes.append(
            "原稿锚点仍然以这些为准："
            + "；".join(f"{heading} -> {anchor}" for heading, anchor in heading_anchors[:4])
            + "。"
        )

    retry_notes.append("不要新增新的环境描写、人物、病症、道具、支线或总结段。")
    retry_notes.append("如果需要改句，优先把判断改成当前段落里已经存在的动作、处境、顺序或关系，不要补新的总括句。")
    retry_notes.append("如果情绪价值已经成立，就不要为了润色再补没有信息增量的场景壳。")
    retry_notes.append("不要把一句消息、对话、短信或引用写成反复出现的展示段，也不要把独立解释短段写成固定排版习惯。")
    retry_notes.append("清理完之后，不要再保留新的“不是……而是/是……”骨架，也不要补新的“我们总以为”“很多时候”“说到底”起手。")
    return base_instruction.strip() + " " + "".join(retry_notes)


def _build_article_shell_retry_instruction(
    *,
    base_instruction: str,
    source_markdown: str,
    candidate_markdown: str,
) -> str:
    paragraph_count = len(_extract_non_heading_paragraphs(candidate_markdown))
    bridging_examples = _format_retry_examples(extract_bridging_summary_paragraphs(candidate_markdown), max_items=3, max_length=20)
    embedded_banner_examples = _format_retry_examples(
        extract_embedded_banner_paragraphs(candidate_markdown),
        max_items=3,
        max_length=20,
    )
    generic_openers = _format_retry_examples(extract_generic_reflective_openers(candidate_markdown), max_items=3, max_length=12)
    repeated_starter, repeated_run = count_repeated_paragraph_starter_run(candidate_markdown)

    retry_notes = [
        "这版已经不像原文了，但还像一篇打磨过头的完整公众号成稿，整体太匀、太整齐、太像每段只负责一个职责的成品文。",
        "这次不要只改句子，要直接拆掉这种成稿骨架。",
        f"当前正文大约有 {paragraph_count} 个自然段；如果它们被切得太均匀，请主动压成 6 到 8 个更长、更自然的段落。",
        "不要把全文排成“现象段 -> 解释段 -> 总结段”轮换，也不要每段只完成一个单一职责。",
        "每个段落里允许同时出现现象、动作、局部解释和后续影响，不必把判断单独拎出来宣布。",
        "如果策略要求碎片回环，就不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线。",
        "不要让电梯、楼梯、午休、饭局、回家、洗澡、深夜这些节点按时间表整齐排队；至少打断一处，改成回看、插入或接口回环。",
        "前两段先钉一个可观察现象和真正卡住的冲突，不要提前回答整篇题眼，也不要一上来就把道理讲完。",
        "至少留一处还没完全说透的观察，不要让每段都像已经被审校过的标准答案。",
        "不要花很多篇幅包装一个已经说过的判断；如果一句话已经成立，后面就继续推进，不要反复换说法证明它。",
        "如果某些段落只是为了宣布、包装、解释或收束观点，优先删掉或并回前后过程，而不是保留整段。",
        "如果正文已经切成很多整齐小段，宁可合并段落，也不要保留一屏一结论的均匀排布。",
    ]

    if bridging_examples:
        retry_notes.append(f"这些负责宣布观点的段落优先删掉或并回过程：{' / '.join(bridging_examples)}。")
    if embedded_banner_examples:
        retry_notes.append(f"这些长段开头先总括再解释的句子也要拆掉：{' / '.join(embedded_banner_examples)}。")
    if generic_openers:
        retry_notes.append(f"这些总括起手先不要再补：{' / '.join(generic_openers)}。")
    if repeated_starter and repeated_run >= 3:
        retry_notes.append(
            f"目前有连续同主语起段（{repeated_starter} x{repeated_run}），至少打散一半，让动作、物件、时间节点或环境先打开句子。"
        )

    heading_anchors = _extract_structure_heading_anchors(source_markdown)
    if heading_anchors:
        retry_notes.append(
            "原稿锚点仍然以这些为准："
            + "；".join(f"{heading} -> {anchor}" for heading, anchor in heading_anchors[:4])
            + "。"
        )

    retry_notes.append("保留原稿已有事实、人物、关系和案例，不要新增陌生人物、病症、城市、职业、支线或寓言化场景。")
    retry_notes.append("如果原稿本质是议论、感悟或并列展开，就继续按这个体裁重写，不要统一转成小说化散文。")
    retry_notes.append("重写后仍然只返回标题和正文，不要解释你做了什么。")
    return base_instruction.strip() + " " + "".join(retry_notes)


def _should_prefer_retried_ai_flavor_candidate(
    *,
    current_title: str,
    current_markdown: str,
    retried_title: str,
    retried_markdown: str,
    current_reference_title: str | None = None,
    current_reference_markdown: str | None = None,
    retried_reference_title: str | None = None,
    retried_reference_markdown: str | None = None,
    current_cleanup_applied: bool | None = None,
    current_cleanup_changed_steps: int | None = None,
    retried_cleanup_applied: bool | None = None,
    retried_cleanup_changed_steps: int | None = None,
    source_type: str | None = None,
) -> bool:
    def _short_paragraph_count(markdown: str) -> int:
        return sum(
            1
            for paragraph in _extract_non_heading_paragraphs(markdown)
            if len(re.sub(r"\s+", "", paragraph)) <= 45
        )

    def _hard_template_burden(markdown: str) -> tuple[int, int, int, int, int, int]:
        quote_paragraphs = max(0, len(extract_isolated_quote_paragraphs(markdown)) - 1)
        explanatory_paragraphs = max(0, len(extract_explanatory_bridge_paragraphs(markdown)) - 1)
        return (
            len(extract_not_ab_skeletons(markdown)),
            len(extract_generic_reflective_openers(markdown)),
            len(extract_growth_cliches(markdown)),
            len(extract_embedded_banner_paragraphs(markdown)),
            quote_paragraphs,
            explanatory_paragraphs,
        )

    def _has_only_minor_ai_flavor_residue(*, title: str, markdown: str) -> bool:
        summary = evaluate_ai_flavor_risk(title=title, body_markdown=markdown)
        if summary.score > 22:
            return False
        if _hard_template_burden(markdown) != (0, 0, 0, 0, 0, 0):
            return False
        if len(extract_short_judgment_paragraphs(markdown)) > 2:
            return False
        if count_short_long_cadence_pairs(markdown) > 2:
            return False
        return any(
            (
                "解释连接词偏多" in hit
                or "短句敲钟后接长解释的固定节拍" in hit
                or "“一”字节奏偏密" in hit
            )
            for hit in summary.hits
        )

    def _has_mild_template_burden(*, title: str, markdown: str) -> bool:
        summary = evaluate_ai_flavor_risk(title=title, body_markdown=markdown)
        return (
            summary.score <= 18
            and len(extract_not_ab_skeletons(markdown)) <= 1
            and len(extract_generic_reflective_openers(markdown)) == 0
            and len(extract_growth_cliches(markdown)) == 0
            and len(extract_embedded_banner_paragraphs(markdown)) == 0
            and count_short_long_cadence_pairs(markdown) <= 1
        )

    def _looks_over_smoothed_relative_to_current(current_markdown: str, retried_markdown: str) -> bool:
        current_paragraph_count = len(_extract_non_heading_paragraphs(current_markdown))
        retried_paragraph_count = len(_extract_non_heading_paragraphs(retried_markdown))
        current_short_paragraphs = _short_paragraph_count(current_markdown)
        retried_short_paragraphs = _short_paragraph_count(retried_markdown)
        current_quote_paragraphs = len(extract_isolated_quote_paragraphs(current_markdown))
        retried_quote_paragraphs = len(extract_isolated_quote_paragraphs(retried_markdown))
        current_explanatory_paragraphs = len(extract_explanatory_bridge_paragraphs(current_markdown))
        retried_explanatory_paragraphs = len(extract_explanatory_bridge_paragraphs(retried_markdown))

        return (
            current_paragraph_count - retried_paragraph_count >= 3
            and current_short_paragraphs - retried_short_paragraphs >= 3
            and (
                current_quote_paragraphs > retried_quote_paragraphs
                or current_explanatory_paragraphs > retried_explanatory_paragraphs
                or current_short_paragraphs >= 5
            )
        )

    def _residual_burden(markdown: str) -> tuple[int, int, int, int, int, int, int, int, int]:
        not_ab = len(extract_not_ab_skeletons(markdown))
        openers = len(extract_generic_reflective_openers(markdown))
        cliches = len(extract_growth_cliches(markdown))
        short_judgments = len(extract_short_judgment_paragraphs(markdown))
        cadence_pairs = count_short_long_cadence_pairs(markdown)
        embedded_banners = len(extract_embedded_banner_paragraphs(markdown))
        quote_paragraphs = max(0, len(extract_isolated_quote_paragraphs(markdown)) - 1)
        explanatory_paragraphs = max(0, len(extract_explanatory_bridge_paragraphs(markdown)) - 1)
        return (
            not_ab + openers + cliches + short_judgments + cadence_pairs + embedded_banners + quote_paragraphs + explanatory_paragraphs,
            embedded_banners,
            short_judgments,
            cadence_pairs,
            not_ab,
            openers,
            cliches,
            quote_paragraphs,
            explanatory_paragraphs,
        )

    current_summary = evaluate_ai_flavor_risk(title=current_title, body_markdown=current_markdown)
    retried_summary = evaluate_ai_flavor_risk(title=retried_title, body_markdown=retried_markdown)
    tracked_article_mode = source_type == "tracked_article"
    current_structure_headings = _extract_structure_headings(current_markdown)
    if len(current_structure_headings) >= 2 and _find_missing_structure_headings(
        source_markdown=current_markdown,
        candidate_markdown=retried_markdown,
    ):
        return False
    current_over_smoothed = (
        tracked_article_mode and _looks_like_over_smoothed_tracked_article_candidate(current_markdown)
    )
    retried_over_smoothed = (
        tracked_article_mode and _looks_like_over_smoothed_tracked_article_candidate(retried_markdown)
    )
    current_reference_summary = evaluate_ai_flavor_risk(
        title=current_reference_title or current_title,
        body_markdown=current_reference_markdown or current_markdown,
    )
    retried_reference_summary = evaluate_ai_flavor_risk(
        title=retried_reference_title or retried_title,
        body_markdown=retried_reference_markdown or retried_markdown,
    )
    if current_over_smoothed != retried_over_smoothed:
        return not retried_over_smoothed
    if _has_only_minor_ai_flavor_residue(title=current_title, markdown=current_markdown):
        if (
            retried_summary.score < current_summary.score
            and not _has_only_minor_ai_flavor_residue(title=retried_title, markdown=retried_markdown)
            and _hard_template_burden(retried_markdown) >= _hard_template_burden(current_markdown)
        ):
            return False
    if (
        retried_summary.score < current_summary.score
        and _has_mild_template_burden(title=current_title, markdown=current_markdown)
        and _looks_over_smoothed_relative_to_current(current_markdown, retried_markdown)
    ):
        return False
    if retried_summary.score < current_summary.score:
        return True
    if retried_summary.score == current_summary.score:
        if retried_reference_summary.score < current_reference_summary.score:
            return True
        if retried_reference_summary.score > current_reference_summary.score:
            return False
        current_cleanup_flag = 1 if bool(current_cleanup_applied) else 0
        retried_cleanup_flag = 1 if bool(retried_cleanup_applied) else 0
        if retried_cleanup_flag < current_cleanup_flag:
            return True
        if retried_cleanup_flag > current_cleanup_flag:
            return False
        current_cleanup_cost = int(current_cleanup_changed_steps or 0)
        retried_cleanup_cost = int(retried_cleanup_changed_steps or 0)
        if retried_cleanup_cost < current_cleanup_cost:
            return True
        if retried_cleanup_cost > current_cleanup_cost:
            return False
    if retried_summary.score == current_summary.score and len(retried_summary.hits) < len(current_summary.hits):
        return True
    if retried_summary.score == current_summary.score and len(retried_summary.hits) == len(current_summary.hits):
        if _residual_burden(retried_markdown) < _residual_burden(current_markdown):
            return True
    return False


def _pick_better_ai_flavor_candidate(
    *,
    current_title: str,
    current_markdown: str,
    retried_title: str,
    retried_markdown: str,
    current_reference_title: str | None = None,
    current_reference_markdown: str | None = None,
    retried_reference_title: str | None = None,
    retried_reference_markdown: str | None = None,
    current_cleanup_applied: bool | None = None,
    current_cleanup_changed_steps: int | None = None,
    retried_cleanup_applied: bool | None = None,
    retried_cleanup_changed_steps: int | None = None,
    source_type: str | None = None,
) -> tuple[str, str]:
    if _should_prefer_retried_ai_flavor_candidate(
        current_title=current_title,
        current_markdown=current_markdown,
        retried_title=retried_title,
        retried_markdown=retried_markdown,
        current_reference_title=current_reference_title,
        current_reference_markdown=current_reference_markdown,
        retried_reference_title=retried_reference_title,
        retried_reference_markdown=retried_reference_markdown,
        current_cleanup_applied=current_cleanup_applied,
        current_cleanup_changed_steps=current_cleanup_changed_steps,
        retried_cleanup_applied=retried_cleanup_applied,
        retried_cleanup_changed_steps=retried_cleanup_changed_steps,
        source_type=source_type,
    ):
        return retried_markdown, retried_title
    return current_markdown, current_title


def _pick_better_article_shell_candidate(
    *,
    current_title: str,
    current_markdown: str,
    retried_title: str,
    retried_markdown: str,
) -> tuple[str, str]:
    current_summary = evaluate_ai_flavor_risk(title=current_title, body_markdown=current_markdown)
    retried_summary = evaluate_ai_flavor_risk(title=retried_title, body_markdown=retried_markdown)
    current_burden = _article_shell_burden(current_markdown)
    retried_burden = _article_shell_burden(retried_markdown)
    current_over_smoothed = _looks_like_over_smoothed_tracked_article_candidate(current_markdown)
    retried_over_smoothed = _looks_like_over_smoothed_tracked_article_candidate(retried_markdown)

    if current_over_smoothed != retried_over_smoothed:
        if retried_over_smoothed:
            return current_markdown, current_title
        return retried_markdown, retried_title

    if retried_summary.score < current_summary.score:
        return retried_markdown, retried_title
    if retried_burden < current_burden and retried_summary.score <= current_summary.score + 8:
        return retried_markdown, retried_title
    if retried_burden == current_burden and retried_summary.score == current_summary.score:
        if len(_extract_non_heading_paragraphs(retried_markdown)) < len(_extract_non_heading_paragraphs(current_markdown)):
            return retried_markdown, retried_title
    return current_markdown, current_title


def _maybe_retry_polish_for_structure_drift(
    *,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    source_draft_title: str,
    source_draft_body_markdown: str,
    candidate_title: str,
    candidate_body_markdown: str,
) -> tuple[str, str]:
    if not polish_instruction:
        return candidate_body_markdown, candidate_title

    missing_headings = _find_missing_structure_headings(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=candidate_body_markdown,
    )
    if not missing_headings:
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
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
            "domain_pack": get_project_domain_pack(project),
            "review_comment": review_comment,
            "polish_instruction": _build_structure_retry_instruction(
                base_instruction=polish_instruction,
                source_markdown=source_draft_body_markdown,
                missing_headings=missing_headings,
            ),
            "allow_structure_recomposition": False,
            "preserve_structure_anchors": True,
            "draft": {
                "title": source_draft_title,
                "body_markdown": source_draft_body_markdown,
            },
            **strategy_bundle_payload,
            **reference_article_payload,
        }
    )
    return str(retry_result["body_markdown"]), str(retry_result["title"])


def _maybe_retry_polish_for_over_smoothing(
    *,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    source_draft_title: str,
    source_draft_body_markdown: str,
    candidate_title: str,
    candidate_body_markdown: str,
) -> tuple[str, str]:
    if not polish_instruction:
        return candidate_body_markdown, candidate_title

    excessive_openers = _find_excessive_generic_reflective_openers(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=candidate_body_markdown,
    )
    if not excessive_openers:
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
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
            "domain_pack": get_project_domain_pack(project),
            "review_comment": review_comment,
            "polish_instruction": _build_over_smoothing_retry_instruction(
                base_instruction=polish_instruction,
                source_markdown=source_draft_body_markdown,
                excessive_openers=excessive_openers,
            ),
            "allow_structure_recomposition": False,
            "preserve_structure_anchors": True,
            "draft": {
                "title": candidate_title,
                "body_markdown": candidate_body_markdown,
            },
            **strategy_bundle_payload,
            **reference_article_payload,
        }
    )
    if not _preserves_structure_headings(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=str(retry_result["body_markdown"]),
    ):
        return candidate_body_markdown, candidate_title
    retried_title = str(retry_result["title"])
    retried_markdown = str(retry_result["body_markdown"])
    if _should_prefer_retried_candidate_after_cleanup_preview(
        current_title=candidate_title,
        current_markdown=candidate_body_markdown,
        retried_title=retried_title,
        retried_markdown=retried_markdown,
        source_type=str(project["source_type"]),
    ):
        return retried_markdown, retried_title
    return candidate_body_markdown, candidate_title


def _maybe_retry_polish_for_article_shell_cleanup(
    *,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    source_draft_title: str,
    source_draft_body_markdown: str,
    candidate_title: str,
    candidate_body_markdown: str,
) -> tuple[str, str]:
    if not polish_instruction or str(project["source_type"]) != "tracked_article":
        return candidate_body_markdown, candidate_title

    if not _should_retry_for_article_shell_cleanup(
        source_markdown=source_draft_body_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
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
            "domain_pack": get_project_domain_pack(project),
            "review_comment": review_comment,
            "polish_instruction": _build_article_shell_retry_instruction(
                base_instruction=polish_instruction,
                source_markdown=source_draft_body_markdown,
                candidate_markdown=candidate_body_markdown,
            ),
            "allow_structure_recomposition": True,
            "preserve_structure_anchors": False,
            "draft": {
                "title": candidate_title,
                "body_markdown": candidate_body_markdown,
            },
            **strategy_bundle_payload,
            **reference_article_payload,
        }
    )
    return _pick_better_article_shell_candidate(
        current_title=candidate_title,
        current_markdown=candidate_body_markdown,
        retried_title=str(retry_result["title"]),
        retried_markdown=str(retry_result["body_markdown"]),
    )


def _maybe_retry_polish_for_remaining_ai_flavor(
    *,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    source_draft_title: str,
    source_draft_body_markdown: str,
    candidate_title: str,
    candidate_body_markdown: str,
) -> tuple[str, str]:
    if not polish_instruction:
        return candidate_body_markdown, candidate_title

    if not _should_retry_for_remaining_ai_flavor(
        source_title=source_draft_title,
        source_markdown=source_draft_body_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
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
            "domain_pack": get_project_domain_pack(project),
            "review_comment": review_comment,
            "polish_instruction": _build_remaining_ai_flavor_retry_instruction(
                base_instruction=polish_instruction,
                source_markdown=source_draft_body_markdown,
                candidate_title=candidate_title,
                candidate_markdown=candidate_body_markdown,
            ),
            "allow_structure_recomposition": str(project["source_type"]) == "tracked_article",
            "preserve_structure_anchors": str(project["source_type"]) != "tracked_article",
            "draft": {
                "title": candidate_title,
                "body_markdown": candidate_body_markdown,
            },
            **strategy_bundle_payload,
            **reference_article_payload,
        }
    )
    if str(project["source_type"]) != "tracked_article" and not _preserves_structure_headings(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=str(retry_result["body_markdown"]),
    ):
        return candidate_body_markdown, candidate_title
    retried_title = str(retry_result["title"])
    retried_markdown = str(retry_result["body_markdown"])
    if _should_prefer_retried_candidate_after_cleanup_preview(
        current_title=candidate_title,
        current_markdown=candidate_body_markdown,
        retried_title=retried_title,
        retried_markdown=retried_markdown,
        source_type=str(project["source_type"]),
    ):
        return retried_markdown, retried_title
    return candidate_body_markdown, candidate_title


def _maybe_retry_polish_for_final_ai_flavor_cleanup(
    *,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    source_draft_title: str,
    source_draft_body_markdown: str,
    candidate_title: str,
    candidate_body_markdown: str,
) -> tuple[str, str]:
    if not polish_instruction:
        return candidate_body_markdown, candidate_title

    current_title = candidate_title
    current_markdown = candidate_body_markdown

    for _ in range(2):
        if not _should_retry_for_final_ai_flavor_cleanup(
            candidate_title=current_title,
            candidate_markdown=current_markdown,
        ):
            break

        retry_result = generator.generate_draft(
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
                "domain_pack": get_project_domain_pack(project),
                "review_comment": review_comment,
                "polish_instruction": _build_final_ai_flavor_cleanup_instruction(
                    base_instruction=polish_instruction,
                    source_markdown=source_draft_body_markdown,
                    candidate_title=current_title,
                    candidate_markdown=current_markdown,
                ),
                "allow_structure_recomposition": str(project["source_type"]) == "tracked_article",
                "preserve_structure_anchors": str(project["source_type"]) != "tracked_article",
                "draft": {
                    "title": current_title,
                    "body_markdown": current_markdown,
                },
                **strategy_bundle_payload,
                **reference_article_payload,
            }
        )
        if str(project["source_type"]) != "tracked_article" and not _preserves_structure_headings(
            source_markdown=source_draft_body_markdown,
            candidate_markdown=str(retry_result["body_markdown"]),
        ):
            break
        next_title = str(retry_result["title"])
        next_markdown = str(retry_result["body_markdown"])
        if not _should_prefer_retried_candidate_after_cleanup_preview(
            current_title=current_title,
            current_markdown=current_markdown,
            retried_title=next_title,
            retried_markdown=next_markdown,
            source_type=str(project["source_type"]),
        ):
            break
        current_markdown = next_markdown
        current_title = next_title

    return current_markdown, current_title


def _can_short_circuit_tracked_article_retry_chain(
    *,
    source_draft_title: str,
    source_draft_body_markdown: str,
    candidate_title: str,
    candidate_body_markdown: str,
) -> bool:
    if _find_missing_structure_headings(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=candidate_body_markdown,
    ):
        return False
    if _find_excessive_generic_reflective_openers(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=candidate_body_markdown,
    ):
        return False
    if _should_retry_for_article_shell_cleanup(
        source_markdown=source_draft_body_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return False
    if _should_retry_for_remaining_ai_flavor(
        source_title=source_draft_title,
        source_markdown=source_draft_body_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return False
    if _should_retry_for_final_ai_flavor_cleanup(
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return False
    return True


def _maybe_auto_polish_ai_flavor_draft_output(
    *,
    title: str,
    body_markdown: str,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    skip_nested_compact_polish: bool = False,
) -> tuple[str, str]:
    if review_comment or polish_instruction:
        return body_markdown, title

    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    is_tracked_article = str(project["source_type"]) == "tracked_article"
    has_opening_explainer_shell = any("开头讲稿式先答后证" in hit for hit in summary.hits)
    tracked_shell_source_title = title
    tracked_shell_source_markdown = body_markdown
    if is_tracked_article:
        reference_body_markdown = str(project["reference_article_body_markdown"] or "").strip()
        if reference_body_markdown:
            tracked_shell_source_markdown = reference_body_markdown
            tracked_shell_source_title = str(project["reference_article_title"] or title)
        if _looks_like_tracked_article_fragment_chain_candidate(body_markdown):
            return body_markdown, title
    needs_tracked_shell_cleanup = (
        is_tracked_article
        and _should_retry_for_article_shell_cleanup(
            source_markdown=tracked_shell_source_markdown,
            candidate_title=title,
            candidate_markdown=body_markdown,
        )
    )
    if summary.level == "低" and not needs_tracked_shell_cleanup and not (
        is_tracked_article and has_opening_explainer_shell
    ):
        return body_markdown, title

    uses_custom_base_url = bool(getattr(generator, "uses_custom_base_url", False))
    allow_structure_recomposition = is_tracked_article
    preserve_structure_anchors = not is_tracked_article
    initial_polish_instruction = build_ai_flavor_polish_instruction(summary)
    if needs_tracked_shell_cleanup:
        initial_polish_instruction = _build_article_shell_retry_instruction(
            base_instruction=initial_polish_instruction,
            source_markdown=tracked_shell_source_markdown,
            candidate_markdown=body_markdown,
        )
    polish_payload: dict[str, object] = {
        "trend_title": project["trend_title"],
        "topic_title": project["topic_title"],
        "topic_angle": project["topic_angle"],
        "project_title": project["title"],
        "outline": {
            "hook": outline_row["hook"],
            "outline_body": outline_row["outline_body"],
        },
        "tone_profile": tone_profile.model_dump(),
        "domain_pack": get_project_domain_pack(project),
        "polish_instruction": initial_polish_instruction,
        "allow_structure_recomposition": allow_structure_recomposition,
        "preserve_structure_anchors": preserve_structure_anchors,
        "draft": {
            "title": title,
            "body_markdown": body_markdown,
        },
        **strategy_bundle_payload,
        **reference_article_payload,
    }
    polished_result = generator.generate_draft(polish_payload)
    polished_title = str(polished_result["title"])
    polished_markdown = str(polished_result["body_markdown"])
    if _should_prefer_retried_candidate_after_cleanup_preview(
        current_title=title,
        current_markdown=body_markdown,
        retried_title=polished_title,
        retried_markdown=polished_markdown,
        source_type=str(project["source_type"]),
    ):
        best_markdown, best_title = polished_markdown, polished_title
    else:
        best_markdown, best_title = body_markdown, title
    working_title = polished_title
    working_markdown = polished_markdown

    if uses_custom_base_url and allow_structure_recomposition and not skip_nested_compact_polish:
        compact_polish_payload = dict(polish_payload)
        compact_polish_payload["compact_polish_mode"] = True
        compact_result = generator.generate_draft(compact_polish_payload)
        compact_title = str(compact_result["title"])
        compact_markdown = str(compact_result["body_markdown"])
        if _should_prefer_retried_candidate_after_cleanup_preview(
            current_title=working_title,
            current_markdown=working_markdown,
            retried_title=compact_title,
            retried_markdown=compact_markdown,
            source_type=str(project["source_type"]),
        ):
            working_markdown, working_title = compact_markdown, compact_title
        if _should_prefer_retried_candidate_after_cleanup_preview(
            current_title=best_title,
            current_markdown=best_markdown,
            retried_title=working_title,
            retried_markdown=working_markdown,
            source_type=str(project["source_type"]),
        ):
            best_markdown, best_title = working_markdown, working_title

    best_summary = evaluate_ai_flavor_risk(title=best_title, body_markdown=best_markdown)
    if best_summary.level == "低" and not is_tracked_article:
        return best_markdown, best_title
    if best_summary.level == "低" and is_tracked_article and _can_short_circuit_tracked_article_retry_chain(
        source_draft_title=tracked_shell_source_title,
        source_draft_body_markdown=tracked_shell_source_markdown,
        candidate_title=best_title,
        candidate_body_markdown=best_markdown,
    ):
        return best_markdown, best_title

    retried_body_markdown, retried_title = _maybe_retry_polish_for_structure_drift(
        project=project,
        outline_row=outline_row,
        tone_profile=tone_profile,
        review_comment=review_comment,
        polish_instruction=build_ai_flavor_polish_instruction(summary),
        strategy_bundle_payload=strategy_bundle_payload,
        reference_article_payload=reference_article_payload,
        generator=generator,
        source_draft_title=title,
        source_draft_body_markdown=body_markdown,
        candidate_title=working_title,
        candidate_body_markdown=working_markdown,
    )
    retried_body_markdown, retried_title = _maybe_retry_polish_for_over_smoothing(
        project=project,
        outline_row=outline_row,
        tone_profile=tone_profile,
        review_comment=review_comment,
        polish_instruction=build_ai_flavor_polish_instruction(summary),
        strategy_bundle_payload=strategy_bundle_payload,
        reference_article_payload=reference_article_payload,
        generator=generator,
        source_draft_title=title,
        source_draft_body_markdown=body_markdown,
        candidate_title=retried_title,
        candidate_body_markdown=retried_body_markdown,
    )
    retried_body_markdown, retried_title = _maybe_retry_polish_for_article_shell_cleanup(
        project=project,
        outline_row=outline_row,
        tone_profile=tone_profile,
        review_comment=review_comment,
        polish_instruction=build_ai_flavor_polish_instruction(summary),
        strategy_bundle_payload=strategy_bundle_payload,
        reference_article_payload=reference_article_payload,
        generator=generator,
        source_draft_title=tracked_shell_source_title,
        source_draft_body_markdown=tracked_shell_source_markdown,
        candidate_title=retried_title,
        candidate_body_markdown=retried_body_markdown,
    )
    retried_body_markdown, retried_title = _maybe_retry_polish_for_remaining_ai_flavor(
        project=project,
        outline_row=outline_row,
        tone_profile=tone_profile,
        review_comment=review_comment,
        polish_instruction=build_ai_flavor_polish_instruction(summary),
        strategy_bundle_payload=strategy_bundle_payload,
        reference_article_payload=reference_article_payload,
        generator=generator,
        source_draft_title=title,
        source_draft_body_markdown=body_markdown,
        candidate_title=retried_title,
        candidate_body_markdown=retried_body_markdown,
    )
    retried_body_markdown, retried_title = _maybe_retry_polish_for_final_ai_flavor_cleanup(
        project=project,
        outline_row=outline_row,
        tone_profile=tone_profile,
        review_comment=review_comment,
        polish_instruction=build_ai_flavor_polish_instruction(summary),
        strategy_bundle_payload=strategy_bundle_payload,
        reference_article_payload=reference_article_payload,
        generator=generator,
        source_draft_title=title,
        source_draft_body_markdown=body_markdown,
        candidate_title=retried_title,
        candidate_body_markdown=retried_body_markdown,
    )
    if _should_prefer_retried_candidate_after_cleanup_preview(
        current_title=best_title,
        current_markdown=best_markdown,
        retried_title=retried_title,
        retried_markdown=retried_body_markdown,
        source_type=str(project["source_type"]),
    ):
        return retried_body_markdown, retried_title
    return best_markdown, best_title


def restore_draft_version(project_slug: str, version: int) -> DraftItem:
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            draft_row = connection.execute(
                """
                SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
                FROM drafts
                WHERE project_slug = ? AND version = ?
                ORDER BY id DESC
                LIMIT 1
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
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(restored=True)
            connection.execute(
                """
                INSERT INTO drafts (
                    project_slug, outline_version, version, title, body_markdown, word_count,
                    created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    draft_row["outline_version"],
                    next_version,
                    draft_row["title"],
                    draft_row["body_markdown"],
                    draft_row["word_count"],
                    created_at,
                    origin,
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
        created_at=created_at,
        origin=origin,
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


def _get_project_version_lock(project_slug: str) -> threading.Lock:
    with _PROJECT_VERSION_LOCKS_GUARD:
        lock = _PROJECT_VERSION_LOCKS.get(project_slug)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_VERSION_LOCKS[project_slug] = lock
        return lock


def _normalize_cover_prompt_layout(prompt: str) -> str:
    normalized = str(prompt).strip()
    normalized = _COVER_PROMPT_LAYOUT_CONFLICT_PATTERN.sub("", normalized)
    normalized = re.sub(r"[，,]\s*[，,]+", "，", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    normalized = normalized.strip(" ，,；;")

    prefix_parts: list[str] = []
    if "21:9" not in normalized and "21：9" not in normalized:
        prefix_parts.append("21:9横版公众号封面")
    elif "横版" not in normalized:
        prefix_parts.append("横版公众号封面")
    if "横向" not in normalized and "宽画幅" not in normalized:
        prefix_parts.append("横向宽画幅构图")
    if "安全区" not in normalized:
        prefix_parts.append("主体位于画面中部安全区")

    if prefix_parts and normalized:
        return f"{'，'.join(prefix_parts)}，{normalized}"
    if prefix_parts:
        return "，".join(prefix_parts)
    return normalized


def _resolve_version_origin(
    *,
    review_comment: str | None = None,
    polish_instruction: str | None = None,
    restored: bool = False,
    cover_regenerated: bool = False,
) -> str:
    if restored:
        return "restore"
    if cover_regenerated:
        return "cover_regeneration"
    if polish_instruction:
        return "polish"
    if review_comment:
        return "review_regeneration"
    return "generate"


def _background_task_log_entity(job_type: str, payload: dict[str, object], task_id: str) -> tuple[str, str]:
    if job_type in PIPELINE_BATCH_TASK_TYPES:
        return "batch", task_id

    project_slug = payload.get("project_slug")
    if project_slug:
        return "project", str(project_slug)

    return "background_task", task_id


def submit_background_task(job_type: str, payload: dict[str, object]) -> BackgroundTaskSubmission:
    task_id = str(uuid.uuid4())
    created_at = _utc_now_iso()
    entity_type, entity_slug = _background_task_log_entity(job_type, payload, task_id)
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
            entity_slug=entity_slug,
            entity_type=entity_type,
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
        elif job_type == "enrich_tracked_articles_metadata":
            result = batch_enrich_tracked_articles_metadata(payload.get("article_slugs"))
        elif job_type == "batch_create_projects":
            result = batch_create_projects(payload.get("topic_slugs"))
        elif job_type == "build_publish_package":
            result = build_publish_package(str(payload["project_slug"]))
        elif job_type == "polish_and_build_publish_package":
            result = polish_and_build_publish_package(
                str(payload["project_slug"]),
                polish_instruction=str(payload.get("polish_instruction") or ""),
            )
        elif job_type == "regenerate_from_review":
            result = regenerate_from_review(str(payload["project_slug"]))
        elif job_type == "regenerate_cover_image":
            result = regenerate_cover_image(str(payload["project_slug"]))
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


def generate_assets(
    project_slug: str,
    *,
    polish_before_generate: bool = False,
    polish_instruction: str | None = None,
) -> AssetItem:
    if polish_before_generate:
        project = _get_project_context(project_slug)
        tone_profile = get_project_tone_profile(project)
        normalized_instruction = (polish_instruction or "").strip()
        effective_instruction = normalized_instruction or tone_profile.default_polish_instruction.strip() or DEFAULT_ASSETS_POLISH_INSTRUCTION
        _generate_draft(project_slug, polish_instruction=effective_instruction)
    return _generate_assets(project_slug)


def regenerate_cover_image(project_slug: str) -> AssetItem:
    project = _get_project_context(project_slug)
    _ensure_generated_assets_dir()
    with _get_project_version_lock(project_slug):
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
                WHERE project_slug = ?
                ORDER BY version DESC, id DESC
                LIMIT 1
                """,
                (project_slug,),
            ).fetchone()
            if not assets_row:
                raise HTTPException(status_code=409, detail="Assets not generated")

            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM assets WHERE project_slug = ?",
                (project_slug,),
            ).fetchone()
            next_version = int(current["version"]) + 1
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(cover_regenerated=True)
            normalized_cover_prompt = _normalize_cover_prompt_layout(str(assets_row["cover_prompt"]))
            cover_filename = f"{project_slug}-assets-v{next_version}.png"
            cover_file_path = GENERATED_ASSETS_DIR / cover_filename
            cover_image_path = ""
            cover_image_url = ""
            try:
                cover_image_bytes = get_ai_generator().generate_cover_image(
                    {
                        "project_slug": project_slug,
                        "project_title": project["title"],
                        "cover_prompt": normalized_cover_prompt,
                        "cover_copy": assets_row["cover_copy"],
                    }
                )
                cover_file_path.write_bytes(cover_image_bytes)
                cover_image_path = str(cover_file_path)
                cover_image_url = f"/generated-assets/{cover_filename}"
            except Exception as exc:
                logger.warning(
                    "Cover image regeneration failed for project %s: %s",
                    project_slug,
                    exc,
                )
                cover_image_path = ""
                cover_image_url = ""

            connection.execute(
                """
                INSERT INTO assets (
                    project_slug, draft_version, version, title_options, cover_prompt, cover_copy, social_teaser,
                    cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    assets_row["draft_version"],
                    next_version,
                    assets_row["title_options"],
                    normalized_cover_prompt,
                    assets_row["cover_copy"],
                    assets_row["social_teaser"],
                    cover_image_path,
                    cover_image_url,
                    created_at,
                    origin,
                    assets_row["tone_profile_id"],
                    assets_row["tone_profile_name"],
                ),
            )
            _record_task(
                connection,
                task_type="cover_image_regenerated",
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
        cover_prompt=normalized_cover_prompt,
        cover_copy=str(assets_row["cover_copy"]),
        social_teaser=str(assets_row["social_teaser"]),
        cover_image_path=cover_image_path,
        cover_image_url=cover_image_url,
        created_at=created_at,
        origin=origin,
        tone_profile_id=int(assets_row["tone_profile_id"]) if assets_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(assets_row["tone_profile_name"]) if assets_row["tone_profile_name"] is not None else None,
    )


def restore_assets_version(project_slug: str, version: int) -> AssetItem:
    with _get_project_version_lock(project_slug):
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
                ORDER BY id DESC
                LIMIT 1
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
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(restored=True)
            connection.execute(
                """
                INSERT INTO assets (
                    project_slug, draft_version, version, title_options, cover_prompt, cover_copy, social_teaser,
                    cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    created_at,
                    origin,
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
        created_at=created_at,
        origin=origin,
        tone_profile_id=int(assets_row["tone_profile_id"]) if assets_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(assets_row["tone_profile_name"]) if assets_row["tone_profile_name"] is not None else None,
    )


def _generate_assets(project_slug: str, *, review_comment: str | None = None) -> AssetItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    domain_pack = get_project_domain_pack(project)
    _ensure_generated_assets_dir()
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            draft_row = connection.execute(
                """
                SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
                FROM drafts
                WHERE project_slug = ?
                ORDER BY version DESC, id DESC
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
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(review_comment=review_comment)
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
                    "domain_pack": domain_pack,
                    "review_comment": review_comment,
                }
            )
            normalized_cover_prompt = _normalize_cover_prompt_layout(str(ai_result["cover_prompt"]))
            cover_filename = f"{project_slug}-assets-v{version}.png"
            cover_file_path = GENERATED_ASSETS_DIR / cover_filename
            cover_image_path = ""
            cover_image_url = ""
            try:
                cover_image_bytes = get_ai_generator().generate_cover_image(
                    {
                        "project_slug": project_slug,
                        "project_title": project["title"],
                        "cover_prompt": normalized_cover_prompt,
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
                    cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    draft_row["version"],
                    version,
                    json.dumps(ai_result["title_options"], ensure_ascii=False),
                    normalized_cover_prompt,
                    ai_result["cover_copy"],
                    ai_result["social_teaser"],
                    cover_image_path,
                    cover_image_url,
                    created_at,
                    origin,
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
        cover_prompt=normalized_cover_prompt,
        cover_copy=str(ai_result["cover_copy"]),
        social_teaser=str(ai_result["social_teaser"]),
        cover_image_path=cover_image_path,
        cover_image_url=cover_image_url,
        created_at=created_at,
        origin=origin,
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
    restored: bool = False,
) -> PublishPackageItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    domain_pack = get_project_domain_pack(project)
    effective_tone_profile_id = tone_profile.id
    effective_tone_profile_name = tone_profile.name
    if package_override and package_override.get("tone_profile_name") is not None:
        effective_tone_profile_id = int(package_override["tone_profile_id"]) if package_override.get("tone_profile_id") is not None else None
        effective_tone_profile_name = str(package_override["tone_profile_name"])
    _ensure_generated_assets_dir()
    with _get_connection() as connection:
        draft_row = connection.execute(
            """
            SELECT project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
            FROM drafts
            WHERE project_slug = ?
            ORDER BY version DESC, id DESC
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
            ORDER BY version DESC, id DESC
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
            "domain_pack": domain_pack,
            "review_comment": review_comment,
        }
    )
    publish_checklist = list(package_override["publish_checklist"]) if package_override and "publish_checklist" in package_override else _build_publish_checklist()

    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM publish_packages WHERE project_slug = ?",
                (project_slug,),
            ).fetchone()
            version = int(current["version"]) + 1
            created_at = _utc_now_iso()
            origin = _resolve_version_origin(
                review_comment=review_comment,
                restored=restored,
            )
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
                "created_at": created_at,
                "origin": origin,
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
        created_at=created_at,
        origin=origin,
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
            ORDER BY id DESC
            LIMIT 1
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
        restored=True,
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


def polish_and_build_publish_package(
    project_slug: str,
    *,
    polish_instruction: str | None = None,
) -> PublishPackageItem:
    project = _get_project_context(project_slug)
    tone_profile = get_project_tone_profile(project)
    normalized_instruction = (polish_instruction or "").strip()
    effective_instruction = normalized_instruction or tone_profile.default_polish_instruction.strip() or DEFAULT_ASSETS_POLISH_INSTRUCTION
    _generate_draft(project_slug, polish_instruction=effective_instruction)
    _generate_assets(project_slug)
    return _build_publish_package(project_slug)


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
        tracked_articles_count = int(connection.execute("SELECT COUNT(*) FROM tracked_articles").fetchone()[0])
        source_ingestion_runs_count = int(connection.execute("SELECT COUNT(*) FROM source_ingestion_runs").fetchone()[0])
        latest_source_ingestion_row = connection.execute(
            """
            SELECT source_kind, completed_at
            FROM source_ingestion_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    latest_source_ingestion_at = (
        str(latest_source_ingestion_row["completed_at"]) if latest_source_ingestion_row is not None else None
    )
    latest_source_ingestion_kind = (
        str(latest_source_ingestion_row["source_kind"]) if latest_source_ingestion_row is not None else None
    )
    source_freshness_state = "missing"
    if latest_source_ingestion_at:
        try:
            completed_at = datetime.fromisoformat(latest_source_ingestion_at)
            source_freshness_state = (
                "fresh"
                if completed_at.astimezone().date() == datetime.now().astimezone().date()
                else "stale"
            )
        except ValueError:
            source_freshness_state = "stale"

    return {
        "today_trends": len(trends),
        "pending_topics": sum(1 for topic in topics if topic.status in {"drafting", "pending"}),
        "draft_ready_projects": sum(1 for project in projects if project.next_required_step is not None),
        "publish_ready_projects": sum(1 for project in projects if project.chain_status == "ready"),
        "tracked_articles_count": tracked_articles_count,
        "source_ingestion_runs_count": source_ingestion_runs_count,
        "latest_source_ingestion_at": latest_source_ingestion_at,
        "latest_source_ingestion_kind": latest_source_ingestion_kind,
        "source_freshness_state": source_freshness_state,
        "recent_tasks": [dict(row) for row in recent_task_rows],
    }


def list_background_task_logs(*, scope: str = "all", limit: int = 20) -> list[TaskLogEntry]:
    bounded_limit = max(1, min(limit, 100))
    query = """
        SELECT id, task_type, status, entity_slug, entity_type, created_at, background_task_id
        FROM task_logs
    """
    parameters: list[object] = []

    if scope == "pipeline":
        placeholders = ", ".join("?" for _ in PIPELINE_BATCH_TASK_TYPES)
        query += f"""
            WHERE task_type IN ({placeholders})
        """
        parameters.extend(PIPELINE_BATCH_TASK_TYPES)

    query += """
        ORDER BY id DESC
        LIMIT ?
    """
    parameters.append(bounded_limit)

    with _get_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()

    return [TaskLogEntry(**dict(row)) for row in rows]


def _continue_project_next_step(project_slug: str, next_required_step: str):
    if next_required_step == "generate_strategy_package":
        return generate_strategy_package(project_slug)
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
        if trend.slug in existing_trend_slugs:
            skipped_count += 1
            results.append(
                BatchGenerateTopicResult(
                    trend_slug=trend.slug,
                    status="skipped",
                    error="Topic already exists for this trend",
                )
            )
            continue
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
        if article.slug in existing_article_slugs:
            skipped_count += 1
            results.append(
                BatchGenerateTrackedArticleTopicResult(
                    article_slug=article.slug,
                    status="skipped",
                    error="Topic already exists for this tracked article",
                )
            )
            continue
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

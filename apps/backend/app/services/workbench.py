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
from typing import Callable, Mapping
from urllib.parse import urlparse

import httpx
import openai
from fastapi import HTTPException
from openai import APIConnectionError, APITimeoutError

from app.core.settings import settings
from app.schemas.background_tasks import BackgroundTaskDetail, BackgroundTaskErrorContext, BackgroundTaskSubmission, TaskLogEntry
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
from app.services.ai_generator import format_image_upstream_failure_message, get_ai_config_summary, get_default_generator
from app.services.ai_flavor import (
    _extract_clause_leading_yi_phrases,
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
    extract_truncated_fragment_paragraphs,
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
    _find_danger_fragment_hits,
    build_diagnosis_polish_instruction,
    build_draft_diagnosis_report,
    build_reference_originality_report,
    resolve_diagnosis_objective_summary,
)
from app.services.draft_quality_summary import build_draft_quality_summary
from app.services.creative_reports import build_creative_review_report
from app.services.creative_patterns import build_reusable_pattern_from_lesson, build_reusable_pattern_id
from app.services.creative_strategy import (
    build_strategy_package,
    normalize_structure_mode_hint,
    resolve_tracked_article_structure_mode,
)
from app.schemas.tone_profiles import ToneProfileItem, ToneProfileReorder, ToneProfileUpsert
from app.services.prompt_templates import DEFAULT_DOMAIN_PROMPT_PACK, get_domain_prompt_pack
from app.services.prompt_templates import (
    _extract_tracked_article_body_cues,
    _extract_tracked_article_emotional_cues,
    _infer_tracked_article_pressure_guard,
    _has_broad_emotional_release_focus,
    _has_everyday_warmth_responsibility_shelter_focus,
    _has_everyday_warmth_return_focus,
    _has_inner_settlement_focus,
    _has_self_reliance_inward_support_focus,
    _has_self_worth_rebuild_focus,
    _has_supportive_appreciation_focus,
    _has_relationship_aftercare_focus,
    _has_response_priority_focus,
    _has_resilience_reconstruction_focus,
    _has_trust_boundary_focus,
    _should_use_tracked_article_strategy_first_draft_mode,
    _uses_response_priority_followup_variant,
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


_OUTLINE_TRANSIENT_PROVIDER_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    openai.InternalServerError,
)

_CREATIVE_UPSTREAM_FAILURE_STATUS_CODE = 503
DB_PATH = Path(settings.db_path)
GENERATED_ASSETS_DIR = Path(settings.generated_assets_dir)
DEFAULT_DB_PATH = Path("C:/tmp/gankaigc-wechat-workbench.db")
_COVER_PROMPT_LAYOUT_CONFLICT_PATTERN = re.compile(
    r"(?:9\s*[:：]\s*16|竖版|竖构图|竖幅|手机竖屏|海报竖版|适合竖版|竖屏)",
    re.IGNORECASE,
)
_COVER_PROMPT_CHAT_UI_PATTERN = re.compile(
    r"(?:手机)?(?:聊天界面|聊天框|输入框|消息气泡|微信聊天|聊天记录|对话界面|对话框)",
    re.IGNORECASE,
)
_COVER_PROMPT_DOUBLE_SCREEN_PATTERN = re.compile(
    r"(?:双面手机|两面手机|前后双屏|前后两块屏幕|背面屏幕|背屏|后背屏幕|手机背面[^，。；;\n]{0,20}屏幕|背面[^，。；;\n]{0,20}聊天界面)",
    re.IGNORECASE,
)
_COVER_PROMPT_PHONE_BACK_SCENE = "人物看手机，手机背面或侧面朝向镜头，屏幕不朝向镜头，不展示可读内容"
_PROJECT_VERSION_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_VERSION_LOCKS_GUARD = threading.Lock()
_TRACKED_ARTICLE_DANGER_FRAGMENT_REPLACEMENTS = {
    "还没发生的": "尚未走到眼前的",
    "没事，有我": "我来想办法",
    "没事有我": "我来想办法",
    "这个月的绩效": "手头的工作考核",
    "这个月的": "眼下这段时间的",
    "缴费窗口前": "办事窗口前",
    "缴费窗口": "办事窗口",
    "一个家的": "一家人的",
    "是不是也": "会不会也",
    "一句话说": "话说",
    "，最后还": "，后来还",
    "。那一刻": "。那个瞬间",
    "回到家那一刻": "推门听见回应时",
    "有人在门口等你": "有人还在惦记你",
    "小安稳": "细小踏实",
    "撑不撑得住": "怎样把顺序理清",
    "撑不住": "想歇一歇",
    "撑稳": "托稳",
    "长期扛压": "长期把家里的事放在心上",
    "扛住压力": "先把事情接住",
    "一路忍着、扛着": "一步步安排、一件件接住",
    "忍着、扛着": "安排着、接住着",
    "成年人扛着的那些压力": "成年人放在心上的那些责任",
    "真正扛着压力往前走": "把责任放在心上认真往前走",
    "扛着压力": "带着责任",
    "白天扛事晚上崩一下": "白天把事情理顺、晚上才松一口气",
    "长期在家庭里当支柱": "长期把家里的事放在心上",
    "天生坚强": "没有自己的难处",
    "崩一下": "松一口气",
    "这些辛苦没有白扛": "这些认真没有白费",
    "辛苦没有白扛": "认真没有白费",
    "辛苦未必值得歌颂，但也没有白扛": "这些认真不必夸大，也没有白费",
    "辛苦未必值得歌颂": "这些认真不必夸大",
    "苦情赞歌": "吃苦叙事",
    "没有白扛": "没有白忙",
    "没白扛": "没有白忙",
    "白扛": "白忙",
    "暂时不能倒": "还要先把事情理顺",
    "不能倒下": "还要把顺序理清",
    "不能倒": "还要把顺序理清",
    "这么苦还要撑": "这么不容易还要把家里理顺",
    "苦难": "难处",
    "苦水": "不容易",
    "风浪": "忙乱",
}
_RESPONSIBILITY_ONLY_DANGER_FRAGMENTS = {
    "没事，有我",
    "没事有我",
    "这个月的",
}
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


@dataclass(frozen=True)
class _CoverImageFileResult:
    path: str
    url: str
    route_label: str | None = None
    route_model: str | None = None
    route_base_url: str | None = None


def _get_project_reference_source_markdown(project: sqlite3.Row | dict[str, object]) -> str:
    try:
        value = project["reference_article_body_markdown"]
    except (LookupError, TypeError):
        return ""
    return str(value or "")


def _apply_initial_draft_candidate_cleanups(
    *,
    title: str,
    body_markdown: str,
    source_type: str,
    reference_source_markdown: str = "",
) -> tuple[str, int]:
    current_body = _strip_draft_response_wrappers(title=title, body_markdown=body_markdown)
    changed_steps = int(current_body != body_markdown)
    responsibility_cleanup = source_type == "tracked_article" and _looks_like_responsibility_shelter_output(
        title=title,
        body_markdown=current_body,
        reference_source_markdown=reference_source_markdown,
    )

    cleanup_steps = _get_initial_draft_candidate_cleanup_steps(source_type=source_type)
    segmented_collapse_applied = False
    post_collapse_split_steps = {
        "split_tracked_article_dense_explainer_residue",
        "split_resilience_dense_paragraph_residue",
        "split_resilience_process_anchor_residue",
    }

    for step_name, cleanup_fn in cleanup_steps:
        if responsibility_cleanup and step_name == "soften_not_ab_residue":
            continue
        if segmented_collapse_applied and step_name in post_collapse_split_steps:
            continue
        collapsed_body = cleanup_fn(
            title=title,
            body_markdown=current_body,
        )
        if collapsed_body != current_body:
            changed_steps += 1
            if step_name in {
                "collapse_over_segmented_shell_residue",
                "collapse_light_segmented_shell_residue",
            }:
                segmented_collapse_applied = True
        current_body = collapsed_body

    if source_type == "tracked_article" and reference_source_markdown:
        rewritten_body = _rewrite_tracked_article_danger_fragments(
            source_markdown=reference_source_markdown,
            body_markdown=current_body,
        )
        if rewritten_body != current_body:
            changed_steps += 1
            current_body = rewritten_body

    if responsibility_cleanup:
        responsibility_body = _sanitize_responsibility_shelter_output_text(current_body)
        responsibility_body = _split_responsibility_shelter_output_paragraphs(responsibility_body)
        if responsibility_body != current_body:
            changed_steps += 1
            current_body = responsibility_body

    return current_body, changed_steps


def _strip_draft_response_wrappers(*, title: str, body_markdown: str) -> str:
    body = str(body_markdown or "").strip()
    body = re.sub(r"^\s*```(?:markdown|md|text)?\s*", "", body, flags=re.IGNORECASE)
    body = re.sub(r"\s*```\s*$", "", body)
    body = re.sub(
        r"^\s*(?:\d+\s*[\.\)：:]?\s*)?(?:\*{1,2}\s*)?(?:标题|title)(?:\s+title)?(?:\s*\*{1,2})?\s*[:：]?\s*",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(
        r"(?:\d+\s*[\.\)：:]?\s*)?(?:\*{1,2}\s*)?(?:正文|body_markdown|markdown\s*body_markdown)(?:\s*\*{1,2})?\s*[:：]?\s*",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"^\s*```(?:markdown|md|text)?\s*", "", body, flags=re.IGNORECASE)
    lines = body.splitlines()
    if lines:
        first_line = re.sub(r"^\s*#+\s*", "", lines[0]).strip()
        normalized_title = re.sub(r"[\s*_`#]+", "", str(title or ""))
        normalized_heading = re.sub(r"[\s*_`#]+", "", first_line)
        if normalized_title and normalized_heading == normalized_title:
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines.pop(0)
            body = "\n".join(lines)
    return body.strip()


def _rewrite_tracked_article_danger_fragments(
    *,
    source_markdown: str,
    body_markdown: str,
) -> str:
    if not source_markdown.strip() or not body_markdown.strip():
        return body_markdown

    responsibility_focus = _looks_like_responsibility_shelter_output(
        title="",
        body_markdown="",
        reference_source_markdown=source_markdown,
    )
    rewritten = body_markdown
    for hit in _find_danger_fragment_hits(source_markdown, body_markdown):
        replacement = _TRACKED_ARTICLE_DANGER_FRAGMENT_REPLACEMENTS.get(hit.fragment)
        if not replacement or replacement == hit.fragment:
            continue
        if hit.fragment in _RESPONSIBILITY_ONLY_DANGER_FRAGMENTS and not responsibility_focus:
            continue
        rewritten = rewritten.replace(hit.fragment, replacement)
    for fragment, replacement in sorted(
        _TRACKED_ARTICLE_DANGER_FRAGMENT_REPLACEMENTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if fragment in _RESPONSIBILITY_ONLY_DANGER_FRAGMENTS and not responsibility_focus:
            continue
        if fragment in source_markdown and fragment in rewritten and replacement != fragment:
            rewritten = rewritten.replace(fragment, replacement)
    return rewritten
def _rewrite_tracked_article_danger_value(
    *,
    source_markdown: str,
    value: object,
) -> str:
    return _rewrite_tracked_article_danger_fragments(
        source_markdown=source_markdown,
        body_markdown=str(value or ""),
    )


def _rewrite_tracked_article_danger_result_fields(
    *,
    source_markdown: str,
    ai_result: Mapping[str, object],
    text_fields: tuple[str, ...],
    list_fields: tuple[str, ...] = (),
) -> dict[str, object]:
    sanitized = dict(ai_result)
    if not source_markdown.strip():
        return sanitized
    for field in text_fields:
        if field in sanitized:
            sanitized[field] = _rewrite_tracked_article_danger_value(
                source_markdown=source_markdown,
                value=sanitized.get(field),
            )
    for field in list_fields:
        value = sanitized.get(field)
        if isinstance(value, list):
            sanitized[field] = [
                _rewrite_tracked_article_danger_value(source_markdown=source_markdown, value=item)
                for item in value
            ]
    return sanitized


def _get_initial_draft_candidate_cleanup_steps(
    *,
    source_type: str,
) -> list[tuple[str, Callable[..., str]]]:
    cleanup_steps: list[tuple[str, Callable[..., str]]] = [
        ("collapse_short_judgment_residue", _collapse_short_judgment_residue),
    ]
    if source_type == "tracked_article":
        cleanup_steps.extend(
            (
                ("collapse_time_chain_shell_residue", _collapse_time_chain_shell_residue),
                ("collapse_embedded_banner_shell_residue", _collapse_embedded_banner_shell_residue),
                ("collapse_explanatory_bridge_residue", _collapse_explanatory_bridge_residue),
                ("collapse_leading_short_long_cadence_residue", _collapse_leading_short_long_cadence_residue),
                ("collapse_short_long_cadence_residue", _collapse_short_long_cadence_residue),
                ("soften_structural_ladder_residue", _soften_structural_ladder_residue),
                ("soften_direct_address_lecture_residue", _soften_direct_address_lecture_residue),
                ("collapse_over_segmented_shell_residue", _collapse_over_segmented_shell_residue),
                ("collapse_light_segmented_shell_residue", _collapse_light_segmented_shell_residue),
                ("soften_not_ab_residue", _soften_not_ab_residue),
                ("strip_rebound_explainer_tail_residue", _strip_rebound_explainer_tail_residue),
                ("strip_orphaned_rebound_tail_residue", _strip_orphaned_rebound_tail_residue),
                ("repair_tracked_article_fragment_residue", _repair_tracked_article_fragment_residue),
                ("repair_self_reliance_expression_sink_residue", _repair_self_reliance_expression_sink_residue),
                ("collapse_isolated_quote_example_residue", _collapse_isolated_quote_example_residue),
                ("repair_repeated_phrase_typo_residue", _repair_repeated_phrase_typo_residue),
                ("repair_tracked_article_dangling_semicolon_chunks", _repair_tracked_article_dangling_semicolon_chunks),
                ("soften_connector_residue", _soften_connector_residue),
                ("split_tracked_article_dense_explainer_residue", _split_tracked_article_dense_explainer_residue),
                ("split_resilience_dense_paragraph_residue", _split_resilience_dense_paragraph_residue),
                ("split_resilience_process_anchor_residue", _split_resilience_process_anchor_residue),
                ("soften_resilience_hook_echo_residue", _soften_resilience_hook_echo_residue),
                ("soften_resilience_local_reference_echo_residue", _soften_resilience_local_reference_echo_residue),
                ("split_tracked_article_long_paragraph_residue", _split_tracked_article_long_paragraph_residue),
                ("split_tracked_article_scene_anchor_residue", _split_tracked_article_scene_anchor_residue),
            )
        )
    return cleanup_steps


def _build_initial_draft_candidate_result(
    *,
    title: str,
    body_markdown: str,
    source_type: str,
    reference_source_markdown: str = "",
) -> _InitialDraftCandidateResult:
    reference_title = title
    reference_body_markdown = body_markdown
    current_body, changed_steps = _apply_initial_draft_candidate_cleanups(
        title=title,
        body_markdown=body_markdown,
        source_type=source_type,
        reference_source_markdown=reference_source_markdown,
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
    reference_source_markdown: str = "",
    selection_context: Mapping[str, object] | None = None,
) -> bool:
    current_candidate = _build_initial_draft_candidate_result(
        title=current_title,
        body_markdown=current_markdown,
        source_type=source_type,
        reference_source_markdown=reference_source_markdown,
    )
    retried_candidate = _build_initial_draft_candidate_result(
        title=retried_title,
        body_markdown=retried_markdown,
        source_type=source_type,
        reference_source_markdown=reference_source_markdown,
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
        selection_context=selection_context,
    )


def _normalize_tracked_article_source_name(source_name: str | None) -> str:
    normalized = (source_name or "").strip()
    return normalized or "手动录入"


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
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
    if "recommended_title" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN recommended_title TEXT NOT NULL DEFAULT ''"
        )
    if "social_teaser_options" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN social_teaser_options TEXT NOT NULL DEFAULT '[]'"
        )
    if "cover_image_path" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_path TEXT NOT NULL DEFAULT ''"
        )
    if "cover_image_url" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_url TEXT NOT NULL DEFAULT ''"
        )
    if "cover_image_status" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_status TEXT NOT NULL DEFAULT 'ready'"
        )
        connection.execute(
            "UPDATE assets SET cover_image_status = 'pending' WHERE TRIM(COALESCE(cover_image_url, '')) = ''"
        )
    if "cover_image_error" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_error TEXT DEFAULT NULL"
        )
    if "cover_image_route_label" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_route_label TEXT DEFAULT NULL"
        )
    if "cover_image_route_model" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_route_model TEXT DEFAULT NULL"
        )
    if "cover_image_route_base_url" not in columns:
        connection.execute(
            "ALTER TABLE assets ADD COLUMN cover_image_route_base_url TEXT DEFAULT NULL"
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
    if "publish_title" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN publish_title TEXT NOT NULL DEFAULT ''"
        )
    if "publish_lead" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN publish_lead TEXT NOT NULL DEFAULT ''"
        )
    if "intro_options" not in columns:
        connection.execute(
            "ALTER TABLE publish_packages ADD COLUMN intro_options TEXT NOT NULL DEFAULT '[]'"
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
            problem_explanation TEXT NOT NULL DEFAULT '',
            emotional_value_goal TEXT NOT NULL DEFAULT '',
            theme_axis TEXT NOT NULL DEFAULT '',
            anti_drift_axis TEXT NOT NULL DEFAULT '',
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
            hook_trigger TEXT NOT NULL DEFAULT '',
            progression_drive TEXT NOT NULL DEFAULT '',
            share_reason TEXT NOT NULL DEFAULT '',
            positive_direction TEXT NOT NULL DEFAULT '',
            quotable_line_goal TEXT NOT NULL DEFAULT '',
            packaging_focus TEXT NOT NULL DEFAULT '',
            packaging_hook TEXT NOT NULL DEFAULT '',
            realism_texture_goal TEXT NOT NULL DEFAULT '',
            structure_mode TEXT NOT NULL DEFAULT '',
            opening_move TEXT NOT NULL DEFAULT '',
            body_shift TEXT NOT NULL DEFAULT '',
            ending_move TEXT NOT NULL DEFAULT '',
            writing_texture_notes TEXT NOT NULL DEFAULT '[]',
            scene_anchor_requirements TEXT NOT NULL DEFAULT '[]',
            quotable_line_seeds TEXT NOT NULL DEFAULT '[]',
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
    if "problem_explanation" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN problem_explanation TEXT NOT NULL DEFAULT ''"
        )
    if "emotional_value_goal" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN emotional_value_goal TEXT NOT NULL DEFAULT ''"
        )
    if "theme_axis" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN theme_axis TEXT NOT NULL DEFAULT ''"
        )
    if "anti_drift_axis" not in problem_brief_columns:
        connection.execute(
            "ALTER TABLE problem_briefs ADD COLUMN anti_drift_axis TEXT NOT NULL DEFAULT ''"
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
    if "hook_trigger" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN hook_trigger TEXT NOT NULL DEFAULT ''"
        )
    if "progression_drive" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN progression_drive TEXT NOT NULL DEFAULT ''"
        )
    if "share_reason" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN share_reason TEXT NOT NULL DEFAULT ''"
        )
    if "positive_direction" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN positive_direction TEXT NOT NULL DEFAULT ''"
        )
    if "quotable_line_goal" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN quotable_line_goal TEXT NOT NULL DEFAULT ''"
        )
    if "packaging_focus" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN packaging_focus TEXT NOT NULL DEFAULT ''"
        )
    if "packaging_hook" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN packaging_hook TEXT NOT NULL DEFAULT ''"
        )
    if "realism_texture_goal" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN realism_texture_goal TEXT NOT NULL DEFAULT ''"
        )
    if "writing_texture_notes" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN writing_texture_notes TEXT NOT NULL DEFAULT '[]'"
        )
    if "scene_anchor_requirements" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN scene_anchor_requirements TEXT NOT NULL DEFAULT '[]'"
        )
    if "quotable_line_seeds" not in strategy_card_columns:
        connection.execute(
            "ALTER TABLE strategy_cards ADD COLUMN quotable_line_seeds TEXT NOT NULL DEFAULT '[]'"
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
            analysis_theme TEXT NOT NULL DEFAULT '',
            analysis_core_conflict TEXT NOT NULL DEFAULT '',
            analysis_emotional_exit TEXT NOT NULL DEFAULT '',
            analysis_structure_mode TEXT NOT NULL DEFAULT '',
            analysis_opening_pattern TEXT NOT NULL DEFAULT '',
            analysis_hook_trigger TEXT NOT NULL DEFAULT '',
            analysis_progression_drive TEXT NOT NULL DEFAULT '',
            analysis_share_reason TEXT NOT NULL DEFAULT '',
            analysis_do_not_turn_into TEXT NOT NULL DEFAULT '',
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
    if "analysis_theme" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_theme TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_core_conflict" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_core_conflict TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_emotional_exit" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_emotional_exit TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_structure_mode" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_structure_mode TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_opening_pattern" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_opening_pattern TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_hook_trigger" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_hook_trigger TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_progression_drive" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_progression_drive TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_share_reason" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_share_reason TEXT NOT NULL DEFAULT ''"
        )
    if "analysis_do_not_turn_into" not in columns:
        connection.execute(
            "ALTER TABLE tracked_articles ADD COLUMN analysis_do_not_turn_into TEXT NOT NULL DEFAULT ''"
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


def _ensure_runtime_chain_schema(connection: sqlite3.Connection) -> None:
    _ensure_projects_schema(connection)
    _ensure_topics_schema(connection)
    _ensure_creative_workflow_schema(connection)
    _ensure_outlines_schema(connection)
    _ensure_drafts_schema(connection)
    _ensure_assets_schema(connection)
    _ensure_publish_packages_schema(connection)
    _ensure_project_retros_schema(connection)
    _ensure_tone_profiles_schema(connection)
    _ensure_tracked_articles_schema(connection)


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
                recommended_title TEXT NOT NULL DEFAULT '',
                cover_prompt TEXT NOT NULL,
                cover_copy TEXT NOT NULL,
                social_teaser TEXT NOT NULL,
                social_teaser_options TEXT NOT NULL DEFAULT '[]',
                cover_image_path TEXT NOT NULL,
                cover_image_url TEXT NOT NULL,
                cover_image_status TEXT NOT NULL DEFAULT 'ready',
                cover_image_error TEXT DEFAULT NULL,
                cover_image_route_label TEXT DEFAULT NULL,
                cover_image_route_model TEXT DEFAULT NULL,
                cover_image_route_base_url TEXT DEFAULT NULL,
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
                publish_title TEXT NOT NULL DEFAULT '',
                publish_lead TEXT NOT NULL DEFAULT '',
                intro_options TEXT NOT NULL DEFAULT '[]',
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
    analysis_theme = str(row["analysis_theme"]) if "analysis_theme" in row.keys() else ""
    analysis_core_conflict = str(row["analysis_core_conflict"]) if "analysis_core_conflict" in row.keys() else ""
    analysis_emotional_exit = str(row["analysis_emotional_exit"]) if "analysis_emotional_exit" in row.keys() else ""
    analysis_opening_pattern = str(row["analysis_opening_pattern"]) if "analysis_opening_pattern" in row.keys() else ""
    analysis_hook_trigger = str(row["analysis_hook_trigger"]) if "analysis_hook_trigger" in row.keys() else ""
    analysis_progression_drive = str(row["analysis_progression_drive"]) if "analysis_progression_drive" in row.keys() else ""
    analysis_share_reason = str(row["analysis_share_reason"]) if "analysis_share_reason" in row.keys() else ""
    analysis_do_not_turn_into = str(row["analysis_do_not_turn_into"]) if "analysis_do_not_turn_into" in row.keys() else ""
    tags = _normalize_tracked_article_tags(json.loads(str(row["tags"])))
    metadata = _sanitize_responsibility_shelter_tracked_article_metadata(
        {
            "summary": summary,
            "structure_notes": str(row["structure_notes"]),
            "analysis_theme": analysis_theme,
            "analysis_core_conflict": analysis_core_conflict,
            "analysis_emotional_exit": analysis_emotional_exit,
            "analysis_structure_mode": str(row["analysis_structure_mode"]) if "analysis_structure_mode" in row.keys() else "",
            "analysis_opening_pattern": analysis_opening_pattern,
            "analysis_hook_trigger": analysis_hook_trigger,
            "analysis_progression_drive": analysis_progression_drive,
            "analysis_share_reason": analysis_share_reason,
            "analysis_do_not_turn_into": analysis_do_not_turn_into,
        },
        article_title=str(row["title"]),
        body_markdown=body_markdown,
        tags=tags,
    )
    summary = str(metadata["summary"])
    structure_notes = str(metadata["structure_notes"])
    analysis_theme = str(metadata["analysis_theme"])
    analysis_core_conflict = str(metadata["analysis_core_conflict"])
    analysis_emotional_exit = str(metadata["analysis_emotional_exit"])
    analysis_opening_pattern = str(metadata["analysis_opening_pattern"])
    analysis_hook_trigger = str(metadata["analysis_hook_trigger"])
    analysis_progression_drive = str(metadata["analysis_progression_drive"])
    analysis_share_reason = str(metadata["analysis_share_reason"])
    analysis_do_not_turn_into = str(metadata["analysis_do_not_turn_into"])
    tags = _normalize_tracked_article_tags(metadata.get("tags"))
    analysis_structure_mode = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary=summary,
        structure_notes=structure_notes,
        analysis_structure_mode_hint=str(metadata.get("analysis_structure_mode") or ""),
        analysis_theme=analysis_theme,
        analysis_core_conflict=analysis_core_conflict,
        analysis_emotional_exit=analysis_emotional_exit,
        analysis_opening_pattern=analysis_opening_pattern,
        analysis_do_not_turn_into=analysis_do_not_turn_into,
    )
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
        structure_notes=structure_notes,
        analysis_theme=analysis_theme,
        analysis_core_conflict=analysis_core_conflict,
        analysis_emotional_exit=analysis_emotional_exit,
        analysis_structure_mode=analysis_structure_mode,
        analysis_opening_pattern=analysis_opening_pattern,
        analysis_hook_trigger=analysis_hook_trigger,
        analysis_progression_drive=analysis_progression_drive,
        analysis_share_reason=analysis_share_reason,
        analysis_do_not_turn_into=analysis_do_not_turn_into,
        created_at=str(row["created_at"]) if "created_at" in row.keys() and row["created_at"] is not None else None,
        tags=tags,
    )


def _get_tracked_article_row_by_slug(connection: sqlite3.Connection, article_slug: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes,
               analysis_theme, analysis_core_conflict, analysis_emotional_exit, analysis_structure_mode,
               analysis_opening_pattern, analysis_hook_trigger, analysis_progression_drive, analysis_share_reason,
               analysis_do_not_turn_into, created_at, tags
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
        SELECT slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes,
               analysis_theme, analysis_core_conflict, analysis_emotional_exit, analysis_structure_mode,
               analysis_opening_pattern, analysis_hook_trigger, analysis_progression_drive, analysis_share_reason,
               analysis_do_not_turn_into, created_at, tags
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
        INSERT INTO tracked_articles (
            slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes,
            analysis_theme, analysis_core_conflict, analysis_emotional_exit, analysis_structure_mode,
            analysis_opening_pattern, analysis_hook_trigger, analysis_progression_drive, analysis_share_reason,
            analysis_do_not_turn_into, created_at, tags
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            payload.analysis_theme,
            payload.analysis_core_conflict,
            payload.analysis_emotional_exit,
            normalize_structure_mode_hint(payload.analysis_structure_mode),
            payload.analysis_opening_pattern,
            payload.analysis_hook_trigger,
            payload.analysis_progression_drive,
            payload.analysis_share_reason,
            payload.analysis_do_not_turn_into,
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
            SELECT slug, source_kind, source_name, title, url, author, summary, body_markdown, body_source, structure_notes,
                   analysis_theme, analysis_core_conflict, analysis_emotional_exit, analysis_structure_mode,
                   analysis_opening_pattern, analysis_hook_trigger, analysis_progression_drive, analysis_share_reason,
                   analysis_do_not_turn_into, created_at, tags
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
            SET body_markdown = ?, body_source = ?,
                analysis_theme = '', analysis_core_conflict = '', analysis_emotional_exit = '',
                analysis_structure_mode = '', analysis_opening_pattern = '', analysis_hook_trigger = '',
                analysis_progression_drive = '', analysis_share_reason = '', analysis_do_not_turn_into = ''
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


def _sanitize_responsibility_shelter_metadata_text(value: str) -> str:
    sanitized = re.sub(r"\s+", " ", str(value or "")).strip()
    for source, replacement in sorted(
        _RESPONSIBILITY_SHELTER_METADATA_REPLACEMENTS,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        sanitized = sanitized.replace(source, replacement)
    return sanitized.strip()


def _sanitize_responsibility_shelter_metadata_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        value = str(tag or "").strip()
        for source, replacement in sorted(
            _RESPONSIBILITY_SHELTER_METADATA_TAG_REPLACEMENTS,
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            value = value.replace(source, replacement)
        value = value.strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized[:8]


def _sanitize_responsibility_shelter_tracked_article_metadata(
    metadata: Mapping[str, object],
    *,
    article_title: str,
    body_markdown: str,
    tags: list[str],
) -> dict[str, object]:
    normalized = dict(metadata)
    normalized["tags"] = _normalize_tracked_article_tags(tags)
    probe = {
        "source_type": "tracked_article",
        "article_title": article_title,
        "title": article_title,
        "body_markdown": body_markdown,
        "tags": normalized["tags"],
        **normalized,
    }
    if not _has_everyday_warmth_responsibility_shelter_focus(probe):
        return normalized

    text_fields = (
        "summary",
        "structure_notes",
        "analysis_theme",
        "analysis_core_conflict",
        "analysis_emotional_exit",
        "analysis_opening_pattern",
        "analysis_hook_trigger",
        "analysis_progression_drive",
        "analysis_share_reason",
        "analysis_do_not_turn_into",
    )
    for field in text_fields:
        normalized[field] = _sanitize_responsibility_shelter_metadata_text(str(normalized.get(field) or ""))
    normalized["tags"] = _sanitize_responsibility_shelter_metadata_tags(tags)
    return normalized


def _tracked_article_has_analysis(article: TrackedArticleItem) -> bool:
    return all(getattr(article, field, "").strip() for field in _TRACKED_ARTICLE_ANALYSIS_FIELDS[:4])


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
    "旧关系",
    "完整定义",
    "追讨完整定义",
    "关系结束",
    "再坚持一下",
    "止损",
)
_ABSTRACT_EMOTIONAL_RELEASE_MEMORY_TOKENS = (
    "要是他还在",
    "他还在就好了",
    "还没来得及",
    "很多时候",
    "忘不掉",
    "忘不了",
    "回潮",
    "意难平",
    "没说完的话",
    "没兑现的承诺",
    "没被接住",
    "未完成",
    "背影",
    "擦肩",
    "旧相册",
    "聊天记录",
    "往事会自行爬上来",
    "碰不到摸不着",
    "遗忘再长",
)
_ABSTRACT_EVERYDAY_WARMTH_PRESSURE_TOKENS = (
    "体检",
    "复查",
    "身体提醒",
    "身体信号",
    "求救信号",
    "排在待办清单最后",
    "排在最后",
    "往后排",
    "排后面",
    "压后",
    "追债",
    "自我照料",
)
_ABSTRACT_EVERYDAY_WARMTH_RELATIONSHIP_TOKENS = (
    "有人等你回应",
    "等你回应",
    "把关系接住",
    "关系接住",
    "回应顺序",
    "先接住关系",
    "失去什么",
    "成年女性",
)
_ABSTRACT_EVERYDAY_WARMTH_GROWTH_TOKENS = (
    "重建的是生活托底感",
    "生活托底感",
    "情绪托底",
    "托底",
    "意义供给",
    "高光退潮",
    "成长转向",
    "空心感",
    "空心",
    "没意思",
    "提不起劲",
    "怎么办",
    "中年以后",
    "更需要重估哪些事",
    "重估哪些事",
)
_ABSTRACT_SCENE_FIRST_TITLE_TOKENS = (
    "很多关系",
    "为什么",
    "真正被耗掉的是",
    "真正失去的是",
    "最难恢复的",
    "慢慢失联",
    "重要的话",
    "表达时机感",
)
_ABSTRACT_SCENE_FIRST_ANGLE_TOKENS = (
    "拆开一种",
    "拆开女性在",
    "拆成一种常见",
    "为什么总",
    "怎样一步步",
    "如何一步步",
    "慢慢失去",
    "内部时机",
    "人际预判机制",
)
_TRACKED_ARTICLE_ANALYSIS_FIELDS = (
    "analysis_theme",
    "analysis_core_conflict",
    "analysis_emotional_exit",
    "analysis_structure_mode",
    "analysis_opening_pattern",
    "analysis_hook_trigger",
    "analysis_progression_drive",
    "analysis_share_reason",
    "analysis_do_not_turn_into",
)

_RESPONSIBILITY_SHELTER_METADATA_REPLACEMENTS = (
    ("撑不撑得住", "怎样把顺序理清"),
    ("撑不住", "想歇一歇"),
    ("撑稳", "托稳"),
    ("长期扛压", "长期把家里的事放在心上"),
    ("扛住压力", "先把事情接住"),
    ("一路忍着、扛着", "一步步安排、一件件接住"),
    ("忍着、扛着", "安排着、接住着"),
    ("成年人扛着的那些压力", "成年人放在心上的那些责任"),
    ("真正扛着压力往前走", "把责任放在心上认真往前走"),
    ("很多人以为，责任重的人一定很有力量。其实不是。责任最重的地方，往往只是心里一直装着想守护的人。", "责任重的人，也会累。只是心里一直装着想守护的人，所以愿意把眼前的事再理一理。"),
    ("扛着压力", "带着责任"),
    ("白天扛事晚上崩一下", "白天把事情理顺、晚上才松一口气"),
    ("长期在家庭里当支柱", "长期把家里的事放在心上"),
    ("天生坚强", "没有自己的难处"),
    ("崩一下", "松一口气"),
    ("这些辛苦没有白扛", "这些认真没有白费"),
    ("辛苦没有白扛", "认真没有白费"),
    ("辛苦未必值得歌颂，但也没有白扛", "这些认真不必夸大，也没有白费"),
    ("辛苦未必值得歌颂", "这些认真不必夸大"),
    ("苦情赞歌", "吃苦叙事"),
    ("没有白扛", "没有白忙"),
    ("没白扛", "没有白忙"),
    ("白扛", "白忙"),
    ("暂时不能倒", "还要先把事情理顺"),
    ("不能倒下", "还要把顺序理清"),
    ("不能倒", "还要把顺序理清"),
    ("这么苦还要撑", "这么不容易还要把家里理顺"),
    ("吞下去的辛苦", "一路走来的认真"),
    ("把慌乱咽下去", "把顺序理清楚"),
    ("身体报警", "身体提醒"),
    ("身体告警", "身体提醒"),
    ("成年人硬撑", "家庭责任"),
    ("长期硬撑", "长时间不容易"),
    ("夜里硬撑", "夜里不容易"),
    ("把辛苦咽下去", "把责任放在心上"),
    ("把苦咽下去", "把日子认真托住"),
    ("咽下生活的苦", "认真走过生活里的难"),
    ("辛苦咽下去", "责任放在心上"),
    ("咽下去", "认真走过去"),
    ("咽下", "认真走过"),
    ("硬扛压力", "认真托住家里的事"),
    ("硬扛", "先把事情接住"),
    ("硬撑", "认真托住日子"),
    ("强撑", "先把事情稳住"),
    ("继续撑住", "继续认真往前走"),
    ("撑住了一家人的基本秩序", "托住了一家人的基本秩序"),
    ("撑住一家人的基本秩序", "托住一家人的基本秩序"),
    ("你为家多想的每一步，", "那些为家多想的每一步，"),
    ("你先把能协调的时间圈出来，", "能协调的时间先圈出来，"),
    ("你在纸上把事情一项项写下来，", "纸上把事情一项项写下来，"),
    ("你可以把话说得更慢一点，", "有些话可以说得更慢一点，"),
    ("你替一家人多想一步，", "替一家人多想一步的时候，"),
    ("继续撑下去", "继续认真往前走"),
    ("撑下去", "继续往前走"),
    ("或倒下", "或停下"),
    ("倒下", "停下"),
    ("沉默疲惫", "不张扬的责任感"),
    ("长期疲惫、委屈、想停下却不敢停的内在消耗", "现实责任和自己也需要被照顾之间的拉扯"),
    ("长期疲惫", "长时间不容易"),
    ("疲惫", "不容易"),
    ("内在消耗", "心里的不容易"),
    ("消耗", "不容易"),
    ("孤撑感", "被理解的责任感"),
    ("孤立无援", "有人一起分担"),
    ("咬牙", "撑着"),
    ("没事，有我", "先把家里理顺"),
    ("没事有我", "先把家里理顺"),
    ("喉咙发紧", "心里开始排顺序"),
    ("万般辛苦", "那些认真托住日子的时刻"),
    ("人间安稳", "家里的踏实"),
    ("苦难必有回报", "认真走过的日子会慢慢有回响"),
    ("苦难勋章", "日子回响"),
    ("苦难赞歌", "空泛吃苦叙事"),
    ("苦难", "难处"),
    ("苦水", "不容易"),
    ("风浪", "忙乱"),
    ("白熬", "白费"),
    ("苦熬", "认真走过"),
    ("那一刻", "那个瞬间"),
    ("你会发现", "你会慢慢看见"),
    ("不是没有", "并不是全无"),
)

_RESPONSIBILITY_SHELTER_METADATA_TAG_REPLACEMENTS = (
    ("长期扛压", "责任被看见"),
    ("不能倒下", "责任被看见"),
    ("不能倒", "责任被看见"),
    ("长期硬撑", "责任被看见"),
    ("夜里硬撑", "责任被看见"),
    ("成年人硬撑", "家庭责任"),
    ("硬撑", "家庭责任"),
    ("硬扛", "家庭责任"),
    ("沉默疲惫", "责任被看见"),
    ("孤撑", "责任被看见"),
    ("人间安稳", "家里踏实"),
    ("中年压力", "中年责任"),
)
_ABSTRACT_RESPONSE_PRIORITY_AFTERCARE_TOKENS = (
    "善后",
    "把日子重新接上",
    "自己消化情绪",
    "吵完架以后",
    "回避修复",
    "关系回暖",
    "冷战",
    "争执过后",
)
_ABSTRACT_RESPONSIBILITY_SHELTER_TITLE_TOKENS = (
    "消化情绪",
    "缓一会儿",
    "缓很久",
    "替全家",
    "全家",
)
_RESPONSIBILITY_SHELTER_NEGATIVE_TOPIC_TOKENS = (
    "熬沉默",
    "挂了电话才敢累",
)
_RESPONSIBILITY_SHELTER_TITLE_HARD_ANCHOR_TOKENS = (
    "责任",
    "肩上",
    "家里",
    "灯",
    "硬撑",
    "撑住",
    "安稳",
)
_ABSTRACT_INNER_SETTLEMENT_RELATIONSHIP_TOKENS = (
    "等你回应",
    "回应顺序",
    "等一个交代",
    "交代",
    "旧关系",
    "没收好的旧关系",
    "聊天框",
    "消息框",
    "对话框",
    "没被接住",
    "他还在",
)
_ABSTRACT_INNER_SETTLEMENT_PRESSURE_TOKENS = (
    "体检",
    "复查",
    "复诊",
    "身体提醒",
    "身体信号",
    "求救信号",
    "待办清单最后",
    "排在待办清单最后",
    "排在最后",
    "身体追债",
    "自我照料",
    "排回前面",
)
_ABSTRACT_INNER_SETTLEMENT_HAPPINESS_TOKENS = (
    "幸福是什么",
    "幸福是得到",
    "幸福是放下",
    "不再强求",
    "放手",
    "得不到",
    "别无所求",
    "知足",
)
_INNER_SETTLEMENT_TOPIC_ANCHOR_TOKENS = (
    "心安",
    "安顿",
    "归处",
    "内心",
    "与内心和解",
    "把心放平",
    "把事看淡",
    "一餐一饮",
    "一呼一吸",
    "把自己放回",
    "心里一直",
    "心无挂碍",
    "安稳",
)
_INNER_SETTLEMENT_POSITIVE_TOKENS = (
    "安放",
    "安稳",
    "放平",
    "松下来",
    "归处",
    "轻重",
    "顺起来",
    "住进去",
)
_INNER_SETTLEMENT_RETURN_ANCHOR_TOKENS = (
    "心安",
    "安顿",
    "归处",
    "回到当下",
    "一餐一饮",
    "一呼一吸",
    "把自己放回",
    "住回",
    "轻重",
)
_INNER_SETTLEMENT_DIAGNOSTIC_TOKENS = (
    "更难落地",
    "卡住",
    "卡在",
    "悬着",
    "复盘过去",
    "演练未来",
    "最坏的结果",
    "值班",
    "失控",
)
_INNER_SETTLEMENT_STAGE_RESTART_TOKENS = (
    "上半年",
    "下半年",
    "半年",
    "事与愿违",
    "另有安排",
    "做好眼前事",
    "珍惜身边人",
    "珍惜身边所爱之人",
    "每一段人生",
    "这个年龄真好",
    "我在哪个年龄段",
    "努力不被辜负",
    "幸运不期而遇",
    "快乐无需假装",
    "重新等待",
    "重新出发",
    "接受每一个阶段的自己",
    "过好每一个阶段的人生",
)
_INNER_SETTLEMENT_TITLE_WAITING_SINK_TOKENS = (
    "把安稳交给结果",
    "把心安交给结果",
    "把安全感押在结果上",
    "把安全感押在外部结果上",
    "把平静押在结果上",
    "把平静押在外部结果上",
    "把确认留给别人",
    "等一个结果",
    "等一个回应",
    "等一个答案",
)
_INNER_SETTLEMENT_ANGLE_WAITING_SINK_TOKENS = (
    "把情绪稳定交给回复",
    "把情绪稳定交给评价",
    "把情绪稳定交给回复、评价和结果",
    "把平静押在关系、工作和他人评价的结论上",
    "把平静押在结果上",
    "把平静押在外部结果上",
    "把安全感押在结果上",
    "把安全感押在外部结果上",
    "把安全感都押在外部",
    "日子落不了地",
    "从等待里接回来",
    "迟迟不肯把自己从等待里接回来",
)
_EVERYDAY_WARMTH_TOPIC_ANCHOR_TOKENS = (
    "大事",
    "小事",
    "陪伴",
    "简单快乐",
    "知己",
    "家人",
    "平安",
    "一家温暖",
    "有家可回",
    "踏实",
    "人间烟火",
    "祛魅",
    "日常",
    "热饭",
    "回家",
    "有人惦记",
    "晚安",
    "说心里话",
)
_ABSTRACT_RESILIENCE_SELF_HELP_TOKENS = (
    "女性",
    "把自己放最后",
    "把自己排到最后",
    "列表最底下",
    "提醒列表",
    "先照顾别人",
    "照顾别人",
    "兜底",
    "自我照顾",
    "先把自己",
    "排回前面",
)
_SELF_RELIANCE_RELATIONSHIP_SINK_TOKENS = (
    "说得很轻",
    "不好意思开口",
    "不敢开口",
    "想开口",
    "说不出口",
    "越想解释",
    "被误解",
    "边界不清",
    "需求不明",
    "关系里",
    "真正的帮助",
    "真正的支持",
    "求助包装",
    "顺手帮一下",
)
_SELF_RELIANCE_THEME_ANCHOR_TOKENS = (
    "向内求",
    "自我支撑",
    "自我修复",
    "自我托住",
    "自救自渡",
    "把自己托起来",
    "把自己托过去",
    "把自己稳住",
    "先把自己稳住",
    "判断",
    "行动",
    "恢复力",
    "求助",
    "分担",
    "别人也各自承压",
)
_ABSTRACT_RELATIONSHIP_AFTERCARE_WITHDRAWN_TOKENS = (
    "求助能力",
    "自我消化",
    "独自消化",
    "把自己哄好",
    "把自己收拾好",
    "先撤回依赖",
    "关掉表达",
    "不再说",
)
_RESPONSE_PRIORITY_TOPIC_ANCHOR_TOKENS = (
    "没时间",
    "优先级",
    "回应",
    "时间分配",
    "在乎",
    "顺序",
    "时间在哪儿",
    "心就在哪儿",
    "排在前面",
    "评论",
    "追问",
    "接住",
    "读懂",
    "注意力",
    "我没事",
)
_RESPONSE_PRIORITY_PRESSURE_SINK_TOKENS = (
    "身体代价链",
    "身体提醒",
    "求救信号",
    "压后",
    "往后推",
    "复查",
    "体检",
    "胃疼",
    "心慌",
    "该停下来",
)
_SUPPORTIVE_APPRECIATION_TOPIC_ANCHOR_TOKENS = (
    "心软",
    "柔软",
    "包容",
    "体谅",
    "温柔",
    "珍惜",
    "值得被珍惜",
    "不糊涂",
    "拎得清",
)
_SELF_WORTH_REBUILD_TOPIC_ANCHOR_TOKENS = (
    "爱自己",
    "自爱",
    "自尊",
    "自我价值",
    "养贵",
    "打折品",
    "奢侈品",
    "将就",
    "贬值",
    "配得上",
    "身价",
    "边界",
    "标准",
    "体面",
)
_ABSTRACT_SELF_WORTH_REBUILD_COLLAPSE_TOKENS = (
    "优先级",
    "没时间",
    "被敷衍",
    "回应顺序",
    "被排在前面",
    "改约",
    "都行",
    "不方便",
    "善后",
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


def _rewrite_pressure_interface_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    corpus = " ".join(
        part
        for part in (
            str(payload.get("body_markdown") or ""),
            str(payload.get("reference_article_body_markdown") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("structure_notes") or ""),
        )
        if part
    )
    title = str(ai_result.get("title") or "").strip()
    if not title or any(token in title for token in ("很多答案", "真正重要的地方", "过到眼前")):
        if any(token in corpus for token in ("复查", "体检", "饭点", "晚饭", "生活顺序", "照顾自己", "自我照料")):
            title = "把被挪走的生活顺序，一点点调回来"
        else:
            title = "把该照顾自己的那一步，放回今天"
    angle = (
        "从复查提醒、晚饭和休息一次次被往后挪切入，"
        "写照顾自己不是暂停责任，而是把生活顺序一点点调回来；"
        "最后落到人先回稳，后面的日子才更有力量。"
    )
    return {"title": title, "angle": angle}


def _should_rewrite_emotional_release_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if _has_everyday_warmth_return_focus(payload):
        return False
    memory_variant = _uses_local_emotional_memory_presence_variant(payload) or _uses_local_emotional_memory_reflux_variant(payload)
    endings_acceptance_variant = _uses_local_emotional_endings_acceptance_variant(payload)
    regret_forward_variant = _uses_local_emotional_regret_forward_variant(payload)
    if not _has_broad_emotional_release_focus(payload) and not (
        memory_variant or endings_acceptance_variant or regret_forward_variant
    ):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if memory_variant:
        has_memory_focus = _has_local_emotional_memory_reflux_result_focus(combined)
        has_generic_acceptance = any(
            token in combined
            for token in (
                "感谢相遇",
                "不谈亏欠",
                "继续往前",
                "允许一切结束",
                "允许一切发生",
                "成全后来的你",
                "释怀",
                "放下",
            )
        )
        if has_generic_acceptance or not has_memory_focus:
            return True
    if regret_forward_variant:
        return True
    return any(token in combined for token in _ABSTRACT_EMOTIONAL_RELEASE_RELATIONSHIP_TOKENS) or any(
        token in combined for token in _ABSTRACT_EMOTIONAL_RELEASE_MEMORY_TOKENS
    )


def _rewrite_emotional_release_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    cues = _extract_tracked_article_emotional_cues(payload, max_items=3)
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)
    if not cues:
        cues = _extract_tracked_article_emotional_cues(
            {
                "body_markdown": corpus,
                "summary": summary,
                "structure_notes": structure_notes,
            },
            max_items=3,
        )
    if not cues:
        cues = []

    joined_cues = " ".join(cues)
    regret_forward = _uses_local_emotional_regret_forward_variant(payload)
    endings_acceptance = _uses_local_emotional_endings_acceptance_variant(payload)
    reflux_anchor = any(
        token in corpus or token in joined_cues
        for token in (
            "旧相册",
            "聊天记录",
            "旧关系",
            "回潮",
            "旧事会回潮",
            "往事会自行爬上来",
            "没收好",
            "普通时刻反复",
        )
    )
    memory_reflux = reflux_anchor or (
        not _uses_local_emotional_memory_presence_variant(payload)
        and _uses_local_emotional_memory_reflux_variant(payload)
        and not regret_forward
    )
    memory_presence = (not memory_reflux) and (not regret_forward) and _uses_local_emotional_memory_presence_variant(payload)
    if regret_forward:
        new_title = "旧事可以收起来，脚下的路还要往前走"
    elif endings_acceptance:
        new_title = "有些相遇没能走到最后，却会悄悄成全后来的你"
    elif memory_presence:
        new_title = "有些人走远了，还是会在你的日常里轻轻回来"
    elif memory_reflux:
        new_title = "那段旧关系没收好，往事就会在某个普通时刻回潮"
    elif "幸福" in joined_cues and any(token in joined_cues for token in ("放下", "不再强求", "强求")):
        new_title = "你以为幸福是得到，后来才懂有些幸福叫放下"
    elif any(token in joined_cues for token in ("不再强求", "强求", "放手")):
        new_title = "人最容易错过的幸福，往往藏在不再强求以后"
    else:
        new_title = title

    if regret_forward:
        new_angle = (
            "从旧裙子、旧物和那句“如果当初”切入，"
            "写人为什么会反复替过去改写结局；"
            "重点不是劝人忘记遗憾，而是把回不去的旧事体面收好，"
            "让心重新轻一点，也让脚下的日子继续往前走。"
        )
    elif endings_acceptance:
        new_angle = (
            "从人为什么总把一段关系的结束理解成白费切入，"
            "写真正让人难过的，常常不是离开本身，"
            "而是舍不得承认有些相遇本来就有阶段；"
            "也写人怎样把留下来的温暖、眼界和成长收回自己身上，"
            "带着感谢继续往前。"
        )
    elif memory_presence:
        new_angle = (
            "从街头背影、擦肩和那句“要是他还在就好了”切入，"
            "写有些人走远后为什么仍会在普通日子里轻轻回来；"
            "也写真正的放下不是否认想念，而是让那段真实来过的温暖，"
            "慢慢变成今天继续往前的力气。"
        )
    elif memory_reflux:
        new_angle = (
            "从街头背影、旧相册、聊天记录这些回潮瞬间切入，"
            "写人为什么会反复想起一个已经走远的人："
            "真正挂住人的，往往不只是那个人，"
            "还有没说完的话、没被接住的自己，"
            "以及那段一直没被好好安放的旧关系；"
            "也写当你不再拿今天去补昨天，日子才会慢慢亮起来。"
        )
    elif any(token in joined_cues for token in ("珍惜", "知足", "拥有")):
        new_angle = "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。"
    else:
        new_angle = "从人为什么总在得不到的东西上反复拉扯切入，写强求怎样一点点耗尽自己，以及放下为什么反而让人更接近真正的幸福。"
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_relationship_aftercare_withdrawn_topic(
    payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> bool:
    if not _has_relationship_aftercare_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    return any(token in combined for token in _ABSTRACT_RELATIONSHIP_AFTERCARE_WITHDRAWN_TOKENS)


def _rewrite_relationship_aftercare_withdrawn_topic(
    payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> dict[str, str]:
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()

    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if any(token in corpus for token in ("推开", "不再示弱", "示弱")):
        new_title = "被推开几次以后，很多人就不再开口了"
        new_angle = (
            "从一个人为什么会在最需要被接住的时候先把话咽回去切入，"
            "写她在关系里怎样一次次把求助、示弱和真实反应往后收；"
            "重点放在谁误解了她、谁没有接住她，以及这份后撤后来怎样慢慢改写关系。"
        )
    elif any(token in corpus for token in ("嫌烦", "不被理解", "误读")):
        new_title = "总在脆弱时被嫌烦的人，后来会先把求助咽回去"
        new_angle = (
            "从一个人为什么会在最需要被接住的时候先把话咽回去切入，"
            "写她在关系里怎样一次次把求助、示弱和真实反应往后收；"
            "重点放在谁误解了她、谁没有接住她，以及这份后撤后来怎样慢慢改写关系。"
        )
    elif any(token in corpus for token in ("吵架", "争吵", "冷暴力", "达成共识", "回归理性", "不理不睬", "妥协")):
        new_title = "吵完以后还肯回来把话说完的人，心里真的有这段关系"
        new_angle = (
            "从一场争执停下来以后，屋里那股别扭还在不在写起，"
            "写一个人有没有回来找你、把情绪接住、把误会说开；"
            "重点放在修复是怎么发生的，以及这份修复怎样慢慢把关系接回去。"
        )
    else:
        new_title = "总在最想被接住时先说“没事”的人，后来会慢慢关掉求助"
        new_angle = (
            "从一个人为什么会在最需要被接住的时候先把话咽回去切入，"
            "写她在关系里怎样一次次把求助、示弱和真实反应往后收；"
            "重点放在谁误解了她、谁没有接住她，以及这份后撤后来怎样慢慢改写关系。"
        )
    return {"title": new_title, "angle": new_angle}

def _should_rewrite_everyday_warmth_return_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_everyday_warmth_return_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        title_hard_anchor_hits = sum(
            1 for token in _RESPONSIBILITY_SHELTER_TITLE_HARD_ANCHOR_TOKENS if token in title
        )
        responsibility_anchor_hits = sum(
            1 for token in ("没事", "有我", "责任", "安稳", "家", "账单", "撑住", "硬撑")
            if token in combined
        )
        responsibility_drift_hits = sum(
            1 for token in ("女性", "女性成长", "把自己往后放", "自己往后放") if token in combined
        )
        if any(token in title for token in _ABSTRACT_RESPONSIBILITY_SHELTER_TITLE_TOKENS):
            return True
        if _looks_like_explanatory_responsibility_shelter_title(title):
            return True
        if any(token in combined for token in _RESPONSIBILITY_SHELTER_NEGATIVE_TOPIC_TOKENS):
            return True
        return title_hard_anchor_hits == 0 or responsibility_anchor_hits < 2 or responsibility_drift_hits > 0
    if (
        any(token in combined for token in _ABSTRACT_EVERYDAY_WARMTH_PRESSURE_TOKENS)
        or any(token in combined for token in _ABSTRACT_EVERYDAY_WARMTH_RELATIONSHIP_TOKENS)
        or any(token in combined for token in _ABSTRACT_EVERYDAY_WARMTH_GROWTH_TOKENS)
    ):
        return True
    corpus = " ".join(
        part
        for part in (
            str(payload.get("article_title") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("structure_notes") or ""),
            str(payload.get("body_markdown") or ""),
        )
        if part
    )
    simple_happiness_focus = any(
        token in corpus
        for token in ("大富大贵", "简单快乐", "知己二三", "家人安康", "一家温暖", "高朋满座", "香车美宅")
    )
    if simple_happiness_focus and not any(
        token in combined for token in ("大富大贵", "简单快乐", "知己", "家人", "平安", "温暖", "烟火", "幸福")
    ):
        return True
    return not any(token in combined for token in _EVERYDAY_WARMTH_TOPIC_ANCHOR_TOKENS)


def _rewrite_everyday_warmth_return_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()

    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        if _uses_local_responsibility_endurance_variant(payload):
            new_title = _resolve_local_responsibility_endurance_topic_title(payload)
            if _uses_local_responsibility_midlife_variant(payload):
                new_angle = (
                    "从电话那头是父母、孩子和账单切入，"
                    "写中年人为什么总把“我没事”说得很轻；"
                    "也写那些请假、转身都要多想一步的日子，后来怎样慢慢换来一家人的安稳。"
                )
            else:
                new_angle = (
                    "从成年人总把那句“我没事”顶在前面切入，"
                    "写那些不肯说出口的辛苦，怎样慢慢换来父母的安心、孩子的底气和一家人的安稳；"
                    "也写那个总在为家里扛事的人，最后为什么同样值得被温柔接住。"
                )
            return {"title": new_title, "angle": new_angle}
        if any(token in corpus for token in ("账单", "缴费", "复查", "请假", "电话", "喉咙发紧")):
            new_title = "肩上有责任的人，心里也要留一盏灯"
        else:
            new_title = "把家里日子托稳的人，也该被好好心疼"
        new_angle = (
            "从成年人为什么会先把家里的事理顺切入，"
            "写责任怎样让人多想一步、把日子安排稳；"
            "也写那些认真托住日子的时刻，后来为什么会在父母、孩子、伴侣和家里的安稳里慢慢显出意义。"
        )
        return {"title": new_title, "angle": new_angle}

    if any(token in corpus for token in ("大富大贵", "家人安康", "知己二三", "四季平安", "简单快乐", "一家温暖")):
        new_title = "日子过到后来，有家人有知己就很踏实"
    elif any(token in corpus for token in ("高朋满座", "知己二三", "真朋友")):
        new_title = "见过热闹以后才懂，人生最难得的不过知己二三"
    elif any(token in corpus for token in ("香车美宅", "有家可回", "有人可爱", "热腾腾的饭")):
        new_title = "房子和排场都会过时，真正让人踏实的其实是一个家"
    elif any(token in corpus for token in ("宏大叙事", "微小", "细碎", "平淡的日常")):
        new_title = "很多“大事”最后都会祛魅，留下你的反而是这些小事"
    elif any(token in corpus for token in ("最重要的事", "做大事", "大事")):
        new_title = "原来最重要的，常常是那些不起眼的小事"
    elif any(token in corpus for token in ("人间烟火", "陪在爱的人身边")):
        new_title = "热闹散去以后，留下来的常常是饭桌和惦记"
    else:
        new_title = "原来最重要的，常常是那些不起眼的小事"

    if any(token in corpus for token in ("大富大贵", "家人安康", "知己二三", "四季平安", "简单快乐", "一家温暖", "香车美宅", "高朋满座")):
        new_angle = "人会一路追着更多拥有往前走，直到某个普通晚上被一顿热饭、一通惦记和一句到哪了轻轻接住，才重新看见家人平安、知己仍在的分量。"
    else:
        new_angle = "一路往前赶了很久以后，人会在陪人吃饭、回家说话、有人惦记和有人可回去的日常里，重新摸到生活的分量。"
    return {"title": new_title, "angle": new_angle}


def _has_local_trust_boundary_focus(payload: Mapping[str, object] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    candidate = dict(payload)
    candidate.setdefault("source_type", "tracked_article")
    return _has_trust_boundary_focus(candidate)


_TRUST_BOUNDARY_TOPIC_ANCHOR_TOKENS = ("信任", "坦诚", "隐瞒", "谎言", "辜负", "心安", "说到做到", "赤诚")
_TRUST_BOUNDARY_TOPIC_DRIFT_TOKENS = (
    "点赞",
    "评论",
    "读懂",
    "追问",
    "回消息",
    "没时间",
    "放下过去",
    "执念",
    "释怀",
    "争吵善后",
)


def _should_rewrite_trust_boundary_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_local_trust_boundary_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return True
    combined = f"{title} {angle}"
    if any(token in combined for token in _TRUST_BOUNDARY_TOPIC_DRIFT_TOKENS):
        return True
    return not any(token in combined for token in _TRUST_BOUNDARY_TOPIC_ANCHOR_TOKENS)


def _rewrite_trust_boundary_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    body_markdown = str(payload.get("body_markdown") or payload.get("reference_article_body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or payload.get("reference_article_structure_notes") or "")
    summary = str(payload.get("summary") or payload.get("reference_article_summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)
    if any(token in corpus for token in ("出轨", "背叛", "掉在坑里的钱")):
        new_title = "那句没说清的话，后来要认真补回来"
    elif any(token in corpus for token in ("不查手机", "不追问行踪", "给你自由")):
        new_title = "愿意放心信你的人，别让他在细节里发慌"
    else:
        new_title = "把话说清楚，是关系里最踏实的温柔"
    new_angle = (
        "从一句谎言、一次隐瞒让信任裂开那一下切入，"
        "写信任背后那份交出去的心安；"
        "也写一段关系想走得长久，怎样靠坦诚、交代和说到做到把这份赤诚守住。"
    )
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_response_priority_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_response_priority_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if any(token in combined for token in _ABSTRACT_RESPONSE_PRIORITY_AFTERCARE_TOKENS):
        return True
    if any(token in combined for token in _RESPONSE_PRIORITY_PRESSURE_SINK_TOKENS):
        return True
    anchor_hits = sum(1 for token in _RESPONSE_PRIORITY_TOPIC_ANCHOR_TOKENS if token in combined)
    return anchor_hits < 2


def _rewrite_response_priority_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if _uses_local_response_priority_followup_variant(payload) or any(
        token in corpus for token in ("评论", "追问", "言外之意", "我没事", "有点累", "注意力分给你")
    ):
        new_title = "你轻轻带过的话，真正在意的人会再问一句"
        new_angle = (
            "从点赞、评论和一句“我没事”背后的分量差别切入，"
            "写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。"
        )
    elif any(token in corpus for token in ("红灯30秒", "红灯", "蓝牙")):
        new_title = "愿意把时间分给你的人，心里早就给你留了位置"
        new_angle = (
            "从“没时间”这句话为什么常常说的不是日程，而是顺序切入，"
            "写时间分配、回应动作和投入意愿怎样一点点显出一个人的真实在乎程度；"
            "也写一个人该凭什么认清自己有没有被放在前面。"
        )
    elif any(token in corpus for token in ("24小时在线", "在乎的人", "永远都有时间")):
        new_title = "一个人把时间给了谁，往往比嘴上说了什么更真实"
        new_angle = (
            "从“没时间”这句话为什么常常说的不是日程，而是顺序切入，"
            "写时间分配、回应动作和投入意愿怎样一点点显出一个人的真实在乎程度；"
            "也写一个人该凭什么认清自己有没有被放在前面。"
        )
    else:
        new_title = "总说没时间的人，很多时候只是没把你排在前面"
        new_angle = (
            "从“没时间”这句话为什么常常说的不是日程，而是顺序切入，"
            "写时间分配、回应动作和投入意愿怎样一点点显出一个人的真实在乎程度；"
            "也写一个人该凭什么认清自己有没有被放在前面。"
        )
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_supportive_appreciation_topic(
    payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> bool:
    if not _has_supportive_appreciation_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    return not any(token in combined for token in _SUPPORTIVE_APPRECIATION_TOPIC_ANCHOR_TOKENS)


def _rewrite_supportive_appreciation_topic(
    payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> dict[str, str]:
    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if _has_local_supportive_misread_profile(payload):
        new_title = "别把一个人的体谅，当成他天生就该让着你"
        new_angle = (
            "从太好说话的人为什么总被误会成好欺负切入，"
            "写包容和和好从来不是没底线；"
            "也写一段关系真正该学会的，是珍惜这份体谅，而不是反复透支它。"
        )
    elif _has_local_supportive_discernment_profile(payload):
        new_title = "心软的人，往往看得很清，也把情分看得很重"
        new_angle = (
            "从心软的人其实什么都懂写起，"
            "写她为什么看得清，却还是愿意把锋芒先收回去；"
            "也写真正稀缺的，是这份拎得清以后仍愿意体谅人的分量。"
        )
    elif _has_local_supportive_apology_profile(payload):
        new_title = "那个受了委屈还把语气放轻的人，更该被珍惜"
        new_angle = (
            "从一个人明明已经有点难受，却还是先把语气放轻写起，"
            "写她为什么愿意在道歉落下来以后再给一次余地；"
            "也写真正难得的，不是她容易原谅，而是有人懂得把这份温柔认真接住。"
        )
    elif any(token in corpus for token in ("一生难遇", "牵紧他的手", "这样的人")):
        new_title = "总把别人感受放在前面的人，其实最该被人好好珍惜"
        new_angle = (
            "从一个人总会先把场面放软、先顾别人感受写起，"
            "写这份柔软为什么常被误读成没脾气；"
            "也写真正难得的，是有人看懂这份温柔与包容、接住它，并认真珍惜和回应。"
        )
    elif any(token in corpus for token in ("温柔", "不糊涂", "包容")):
        new_title = "真正难得的，从来不是嘴上会说，而是心里有分寸还舍得体谅你的人"
        new_angle = (
            "从一个人总会先把场面放软、先顾别人感受写起，"
            "写这份柔软为什么常被误读成没脾气；"
            "也写真正难得的，是有人看懂这份温柔与包容、接住它，并认真珍惜和回应。"
        )
    else:
        new_title = "一个总会先把场面放软的人，其实比你想的更值得珍惜"
        new_angle = (
            "从一个人总会先把场面放软、先顾别人感受写起，"
            "写这份柔软为什么常被误读成没脾气；"
            "也写真正难得的，是有人看懂这份温柔与包容、接住它，并认真珍惜和回应。"
        )
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_self_worth_rebuild_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_self_worth_rebuild_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if any(token in combined for token in _ABSTRACT_SELF_WORTH_REBUILD_COLLAPSE_TOKENS):
        return True
    return not any(token in combined for token in _SELF_WORTH_REBUILD_TOPIC_ANCHOR_TOKENS)


def _rewrite_self_worth_rebuild_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    analysis_theme = str(payload.get("analysis_theme") or "")
    analysis_emotional_exit = str(payload.get("analysis_emotional_exit") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary, analysis_theme, analysis_emotional_exit) if part)

    luxury_profile = any(
        token in corpus
        for token in ("打折品", "奢侈品", "贱卖", "廉价", "把自己养贵", "身价", "配得上", "门槛", "标准收紧")
    )
    daily_yield_profile = any(token in corpus for token in ("都可以", "算了", "先说了句行", "先把自己往后挪半步", "往后让"))

    if luxury_profile:
        new_title = "把自己看重一点，关系里的分寸才会回来"
    elif daily_yield_profile:
        new_title = "别总把那句“都可以”说得太顺口"
    elif any(token in corpus for token in ("你爱自己的程度", "人必自爱", "当你开始爱自己")):
        new_title = "你先把自己看重，关系才会慢慢认真对你"
    else:
        new_title = "别把自己的位置，一次次让到最后"

    if luxury_profile:
        new_angle = (
            "从一个人为什么总把门槛放低、把标准放松切入，"
            "写很多轻慢并不是突然发生的，常常是你先把自己放轻以后，关系也顺着这个位置往下走；"
            "也写人怎样把精力收回来、把标准收回来，让边界、体面和分寸一点点回到自己手里。"
        )
    else:
        new_angle = (
            "从一个人明明已经不舒服，却还是习惯说“都可以”那一下切入，"
            "写她为什么会在一次次退让里把自己的位置放轻；"
            "也写她后来怎样把位置一点点放回来，把边界和体面重新找稳。"
        )
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_inner_settlement_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_inner_settlement_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if any(token in combined for token in _ABSTRACT_INNER_SETTLEMENT_RELATIONSHIP_TOKENS):
        return True
    if any(token in combined for token in _ABSTRACT_INNER_SETTLEMENT_PRESSURE_TOKENS):
        return True
    if any(token in combined for token in _ABSTRACT_INNER_SETTLEMENT_HAPPINESS_TOKENS) and not any(
        token in combined for token in _INNER_SETTLEMENT_TOPIC_ANCHOR_TOKENS
    ):
        return True
    source_corpus = " ".join(
        part
        for part in (
            str(payload.get("article_title") or "").strip(),
            str(payload.get("summary") or "").strip(),
            str(payload.get("structure_notes") or "").strip(),
            str(payload.get("body_markdown") or "").strip(),
        )
        if part
    )
    source_has_stage_restart = any(token in source_corpus for token in _INNER_SETTLEMENT_STAGE_RESTART_TOKENS)
    if source_has_stage_restart:
        stage_restart_anchor_hits = sum(1 for token in _INNER_SETTLEMENT_STAGE_RESTART_TOKENS if token in combined)
        if stage_restart_anchor_hits < 2:
            return True
    title_has_positive_signal = any(token in title for token in _INNER_SETTLEMENT_TOPIC_ANCHOR_TOKENS) or any(
        token in title for token in _INNER_SETTLEMENT_POSITIVE_TOKENS
    )
    angle_has_positive_signal = any(token in angle for token in _INNER_SETTLEMENT_TOPIC_ANCHOR_TOKENS) or any(
        token in angle for token in _INNER_SETTLEMENT_POSITIVE_TOKENS
    )
    title_has_return_anchor = any(token in title for token in _INNER_SETTLEMENT_RETURN_ANCHOR_TOKENS)
    angle_has_return_anchor = any(token in angle for token in _INNER_SETTLEMENT_RETURN_ANCHOR_TOKENS)
    if any(token in title for token in _INNER_SETTLEMENT_TITLE_WAITING_SINK_TOKENS) and not title_has_return_anchor:
        return True
    if any(token in angle for token in _INNER_SETTLEMENT_ANGLE_WAITING_SINK_TOKENS) and not angle_has_return_anchor:
        return True
    if any(token in title for token in _INNER_SETTLEMENT_DIAGNOSTIC_TOKENS) and not title_has_positive_signal:
        return True
    if any(token in angle for token in _INNER_SETTLEMENT_DIAGNOSTIC_TOKENS) and not angle_has_positive_signal:
        return True
    return False


def _is_inner_settlement_result_dependence_theme(*, title: str, markdown: str) -> bool:
    payload = {
        "source_type": "tracked_article",
        "article_title": title,
        "body_markdown": markdown,
    }
    if not _has_inner_settlement_focus(payload):
        return False
    combined = f"{title}\n{markdown}"
    return any(token in combined for token in _INNER_SETTLEMENT_TITLE_WAITING_SINK_TOKENS) or any(
        token in combined for token in _INNER_SETTLEMENT_ANGLE_WAITING_SINK_TOKENS
    )


def _rewrite_inner_settlement_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()

    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if any(token in corpus for token in _INNER_SETTLEMENT_STAGE_RESTART_TOKENS):
        new_title = "这半年没按你想的那样来，也不代表你白走了一程"
        new_angle = (
            "从人为什么总会在阶段节点把没完成、没拥有和没赶上一起算成失败切入，"
            "写遗憾怎样被安放、温暖怎样把人托住，"
            "以及人怎样重新接纳眼前这个阶段的自己，带着期待继续往前。"
        )
        return {"title": new_title, "angle": new_angle}
    if any(token in corpus for token in ("此心安处", "吾乡", "心有归处", "心无挂碍")):
        new_title = "人这一生真正想要的，不过是一颗终于有归处的心"
    elif any(token in corpus for token in ("一餐一饮", "一呼一吸", "安顿灵魂")):
        new_title = "当你把心放回一餐一饮里，日子才会慢慢有了轻重"
    elif any(token in corpus for token in ("心若不安", "心若不定", "把心放平", "把事看淡", "与内心和解")):
        new_title = "很多事会慢慢顺起来，是从那颗心终于肯安顿下来开始的"
    else:
        new_title = "人到最后最想守住的，不过是一颗能安安稳稳住回日子的心"

    new_angle = (
        "从人为什么总想先把一切想稳、想透、想明白切入，"
        "写真正需要被安顿的常常不是事情本身，而是那颗一直没有放平的心；"
        "也写人怎样慢慢回到当下、回到一顿饭和一口气，让生活重新有了轻重和归处。"
    )
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_self_reliance_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_self_reliance_inward_support_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if any(token in combined for token in _SELF_RELIANCE_RELATIONSHIP_SINK_TOKENS):
        return True
    has_anchor = any(token in combined for token in _SELF_RELIANCE_THEME_ANCHOR_TOKENS)
    return not has_anchor


def _rewrite_self_reliance_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if any(token in corpus for token in ("向内求", "默默向内求", "冷静、沉淀和成长")):
        new_title = _pick_local_self_reliance_title(payload, "inward")
    elif any(token in corpus for token in ("外求", "求而不得", "靠不到", "靠不住")):
        new_title = _pick_local_self_reliance_title(payload, "external")
    else:
        new_title = _pick_local_self_reliance_title(payload, "generic")

    if any(token in corpus for token in ("倾诉", "朋友也", "愁眉不展", "焦头烂额", "自顾不暇")):
        new_angle = (
            "从想找人说说话，却发现身边人也在各自稳住自己的处境切入，"
            "写成年人怎样把求而不得的委屈放回可处理的位置；"
            "也写一个人先稳住判断和行动，在合适的时候求助、分担，慢慢把生活接回来。"
        )
    elif any(token in corpus for token in ("外求", "求而不得", "靠不到", "靠不住")):
        new_angle = (
            "从外面的回应一时赶不上、事情却还要继续往前走切入，"
            "写一个人怎样不把全部希望压在别人身上；"
            "也写先稳住自己以后，求助、选择和行动怎样重新变得清楚。"
        )
    else:
        new_angle = (
            "从一个人把散掉的力气慢慢收回自己手里切入，"
            "写低谷里的清醒怎样从恢复判断和行动开始；"
            "也写人怎样一边自救，一边在合适的时候接住外面的善意。"
        )
    return {"title": new_title, "angle": new_angle}


def _should_rewrite_resilience_reconstruction_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    if not _has_resilience_reconstruction_focus(payload):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    return any(token in combined for token in _ABSTRACT_RESILIENCE_SELF_HELP_TOKENS)


def _has_local_resilience_pool_profile(
    payload: Mapping[str, object] | None,
    *,
    extra_text: str = "",
) -> bool:
    candidate = payload or {}
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(candidate),
            _extract_local_fallback_corpus(candidate),
            extra_text,
        )
        if part
    )
    pool_hits = sum(1 for token in ("泳池", "划水", "泳道", "50米", "多划11下", "11下") if token in corpus)
    rebuild_hits = sum(
        1
        for token in ("训练", "复健", "手术台", "右臂", "右腿", "肩伤", "背痛", "残奥", "领奖台")
        if token in corpus
    )
    return pool_hits >= 1 and rebuild_hits >= 1


def _payload_has_scene_first_relation_progression_cues(payload: Mapping[str, object]) -> bool:
    extra_fields: list[str] = [
        str(payload.get("cover_copy") or "").strip(),
        str(payload.get("social_teaser") or "").strip(),
        str(payload.get("recommended_title") or "").strip(),
    ]
    for key in ("social_teaser_options", "title_options"):
        value = payload.get(key)
        if isinstance(value, list):
            extra_fields.extend(str(item).strip() for item in value if str(item).strip())
    corpus = re.sub(r"\s+", "", " ".join([_extract_local_fallback_corpus(payload), *extra_fields]))
    if not corpus:
        return False
    scene_hits = sum(
        1
        for token in (
            "会议",
            "早会",
            "开会",
            "散会",
            "方案",
            "翻页笔",
            "投影",
            "工位",
            "出站口",
            "摆渡车",
            "地铁",
            "站牌",
            "上车",
            "车门",
            "餐桌",
            "药盒",
            "检查单",
            "水壶",
            "孩子睡了",
            "夜里进门",
            "家里的心事",
        )
        if token in corpus
    )
    speech_hits = sum(
        1
        for token in (
            "没说出口",
            "没问出口",
            "没说清",
            "话停在嘴边",
            "重要的话",
            "该说的话",
            "该问的话",
            "真话",
            "肯开口",
            "说出来",
        )
        if token in corpus
    )
    relation_hits = sum(
        1
        for token in (
            "关系",
            "距离",
            "沉默",
            "误会",
            "疏远",
            "拖远",
            "往后退",
            "退了半步",
            "说开",
        )
        if token in corpus
    )
    trust_detour_hits = sum(1 for token in ("信任", "谎言", "隐瞒", "坦诚", "赤诚", "辜负") if token in corpus)
    self_worth_detour_hits = sum(
        1
        for token in (
            "把自己看重",
            "把自己养贵",
            "都可以",
            "边界",
            "身价",
            "分寸",
            "标准",
            "将就",
            "立规矩",
            "树边界",
        )
        if token in corpus
    )
    if trust_detour_hits >= 2 and scene_hits < 2:
        return False
    if self_worth_detour_hits >= 2 and scene_hits < 2:
        return False
    return (scene_hits >= 1 and speech_hits >= 1 and relation_hits >= 1) or (speech_hits >= 2 and relation_hits >= 2)


def _payload_looks_like_scene_first_progression(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            str(payload.get("body_markdown") or "").strip(),
            str(payload.get("structure_notes") or "").strip(),
            str(payload.get("summary") or "").strip(),
            str(payload.get("article_title") or "").strip(),
        )
        if part
    )
    return any(
        (
            _has_local_scene_first_office_markers(corpus),
            _has_local_scene_first_transit_markers(corpus),
            _has_local_scene_first_household_markers(corpus),
            _payload_has_scene_first_relation_progression_cues(payload),
        )
    )


def _should_rewrite_scene_first_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
    inferred_scene_first = _payload_looks_like_scene_first_progression(payload)
    if (
        str(payload.get("analysis_structure_mode") or "").strip() != "scene_first_progression"
        and not inferred_scene_first
    ):
        return False
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    if not title and not angle:
        return False
    combined = f"{title} {angle}"
    if any(token in combined for token in _ABSTRACT_SCENE_FIRST_TITLE_TOKENS) or any(
        token in combined for token in _ABSTRACT_SCENE_FIRST_ANGLE_TOKENS
    ):
        return True
    if inferred_scene_first and (
        _looks_like_packaging_instruction_leakage(combined)
        or bool(_starts_with_generic_packaging_openers(title))
        or bool(extract_generic_reflective_openers(title))
        or not any(
            (
                _has_local_scene_first_office_markers(combined),
                _has_local_scene_first_transit_markers(combined),
                _has_local_scene_first_household_markers(combined),
            )
        )
    ):
        return True
    return False


def _rewrite_scene_first_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if any(token in corpus for token in ("会议室", "投影幕布", "散会以后", "老方案", "资料")):
        new_title = "散会后才开口，位置就会慢慢往后退"
        new_angle = (
            "从会前先压住改过的那页、会上顺着顺序点头、会后还在心里补那句提醒这一整段现场切入，"
            "写一个人怎样一次次把该争取的位置先让给场面。"
        )
        return {"title": new_title, "angle": new_angle}

    if any(token in corpus for token in ("地铁口", "围巾", "接驳车", "白雾")):
        new_title = "没问出口的那句话，最容易把关系拖远"
        new_angle = (
            "从等车时看出不对劲却还是先没问、上车后话题跟着白气一起散掉这一段连续现场切入，"
            "写关系怎样在一次次体谅里慢慢把靠近让掉。"
        )
        return {"title": new_title, "angle": new_angle}

    if any(token in corpus for token in ("药盒", "检查单", "水壶", "孩子睡了")):
        new_title = "家里的心事，最怕总被顺到明天"
        new_angle = (
            "从夜里回家看见检查单、想问的话又往回收、第二天照常出门却还悬着这一段连续现场切入，"
            "写家里的沉默怎样一点点把心事压重。"
        )
        return {"title": new_title, "angle": new_angle}

    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()
    return {"title": title, "angle": angle}


def _rewrite_resilience_reconstruction_topic(payload: Mapping[str, object], ai_result: Mapping[str, object]) -> dict[str, str]:
    title = str(ai_result.get("title") or "").strip()
    angle = str(ai_result.get("angle") or "").strip()

    body_markdown = str(payload.get("body_markdown") or "")
    structure_notes = str(payload.get("structure_notes") or "")
    summary = str(payload.get("summary") or "")
    corpus = " ".join(part for part in (body_markdown, structure_notes, summary) if part)

    if _has_local_resilience_pool_profile(payload, extra_text=corpus):
        new_title = "那些总要多划11下的人，最后是怎样把自己从命运里撑出来的"
    elif any(token in corpus for token in ("不被定义", "残缺", "破碎中重建")):
        new_title = "命运想用残缺定义你时，真正托住人的往往是那股不肯松掉的韧性"
    else:
        new_title = "被命运反复重击的人，后来都是怎样一点点把自己重新站起来的"

    if any(token in corpus for token in ("手术台", "车祸", "剧痛", "刺穿")) and any(
        token in corpus for token in ("泳池", "训练", "多划11下", "划水")
    ):
        new_angle = "从命运怎样把一个人早早推上手术台切入，写她又怎样在泳池里一次次多划那11下，把疼痛、训练和不肯认输的劲，慢慢熬成重新站起来的人生。"
    else:
        new_angle = "从人被命运迎头重击以后，为什么还能在训练、疼痛和反复重来里一点点重建自己切入，写真正的韧性不是嘴上给自己打气，而是拒绝被残缺、低谷和外界定义收走人生。"
    return {"title": new_title, "angle": new_angle}


def _resolve_local_responsibility_topic_angle(payload: Mapping[str, object]) -> str:
    if _uses_local_responsibility_endurance_variant(payload):
        return (
            "从成年人总把那句“我没事”顶在前面切入，"
            "写那些不肯说出口的辛苦，怎样慢慢换来父母的安心、孩子的底气和一家人的安稳；"
            "也写那个总在为家里扛事的人，最后为什么同样值得被温柔接住。"
        )
    if _uses_local_responsibility_midlife_variant(payload):
        return (
            "从电话那头是父母、孩子和账单切入，"
            "写中年人为什么总把“我没事”说得很轻；"
            "也写那些请假、转身都要多想一步的日子，后来怎样慢慢换来一家人的安稳。"
        )
    return (
        "从家里一有临时情况，人为什么总会先把顺序理清写起，"
        "写那些翻日历、改安排、往前顶一步的时刻，怎样一点点托住父母、孩子和家里的安稳。"
    )


def _sanitize_responsibility_shelter_topic_result(
    payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> dict[str, str]:
    rewritten = {
        "title": str(ai_result.get("title") or "").strip(),
        "angle": str(ai_result.get("angle") or "").strip(),
    }
    if (
        str(payload.get("analysis_structure_mode") or "").strip() == "scene_first_progression"
        or _payload_looks_like_scene_first_progression(payload)
        or rewritten["title"] == "家里的心事，最怕总被顺到明天"
        or any(token in f"{rewritten['title']} {rewritten['angle']}" for token in ("夜里回家看见检查单", "连续现场"))
    ):
        return rewritten
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    responsibility_hits = sum(
        1
        for token in ("电话", "日历", "父母", "孩子", "账单", "请假", "复查", "医院", "家里", "中年", "没事", "有我")
        if token in corpus
    )
    if responsibility_hits < 3:
        return rewritten

    local_title = (
        _resolve_local_responsibility_endurance_topic_title(payload)
        if _uses_local_responsibility_endurance_variant(payload)
        else _resolve_local_responsibility_scene_title(payload)
    )
    title = _strip_responsibility_title_label(rewritten["title"])
    if (
        not title
        or _looks_like_explanatory_responsibility_shelter_title(title)
        or _should_prefer_short_responsibility_scene_title(title, local_title)
        or any(token in title for token in _ABSTRACT_RESPONSIBILITY_SHELTER_TITLE_TOKENS)
        or any(token in title for token in ("往后排", "更稳", "逞强", "难受", "为什么", "后来才明白", "不是逞强"))
    ):
        rewritten["title"] = local_title

    angle = _strip_packaging_editorial_meta_clauses(_sanitize_responsibility_shelter_output_text(rewritten["angle"]))
    if (
        not angle
        or _looks_like_packaging_instruction_leakage(angle)
        or _looks_like_packaging_meta_text(angle)
        or angle.startswith(("这篇想", "这篇稿子", "文章想", "稿子想", "从家里一有临时情况"))
    ):
        rewritten["angle"] = _resolve_local_responsibility_topic_angle(payload)
    else:
        rewritten["angle"] = angle
    return rewritten


def _apply_tracked_article_topic_rewrites(
    payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> dict[str, str]:
    rewritten: dict[str, str] = {
        "title": str(ai_result.get("title") or "").strip(),
        "angle": str(ai_result.get("angle") or "").strip(),
    }
    if _should_rewrite_pressure_topic_title(payload, rewritten):
        rewritten = {
            "title": _rewrite_pressure_topic_title(payload, rewritten),
            "angle": str(rewritten.get("angle") or "").strip(),
        }
    if _should_rewrite_pressure_topic_angle(payload, rewritten):
        rewritten = _rewrite_pressure_topic_angle(payload, rewritten)
    if _should_rewrite_everyday_warmth_return_topic(payload, rewritten):
        rewritten = _rewrite_everyday_warmth_return_topic(payload, rewritten)
    if _should_rewrite_trust_boundary_topic(payload, rewritten):
        rewritten = _rewrite_trust_boundary_topic(payload, rewritten)
    if _should_rewrite_response_priority_topic(payload, rewritten):
        rewritten = _rewrite_response_priority_topic(payload, rewritten)
    if _should_rewrite_supportive_appreciation_topic(payload, rewritten):
        rewritten = _rewrite_supportive_appreciation_topic(payload, rewritten)
    if _should_rewrite_self_worth_rebuild_topic(payload, rewritten):
        rewritten = _rewrite_self_worth_rebuild_topic(payload, rewritten)
    if _should_rewrite_inner_settlement_topic(payload, rewritten):
        rewritten = _rewrite_inner_settlement_topic(payload, rewritten)
    if _should_rewrite_self_reliance_topic(payload, rewritten):
        rewritten = _rewrite_self_reliance_topic(payload, rewritten)
    if _should_rewrite_emotional_release_topic(payload, rewritten):
        rewritten = _rewrite_emotional_release_topic(payload, rewritten)
    if _should_rewrite_relationship_aftercare_withdrawn_topic(payload, rewritten):
        rewritten = _rewrite_relationship_aftercare_withdrawn_topic(payload, rewritten)
    if _should_rewrite_resilience_reconstruction_topic(payload, rewritten):
        rewritten = _rewrite_resilience_reconstruction_topic(payload, rewritten)
    if _should_rewrite_scene_first_topic(payload, rewritten):
        rewritten = _rewrite_scene_first_topic(payload, rewritten)
    rewritten = _sanitize_responsibility_shelter_topic_result(payload, rewritten)
    return {
        "title": str(rewritten.get("title") or "").strip(),
        "angle": str(rewritten.get("angle") or "").strip(),
    }


def _build_local_tracked_article_topic_fallback(payload: Mapping[str, object]) -> dict[str, str]:
    mode = _resolve_local_fallback_mode(payload)
    local_mode_builders: dict[str, Callable[[Mapping[str, object], Mapping[str, object]], dict[str, str]]] = {
        "everyday_warmth_return": _rewrite_everyday_warmth_return_topic,
        "responsibility_shelter": _rewrite_everyday_warmth_return_topic,
        "trust_boundary": _rewrite_trust_boundary_topic,
        "response_priority": _rewrite_response_priority_topic,
        "supportive_appreciation": _rewrite_supportive_appreciation_topic,
        "self_worth_rebuild": _rewrite_self_worth_rebuild_topic,
        "emotional_engine_direct": _rewrite_emotional_release_topic,
        "relationship_aftercare": _rewrite_relationship_aftercare_withdrawn_topic,
        "inner_settlement": _rewrite_inner_settlement_topic,
        "self_reliance_inward_support": _rewrite_self_reliance_topic,
        "resilience_reconstruction": _rewrite_resilience_reconstruction_topic,
        "scene_first_progression": _rewrite_scene_first_topic,
        "pressure_interface_direct": _rewrite_pressure_interface_topic,
    }
    builder = local_mode_builders.get(mode)
    if builder is not None:
        rewritten = builder(payload, {"title": "", "angle": ""})
        if rewritten.get("title") and rewritten.get("angle"):
            return {
                "title": str(rewritten["title"]).strip(),
                "angle": str(rewritten["angle"]).strip(),
            }

    article_title = str(payload.get("article_title") or "").strip()
    analysis_theme = str(payload.get("analysis_theme") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    structure_notes = str(payload.get("structure_notes") or "").strip()
    anchor = analysis_theme or summary or structure_notes or article_title or "文章里的真实处境"
    if len(anchor) > 48:
        anchor = anchor[:47].rstrip("，,；;。.!?？、 ") + "…"

    fallback = {
        "title": "很多答案，都是把日子过到眼前以后，才慢慢看清的",
        "angle": (
            f"围绕《{article_title}》对应的现实处境切入，重建新的具体入口，"
            f"把{anchor}说得更贴近真人表达。"
            if article_title
            else f"围绕参考文章对应的现实处境切入，重建新的具体入口，把{anchor}说得更贴近真人表达。"
        ),
    }
    rewritten = _apply_tracked_article_topic_rewrites(payload, fallback)
    if rewritten["title"] and rewritten["angle"]:
        return rewritten
    return {
        "title": rewritten["title"] or fallback["title"],
        "angle": rewritten["angle"] or fallback["angle"],
    }


def _allow_local_creative_fallbacks() -> bool:
    return bool(settings.openai_allow_local_creative_fallbacks)


def _creative_quality_retry_max_attempts() -> int:
    return max(0, int(getattr(settings, "openai_creative_quality_retry_max_attempts", 0) or 0))


def _allow_extra_quality_candidate_generation() -> bool:
    return _creative_quality_retry_max_attempts() > 0


def _image_generation_max_attempts() -> int:
    return max(1, int(getattr(settings, "openai_image_generation_max_attempts", 1) or 1))


def _build_creative_upstream_failure_detail(stage_label: str, exc: Exception) -> str:
    normalized_stage_label = stage_label.strip() or "内容生成"
    return (
        f"{normalized_stage_label}失败：当前文本 AI 服务暂时不可用，请稍后重试。"
        " 当前已关闭本地兜底，避免写成退化稿。"
        f" 原始返回：{exc}"
    )


def _raise_creative_upstream_failure(stage_label: str, exc: Exception) -> None:
    raise HTTPException(
        status_code=_CREATIVE_UPSTREAM_FAILURE_STATUS_CODE,
        detail=_build_creative_upstream_failure_detail(stage_label, exc),
    ) from exc


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
        updated_analysis_theme = str(ai_result.get("analysis_theme") or "").strip() or article.analysis_theme
        updated_analysis_core_conflict = (
            str(ai_result.get("analysis_core_conflict") or "").strip() or article.analysis_core_conflict
        )
        updated_analysis_emotional_exit = (
            str(ai_result.get("analysis_emotional_exit") or "").strip() or article.analysis_emotional_exit
        )
        updated_analysis_hook_trigger = (
            str(ai_result.get("analysis_hook_trigger") or "").strip() or article.analysis_hook_trigger
        )
        updated_analysis_progression_drive = (
            str(ai_result.get("analysis_progression_drive") or "").strip() or article.analysis_progression_drive
        )
        updated_analysis_share_reason = (
            str(ai_result.get("analysis_share_reason") or "").strip() or article.analysis_share_reason
        )
        updated_analysis_opening_pattern = (
            str(ai_result.get("analysis_opening_pattern") or "").strip() or article.analysis_opening_pattern
        )
        updated_analysis_do_not_turn_into = (
            str(ai_result.get("analysis_do_not_turn_into") or "").strip() or article.analysis_do_not_turn_into
        )
        updated_metadata = _sanitize_responsibility_shelter_tracked_article_metadata(
            {
                "summary": updated_summary,
                "structure_notes": updated_structure_notes,
                "analysis_theme": updated_analysis_theme,
                "analysis_core_conflict": updated_analysis_core_conflict,
                "analysis_emotional_exit": updated_analysis_emotional_exit,
                "analysis_structure_mode": str(ai_result.get("analysis_structure_mode") or "").strip()
                or article.analysis_structure_mode,
                "analysis_opening_pattern": updated_analysis_opening_pattern,
                "analysis_hook_trigger": updated_analysis_hook_trigger,
                "analysis_progression_drive": updated_analysis_progression_drive,
                "analysis_share_reason": updated_analysis_share_reason,
                "analysis_do_not_turn_into": updated_analysis_do_not_turn_into,
            },
            article_title=article.title,
            body_markdown=article.body_markdown,
            tags=updated_tags,
        )
        updated_summary = str(updated_metadata["summary"])
        updated_structure_notes = str(updated_metadata["structure_notes"])
        updated_analysis_theme = str(updated_metadata["analysis_theme"])
        updated_analysis_core_conflict = str(updated_metadata["analysis_core_conflict"])
        updated_analysis_emotional_exit = str(updated_metadata["analysis_emotional_exit"])
        updated_analysis_opening_pattern = str(updated_metadata["analysis_opening_pattern"])
        updated_analysis_hook_trigger = str(updated_metadata["analysis_hook_trigger"])
        updated_analysis_progression_drive = str(updated_metadata["analysis_progression_drive"])
        updated_analysis_share_reason = str(updated_metadata["analysis_share_reason"])
        updated_analysis_do_not_turn_into = str(updated_metadata["analysis_do_not_turn_into"])
        updated_tags = _normalize_tracked_article_tags(updated_metadata.get("tags"))
        updated_analysis_structure_mode = resolve_tracked_article_structure_mode(
            body_markdown=article.body_markdown,
            summary=updated_summary,
            structure_notes=updated_structure_notes,
            analysis_structure_mode_hint=str(updated_metadata.get("analysis_structure_mode") or ""),
            analysis_theme=updated_analysis_theme,
            analysis_core_conflict=updated_analysis_core_conflict,
            analysis_emotional_exit=updated_analysis_emotional_exit,
            analysis_opening_pattern=updated_analysis_opening_pattern,
            analysis_do_not_turn_into=updated_analysis_do_not_turn_into,
        )

        connection.execute(
            """
            UPDATE tracked_articles
            SET author = ?, summary = ?, structure_notes = ?, tags = ?,
                analysis_theme = ?, analysis_core_conflict = ?, analysis_emotional_exit = ?,
                analysis_structure_mode = ?, analysis_opening_pattern = ?, analysis_hook_trigger = ?,
                analysis_progression_drive = ?, analysis_share_reason = ?, analysis_do_not_turn_into = ?
            WHERE slug = ?
            """,
            (
                updated_author,
                updated_summary,
                updated_structure_notes,
                json.dumps(updated_tags, ensure_ascii=False),
                updated_analysis_theme,
                updated_analysis_core_conflict,
                updated_analysis_emotional_exit,
                updated_analysis_structure_mode,
                updated_analysis_opening_pattern,
                updated_analysis_hook_trigger,
                updated_analysis_progression_drive,
                updated_analysis_share_reason,
                updated_analysis_do_not_turn_into,
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
    article_for_analysis: TrackedArticleItem | None = None
    generator = get_ai_generator()
    with _get_connection() as connection:
        article_row = _get_tracked_article_row_by_slug(connection, article_slug)
        if not article_row:
            raise HTTPException(status_code=404, detail="Tracked article not found")
        article_for_analysis = _hydrate_tracked_article_row(article_row)

    if article_for_analysis is None:
        raise HTTPException(status_code=404, detail="Tracked article not found")
    if not _tracked_article_has_analysis(article_for_analysis) and hasattr(generator, "generate_tracked_article_metadata"):
        try:
            article_for_analysis = enrich_tracked_article_metadata(article_slug)
        except Exception:
            logger.warning(
                "Tracked article metadata enrichment failed during topic generation; falling back to stored article fields",
                extra={"article_slug": article_slug},
                exc_info=True,
            )

    with _get_connection() as connection:
        article = _get_tracked_article_row_by_slug(connection, article_slug)
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
            "source_ref_slug": article_for_analysis.slug,
            "source_name": article_for_analysis.source_name,
            "article_title": article_for_analysis.title,
            "author": article_for_analysis.author,
            "summary": article_for_analysis.summary,
            "body_markdown": article_for_analysis.body_markdown,
            "structure_notes": article_for_analysis.structure_notes,
            "analysis_theme": article_for_analysis.analysis_theme,
            "analysis_core_conflict": article_for_analysis.analysis_core_conflict,
            "analysis_emotional_exit": article_for_analysis.analysis_emotional_exit,
            "analysis_structure_mode": article_for_analysis.analysis_structure_mode,
            "analysis_opening_pattern": article_for_analysis.analysis_opening_pattern,
            "analysis_hook_trigger": article_for_analysis.analysis_hook_trigger,
            "analysis_progression_drive": article_for_analysis.analysis_progression_drive,
            "analysis_share_reason": article_for_analysis.analysis_share_reason,
            "analysis_do_not_turn_into": article_for_analysis.analysis_do_not_turn_into,
            "tags": article_for_analysis.tags,
            "tone_profile": tone_profile.model_dump(),
        }
        try:
            ai_result = _apply_tracked_article_topic_rewrites(topic_payload, generator.generate_topic(topic_payload))
        except Exception as exc:
            if not _allow_local_creative_fallbacks():
                _raise_creative_upstream_failure("选题生成", exc)
            logger.warning(
                "Tracked article topic generation failed; falling back to local topic seed",
                extra={"article_slug": article_slug},
                exc_info=True,
            )
            ai_result = _build_local_tracked_article_topic_fallback(topic_payload)
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
                ta.analysis_theme AS reference_article_analysis_theme,
                ta.analysis_core_conflict AS reference_article_analysis_core_conflict,
                ta.analysis_emotional_exit AS reference_article_analysis_emotional_exit,
                ta.analysis_structure_mode AS reference_article_analysis_structure_mode,
                ta.analysis_opening_pattern AS reference_article_analysis_opening_pattern,
                ta.analysis_hook_trigger AS reference_article_analysis_hook_trigger,
                ta.analysis_progression_drive AS reference_article_analysis_progression_drive,
                ta.analysis_share_reason AS reference_article_analysis_share_reason,
                ta.analysis_do_not_turn_into AS reference_article_analysis_do_not_turn_into,
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

    resolved_analysis_structure_mode = resolve_tracked_article_structure_mode(
        body_markdown=str(project["reference_article_body_markdown"] or ""),
        summary=str(project["reference_article_summary"] or ""),
        structure_notes=str(project["reference_article_structure_notes"] or ""),
        analysis_structure_mode_hint=str(project["reference_article_analysis_structure_mode"] or ""),
        analysis_theme=str(project["reference_article_analysis_theme"] or ""),
        analysis_core_conflict=str(project["reference_article_analysis_core_conflict"] or ""),
        analysis_emotional_exit=str(project["reference_article_analysis_emotional_exit"] or ""),
        analysis_opening_pattern=str(project["reference_article_analysis_opening_pattern"] or ""),
        analysis_do_not_turn_into=str(project["reference_article_analysis_do_not_turn_into"] or ""),
    )

    payload.update(
        {
            "reference_article_title": str(project["reference_article_title"] or ""),
            "reference_article_author": str(project["reference_article_author"] or ""),
            "reference_article_source_name": str(project["reference_article_source_name"] or "手动录入"),
            "reference_article_summary": str(project["reference_article_summary"] or ""),
            "reference_article_body_markdown": str(project["reference_article_body_markdown"] or ""),
            "reference_article_structure_notes": str(project["reference_article_structure_notes"] or ""),
            "reference_article_analysis_theme": str(project["reference_article_analysis_theme"] or ""),
            "reference_article_analysis_core_conflict": str(project["reference_article_analysis_core_conflict"] or ""),
            "reference_article_analysis_emotional_exit": str(project["reference_article_analysis_emotional_exit"] or ""),
            "reference_article_analysis_structure_mode": resolved_analysis_structure_mode,
            "reference_article_analysis_opening_pattern": str(project["reference_article_analysis_opening_pattern"] or ""),
            "reference_article_analysis_do_not_turn_into": str(project["reference_article_analysis_do_not_turn_into"] or ""),
            "reference_article_tags": tags,
        }
    )
    return payload


def _build_draft_candidate_selection_context(
    *,
    project: sqlite3.Row | None = None,
    source_type: str | None = None,
    reference_source_markdown: str = "",
    reference_article_payload: Mapping[str, object] | None = None,
    strategy_bundle_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if project is not None:
        payload.update(
            {
                "source_type": str(project["source_type"] or ""),
                "topic_title": str(project["topic_title"] or ""),
                "topic_angle": str(project["topic_angle"] or ""),
                "project_title": str(project["title"] or ""),
            }
        )
    elif source_type is not None:
        payload["source_type"] = str(source_type or "")
    if reference_article_payload:
        payload.update(dict(reference_article_payload))
    if strategy_bundle_payload:
        payload.update(dict(strategy_bundle_payload))
    if reference_source_markdown and not payload.get("reference_article_body_markdown"):
        payload["reference_article_body_markdown"] = reference_source_markdown
    return payload


def _build_local_tracked_article_fallback_payload(
    *,
    project: sqlite3.Row,
    payload: Mapping[str, object],
) -> dict[str, object]:
    fallback_payload = dict(payload)
    if str(project["source_type"]) != "tracked_article":
        return fallback_payload

    required_keys = (
        "reference_article_title",
        "reference_article_summary",
        "reference_article_structure_notes",
        "reference_article_body_markdown",
        "reference_article_tags",
    )
    if hasattr(project, "keys"):
        project_keys = set(project.keys())
    elif isinstance(project, Mapping):
        project_keys = set(project.keys())
    else:
        project_keys = set()
    if any(key not in project_keys for key in required_keys):
        return fallback_payload

    reference_payload = _build_reference_article_payload(project, hide_details=False)
    for key, value in reference_payload.items():
        if key == "source_type":
            continue
        current = fallback_payload.get(key)
        if current in (None, "", [], {}):
            fallback_payload[key] = value

    fallback_payload.setdefault("article_title", str(project["reference_article_title"] or ""))
    fallback_payload.setdefault("summary", str(project["reference_article_summary"] or ""))
    fallback_payload.setdefault("structure_notes", str(project["reference_article_structure_notes"] or ""))
    fallback_payload.setdefault("body_markdown", str(project["reference_article_body_markdown"] or ""))
    return fallback_payload


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
    payload["writing_texture_notes"] = _load_json_string_list(payload.get("writing_texture_notes"))
    payload["scene_anchor_requirements"] = _load_json_string_list(payload.get("scene_anchor_requirements"))
    payload["quotable_line_seeds"] = _load_json_string_list(payload.get("quotable_line_seeds"))
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
            problem_explanation,
            emotional_value_goal,
            theme_axis,
            anti_drift_axis,
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
            problem_explanation,
            emotional_value_goal,
            theme_axis,
            anti_drift_axis,
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
            hook_trigger,
            progression_drive,
            share_reason,
            positive_direction,
            quotable_line_goal,
            packaging_focus,
            packaging_hook,
            realism_texture_goal,
            structure_mode,
            opening_move,
            body_shift,
            ending_move,
            writing_texture_notes,
            scene_anchor_requirements,
            quotable_line_seeds,
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
            hook_trigger,
            progression_drive,
            share_reason,
            positive_direction,
            quotable_line_goal,
            packaging_focus,
            packaging_hook,
            realism_texture_goal,
            structure_mode,
            opening_move,
            body_shift,
            ending_move,
            writing_texture_notes,
            scene_anchor_requirements,
            quotable_line_seeds,
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
            hook_trigger,
            progression_drive,
            share_reason,
            positive_direction,
            quotable_line_goal,
            packaging_focus,
            packaging_hook,
            realism_texture_goal,
            structure_mode,
            opening_move,
            body_shift,
            ending_move,
            writing_texture_notes,
            scene_anchor_requirements,
            quotable_line_seeds,
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
    _ensure_creative_workflow_schema(connection)
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
                recommended_title,
                cover_prompt,
                cover_copy,
                social_teaser,
                social_teaser_options,
                cover_image_path,
                cover_image_url,
                cover_image_status,
                cover_image_error,
                cover_image_route_label,
                cover_image_route_model,
                cover_image_route_base_url,
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
                publish_title,
                publish_lead,
                intro_options,
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
    elif str(assets_row["cover_image_status"] or "pending") == "quality_blocked":
        chain_status = "stale"
        current_chain_state = "assets_quality_blocked"
        next_required_step = "generate_assets"
    elif (
        str(assets_row["cover_image_status"] or "pending") != "ready"
        or not str(assets_row["cover_image_url"] or "").strip()
    ):
        chain_status = "stale"
        current_chain_state = "cover_pending"
        next_required_step = "regenerate_cover_image"
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
                    problem_explanation,
                    emotional_value_goal,
                    theme_axis,
                    anti_drift_axis,
                    target_reader_situation,
                    core_conflict,
                    constraints,
                    feedback_entry,
                    problem_statement_markdown,
                    unknowns,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package.problem_brief.project_slug,
                    package.problem_brief.version,
                    package.problem_brief.source_mode,
                    package.problem_brief.raw_goal,
                    package.problem_brief.clarified_problem,
                    package.problem_brief.observed_phenomenon,
                    package.problem_brief.writing_goal,
                    package.problem_brief.problem_explanation,
                    package.problem_brief.emotional_value_goal,
                    package.problem_brief.theme_axis,
                    package.problem_brief.anti_drift_axis,
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
                    hook_trigger,
                    progression_drive,
                    share_reason,
                    positive_direction,
                    quotable_line_goal,
                    packaging_focus,
                    packaging_hook,
                    realism_texture_goal,
                    structure_mode,
                    opening_move,
                    body_shift,
                    ending_move,
                    writing_texture_notes,
                    scene_anchor_requirements,
                    quotable_line_seeds,
                    expression_constraints,
                    divergence_axes,
                    execution_checklist,
                    benchmark_summary,
                    strategy_markdown,
                    status,
                    created_at,
                    adopted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package.strategy_card.project_slug,
                    package.strategy_card.version,
                    package.strategy_card.problem_brief_version,
                    package.strategy_card.reader_situation,
                    package.strategy_card.point_of_view,
                    package.strategy_card.conflict_frame,
                    package.strategy_card.emotional_path,
                    package.strategy_card.hook_trigger,
                    package.strategy_card.progression_drive,
                    package.strategy_card.share_reason,
                    package.strategy_card.positive_direction,
                    package.strategy_card.quotable_line_goal,
                    package.strategy_card.packaging_focus,
                    package.strategy_card.packaging_hook,
                    package.strategy_card.realism_texture_goal,
                    package.strategy_card.structure_mode,
                    package.strategy_card.opening_move,
                    package.strategy_card.body_shift,
                    package.strategy_card.ending_move,
                    json.dumps(package.strategy_card.writing_texture_notes, ensure_ascii=False),
                    json.dumps(package.strategy_card.scene_anchor_requirements, ensure_ascii=False),
                    json.dumps(package.strategy_card.quotable_line_seeds, ensure_ascii=False),
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
        _ensure_runtime_chain_schema(connection)
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
    reference_originality_report = _build_project_reference_originality_report(project_row, draft_row)
    diagnosis_report = _hydrate_diagnosis_report_row(diagnosis_report_row) if diagnosis_report_row else None
    draft_quality_summary = (
        build_draft_quality_summary(
            draft_version=int(draft_row["version"]),
            draft_title=str(draft_row["title"]),
            draft_body_markdown=str(draft_row["body_markdown"]),
            diagnosis_report=diagnosis_report.model_dump() if diagnosis_report else None,
            reference_originality_report=reference_originality_report,
        )
        if draft_row
        else None
    )

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
        diagnosis_report=diagnosis_report,
        creative_review_report=(
            _hydrate_creative_review_report_row(creative_review_report_row)
            if creative_review_report_row
            else None
        ),
        draft_quality_summary=draft_quality_summary,
        reusable_patterns=[_hydrate_reusable_pattern_row(row) for row in reusable_pattern_rows],
        reference_originality_report=reference_originality_report,
    )


def get_project_versions(project_slug: str) -> ProjectVersions:
    _get_project_row(project_slug)
    with _get_connection() as connection:
        _ensure_runtime_chain_schema(connection)
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
                recommended_title,
                cover_prompt,
                cover_copy,
                social_teaser,
                social_teaser_options,
                cover_image_path,
                cover_image_url,
                cover_image_status,
                cover_image_error,
                cover_image_route_label,
                cover_image_route_model,
                cover_image_route_base_url,
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
                publish_title,
                publish_lead,
                intro_options,
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
                hook_trigger,
                progression_drive,
                share_reason,
                positive_direction,
                quotable_line_goal,
                packaging_focus,
                packaging_hook,
                realism_texture_goal,
                structure_mode,
                opening_move,
                body_shift,
                ending_move,
                writing_texture_notes,
                scene_anchor_requirements,
                quotable_line_seeds,
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
                    publish_title,
                    publish_lead,
                    intro_options,
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
        if str(project["source_type"]) == "tracked_article":
            ai_payload["strategy_first_outline_mode"] = True
    generator = get_ai_generator()
    ai_result = _generate_outline_with_transient_recovery(
        project=project,
        generator=generator,
        ai_payload=ai_payload,
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


def _build_local_tracked_article_outline_fallback(ai_payload: Mapping[str, object]) -> dict[str, str]:
    strategy_card = ai_payload.get("strategy_card")
    positive_direction = ""
    if isinstance(strategy_card, Mapping):
        positive_direction = str(strategy_card.get("positive_direction") or "").strip()

    if _should_use_local_responsibility_shelter_fallback(ai_payload):
        return {
            "hook": "很多中年人的一通来电，听着只是家里有事，心里却已经开始替所有人排顺序。",
            "outline_body": (
                "### 1. 从一通来电或一个日历安排写起：先落电话、家里有事这些现实接口，把人为什么会先把顺序理清写具体。\n"
                "### 2. 说清责任怎样让人多想一步：上有父母、下有孩子，工作也不能松，很多人慢慢学会先把家里安顿好，也给自己留一口气。\n"
                "### 3. 写出责任怎样回到日常：父母少一点担心，孩子多一点底气，家里的灯还亮着，让辛苦落成看得见的踏实。\n"
                f"### 4. 结尾回到家里那点安稳：{positive_direction or '不是夸苦难，而是把这些辛苦最后怎样托住父母、孩子、伴侣和整个家的秩序写出来。'}"
            ),
        }

    topic_title = str(ai_payload.get("topic_title") or ai_payload.get("project_title") or "").strip()
    topic_angle = str(ai_payload.get("topic_angle") or "").strip()
    mode = _resolve_local_generic_fallback_mode(ai_payload)
    problem_brief = ai_payload.get("problem_brief")
    theme_axis = ""
    core_conflict = ""
    if isinstance(problem_brief, Mapping):
        theme_axis = _clean_local_fallback_instruction_phrase(str(problem_brief.get("theme_axis") or "").strip())
        core_conflict = _clean_local_fallback_instruction_phrase(str(problem_brief.get("core_conflict") or "").strip())

    hook = _resolve_local_generic_outline_hook(
        payload=ai_payload,
        mode=mode,
        topic_title=topic_title,
        topic_angle=topic_angle,
        theme_axis=theme_axis,
        core_conflict=core_conflict,
    )
    point_one, point_two, point_three, point_four = _resolve_local_generic_outline_points(
        payload=ai_payload,
        mode=mode,
        topic_angle=topic_angle,
        theme_axis=theme_axis,
        core_conflict=core_conflict,
        positive_direction=positive_direction,
    )
    return {
        "hook": hook,
        "outline_body": (
            f"### 1. {_ensure_sentence_end(point_one)}\n"
            f"### 2. {_ensure_sentence_end(point_two)}\n"
            f"### 3. {_ensure_sentence_end(point_three)}\n"
            f"### 4. {_ensure_sentence_end(point_four)}"
        ),
    }


def _generate_outline_with_transient_recovery(
    *,
    project: sqlite3.Row,
    generator,
    ai_payload: dict[str, object],
) -> dict[str, str]:
    allow_retry = (
        str(project["source_type"]) == "tracked_article"
        and bool(ai_payload.get("strategy_first_outline_mode"))
        and bool(getattr(generator, "uses_custom_base_url", False))
    )
    try:
        return generator.generate_outline(ai_payload)
    except _OUTLINE_TRANSIENT_PROVIDER_ERRORS as exc:
        if not allow_retry:
            raise
        logger.warning(
            "Tracked article outline transient failure for project %s; retrying with compact recovery prompt: %s",
            project["slug"],
            exc,
        )
        recovery_payload = _build_outline_timeout_recovery_payload(
            project=project,
            ai_payload=ai_payload,
        )
        try:
            return generator.generate_outline(recovery_payload)
        except Exception as recovery_exc:
            if not _allow_local_creative_fallbacks():
                _raise_creative_upstream_failure("大纲生成", recovery_exc)
            logger.warning(
                "Tracked article outline recovery failed for project %s; using local outline fallback: %s",
                project["slug"],
                recovery_exc,
            )
            fallback_payload = _build_local_tracked_article_fallback_payload(
                project=project,
                payload=ai_payload,
            )
            return _build_local_tracked_article_outline_fallback(fallback_payload)


def _build_outline_timeout_recovery_payload(
    *,
    project: sqlite3.Row,
    ai_payload: Mapping[str, object],
) -> dict[str, object]:
    recovery_payload = dict(ai_payload)
    recovery_payload["source_type"] = str(project["source_type"])
    recovery_payload["outline_timeout_recovery_mode"] = True
    return recovery_payload


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
            candidate_selection_context = _build_draft_candidate_selection_context(
                project=project,
                reference_article_payload=reference_article_payload,
                strategy_bundle_payload=strategy_bundle_payload,
            )
            initial_candidates = _generate_initial_draft_candidates(
                project=project,
                generator=generator,
                draft_payload=draft_payload,
            )
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
                    selection_context=candidate_selection_context,
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
                )
                body_markdown = finalized_candidate.body_markdown
                title = finalized_candidate.title
            body_markdown = _apply_final_tracked_article_guard(
                title=title,
                body_markdown=body_markdown,
                source_type=str(project["source_type"]),
                reference_source_markdown=_get_project_reference_source_markdown(project),
            )
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
    strategy_first_draft_mode = _should_use_tracked_article_strategy_first_draft_mode(
        draft_payload,
        is_polish_mode=is_polish_mode,
    )
    if strategy_first_draft_mode:
        draft_payload = dict(draft_payload)
        draft_payload["strategy_first_draft_mode"] = True

    if strategy_first_draft_mode and is_tracked_article and not is_polish_mode and uses_custom_base_url:
        try:
            initial_result = generator.generate_draft(draft_payload)
        except _OUTLINE_TRANSIENT_PROVIDER_ERRORS as exc:
            logger.warning(
                "Strategy-first draft transient failure for project %s; retrying with timeout recovery prompt: %s",
                project["slug"],
                exc,
            )
            recovery_payload = _build_draft_timeout_recovery_payload(
                project=project,
                draft_payload=draft_payload,
            )
            try:
                initial_result = generator.generate_draft(recovery_payload)
            except Exception as recovery_exc:
                if not _allow_local_creative_fallbacks():
                    _raise_creative_upstream_failure("正文生成", recovery_exc)
                logger.warning(
                    "Strategy-first timeout recovery draft branch failed for project %s; using local draft fallback: %s",
                    project["slug"],
                    recovery_exc,
                )
                fallback_payload = _build_local_tracked_article_fallback_payload(
                    project=project,
                    payload=draft_payload,
                )
                fallback_title, fallback_body_markdown = _build_local_tracked_article_draft_fallback(
                    fallback_payload
                )
                initial_result = {
                    "title": fallback_title,
                    "body_markdown": fallback_body_markdown,
                }
        return [
            (
                str(initial_result["title"]),
                str(initial_result["body_markdown"]),
            )
        ]

    if not is_tracked_article or is_polish_mode or not uses_custom_base_url:
        initial_result = generator.generate_draft(draft_payload)
        return [
            (
                str(initial_result["title"]),
                str(initial_result["body_markdown"]),
            )
        ]

    strategy_card = draft_payload.get("strategy_card")
    compact_allowed_modes = {"scene_first_progression", "pressure_interface_direct"}
    if isinstance(strategy_card, Mapping):
        expected_mode = _resolve_tracked_article_expected_selection_mode(draft_payload)
        if expected_mode and expected_mode not in compact_allowed_modes:
            try:
                initial_result = generator.generate_draft(draft_payload)
            except _OUTLINE_TRANSIENT_PROVIDER_ERRORS as exc:
                logger.warning(
                    "Tracked article draft transient failure for project %s; retrying with timeout recovery prompt: %s",
                    project["slug"],
                    exc,
                )
                recovery_payload = _build_draft_timeout_recovery_payload(
                    project=project,
                    draft_payload=draft_payload,
                )
                try:
                    initial_result = generator.generate_draft(recovery_payload)
                except Exception as recovery_exc:
                    if not _allow_local_creative_fallbacks():
                        _raise_creative_upstream_failure("正文生成", recovery_exc)
                    logger.warning(
                        "Tracked article timeout recovery draft branch failed for project %s; using local draft fallback: %s",
                        project["slug"],
                        recovery_exc,
                    )
                    fallback_payload = _build_local_tracked_article_fallback_payload(
                        project=project,
                        payload=draft_payload,
                    )
                    fallback_title, fallback_body_markdown = _build_local_tracked_article_draft_fallback(
                        fallback_payload
                    )
                    initial_result = {
                        "title": fallback_title,
                        "body_markdown": fallback_body_markdown,
                    }
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
            if not _allow_local_creative_fallbacks():
                if isinstance(recovery_exc, _OUTLINE_TRANSIENT_PROVIDER_ERRORS):
                    _raise_creative_upstream_failure("正文生成", recovery_exc)
                raise
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
    if not _allow_extra_quality_candidate_generation():
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
    for key in ("benchmarks", "reference_article_hidden", "compact_strategy_mode", "strategy_first_draft_mode"):
        recovery_payload.pop(key, None)
    recovery_payload["timeout_recovery_mode"] = True
    return recovery_payload


def _build_assets_timeout_recovery_payload(
    *,
    assets_payload: Mapping[str, object],
) -> dict[str, object]:
    recovery_payload = dict(assets_payload)
    recovery_payload.pop("benchmarks", None)
    recovery_payload["assets_timeout_recovery_mode"] = True
    return recovery_payload


def _build_publish_timeout_recovery_payload(
    *,
    publish_payload: Mapping[str, object],
) -> dict[str, object]:
    recovery_payload = dict(publish_payload)
    recovery_payload.pop("benchmarks", None)
    recovery_payload["publish_timeout_recovery_mode"] = True
    return recovery_payload


def _build_nested_draft_retry_payload(
    payload: Mapping[str, object],
    *,
    generator,
) -> dict[str, object]:
    nested_payload = dict(payload)
    if bool(getattr(generator, "uses_custom_base_url", False)):
        nested_payload["compact_polish_mode"] = True
    return nested_payload


def _extract_local_draft_outline_points(outline_body: str) -> list[str]:
    points: list[str] = []
    for raw_line in outline_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[0-9一二三四五六七八九十]+[.、)\s]+", "", line)
        line = line.strip("：: ")
        if line:
            if re.match(r"^(?:开头|中段(?:[一二三四五六七八九十\d]+)?|前半篇|后半篇|结尾|尾段|标题|导语|正文)(?:[：:]\s*|$)", line):
                continue
            if _looks_like_local_fallback_instruction_fragment(line) or _looks_like_local_fallback_strategy_scaffold(line):
                continue
            points.append(line)
    return points


def _extract_local_fallback_corpus(payload: Mapping[str, object]) -> str:
    fields: list[str] = [
        str(payload.get("topic_title") or "").strip(),
        str(payload.get("topic_angle") or "").strip(),
        str(payload.get("project_title") or "").strip(),
        str(payload.get("article_title") or "").strip(),
        str(payload.get("summary") or "").strip(),
        str(payload.get("structure_notes") or "").strip(),
        str(payload.get("body_markdown") or "").strip(),
        str(payload.get("reference_article_title") or "").strip(),
        str(payload.get("reference_article_summary") or "").strip(),
        str(payload.get("reference_article_structure_notes") or "").strip(),
        str(payload.get("reference_article_body_markdown") or "").strip(),
    ]
    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        for key in (
            "raw_goal",
            "clarified_problem",
            "observed_phenomenon",
            "writing_goal",
            "target_reader_situation",
            "core_conflict",
            "feedback_entry",
            "theme_axis",
            "emotional_value_goal",
            "anti_drift_axis",
        ):
            fields.append(str(problem_brief.get(key) or "").strip())
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        for key in (
            "reader_situation",
            "point_of_view",
            "conflict_frame",
            "emotional_path",
            "opening_move",
            "body_shift",
            "ending_move",
            "benchmark_summary",
            "hook_trigger",
            "progression_drive",
            "positive_direction",
            "packaging_focus",
            "packaging_hook",
        ):
            fields.append(str(strategy_card.get(key) or "").strip())
        for key in ("scene_anchor_requirements", "quotable_line_seeds", "writing_texture_notes"):
            value = strategy_card.get(key)
            if isinstance(value, list):
                fields.extend(str(item).strip() for item in value if str(item).strip())
    for key in ("tags", "reference_article_tags"):
        value = payload.get(key)
        if isinstance(value, list):
            fields.extend(str(item).strip() for item in value if str(item).strip())
    return " ".join(item for item in fields if item)


def _extract_local_reference_corpus(payload: Mapping[str, object]) -> str:
    fields: list[str] = [
        str(payload.get("article_title") or "").strip(),
        str(payload.get("summary") or "").strip(),
        str(payload.get("structure_notes") or "").strip(),
        str(payload.get("body_markdown") or "").strip(),
        str(payload.get("reference_article_title") or "").strip(),
        str(payload.get("reference_article_summary") or "").strip(),
        str(payload.get("reference_article_structure_notes") or "").strip(),
        str(payload.get("reference_article_body_markdown") or "").strip(),
    ]
    for key in ("tags", "reference_article_tags"):
        value = payload.get(key)
        if isinstance(value, list):
            fields.extend(str(item).strip() for item in value if str(item).strip())
    return " ".join(item for item in fields if item)


def _extract_local_reference_paragraphs(payload: Mapping[str, object]) -> list[str]:
    paragraphs: list[str] = []
    for raw in (
        payload.get("body_markdown"),
        payload.get("reference_article_body_markdown"),
    ):
        markdown = str(raw or "").strip()
        if not markdown:
            continue
        for chunk in re.split(r"\n\s*\n", markdown):
            cleaned = re.sub(r"^#+\s*", "", chunk.strip())
            if cleaned:
                paragraphs.append(cleaned)
    return paragraphs


def _has_local_scene_first_office_markers(text: str) -> bool:
    return any(token in text for token in ("会议室", "投影幕布", "散会", "老方案", "资料", "咖啡"))


def _has_local_scene_first_transit_markers(text: str) -> bool:
    return any(token in text for token in ("地铁口", "接驳车", "围巾", "白雾", "上车"))


def _has_local_scene_first_household_markers(text: str) -> bool:
    return any(token in text for token in ("药盒", "检查单", "水壶", "孩子睡了", "夜里回家", "家里的心事", "明天再说", "慢慢说开"))


def _resolve_local_scene_first_hook(payload: Mapping[str, object], *, topic_angle: str) -> str:
    reference_corpus = _extract_local_reference_corpus(payload)
    scene_corpus = f"{topic_angle} {reference_corpus}"
    if _has_local_scene_first_office_markers(scene_corpus):
        return "周一的会还没开始，她握着翻页笔站在侧边，又把昨晚那版先压到了后面。"
    if _has_local_scene_first_transit_markers(scene_corpus):
        return "雨停了，车还没进站。她盯着对话框里那句删了又停住的话，指尖一直没离开屏幕。"
    if _has_local_scene_first_household_markers(scene_corpus):
        return "夜里进门时，餐桌只收了一半，壶身还有余温，那张单子正压在桌角。"

    for paragraph in _extract_local_reference_paragraphs(payload):
        compact = re.sub(r"\s+", "", paragraph)
        if 12 <= len(compact) <= 44:
            return _ensure_sentence_end(paragraph.replace("“", "\"").replace("”", "\""))
    return ""


def _pick_local_seeded_index(payload: Mapping[str, object], size: int) -> int:
    if size <= 0:
        return 0
    seed = " ".join(
        str(payload.get(key) or "")
        for key in (
            "topic_title",
            "topic_angle",
            "project_title",
            "article_title",
            "reference_article_title",
            "reference_article_summary",
            "reference_article_structure_notes",
            "reference_article_body_markdown",
        )
    )
    seed = seed or _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    return sum(ord(char) for char in seed) % size


def _pick_local_seeded_text_variant(payload: Mapping[str, object], options: tuple[str, ...]) -> str:
    if not options:
        return ""
    return options[_pick_local_seeded_index(payload, len(options))]


def _pick_local_seeded_pair_variant(payload: Mapping[str, object], options: tuple[tuple[str, str], ...]) -> tuple[str, str]:
    if not options:
        return "", ""
    return options[_pick_local_seeded_index(payload, len(options))]


def _pick_local_self_reliance_title(payload: Mapping[str, object], lane: str = "external") -> str:
    options_by_lane: dict[str, tuple[str, ...]] = {
        "inward": (
            "最难的时候，先把自己稳住",
            "向内求的人，也能慢慢走出风雨",
            "把自己稳住，选择就有了转身的余地",
        ),
        "external": (
            "没人替你扛时，先把自己扶稳",
            "求助不丢人，自救也不丢人",
            "能把自己扶稳的人，路会越走越宽",
        ),
        "generic": (
            "越是乱的时候，越要先稳住自己",
            "把眼前事理清，人就不会一直被难处推着走",
            "先把自己扶稳，才有力气接住明天",
        ),
    }
    return _pick_local_seeded_text_variant(payload, options_by_lane.get(lane, options_by_lane["external"]))


def _resolve_local_mode_reference_opening(payload: Mapping[str, object], mode: str) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if not corpus:
        return ""

    if mode == "inner_settlement":
        if _uses_local_inner_settlement_stage_restart_variant(payload):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "翻回年初那页计划时，别急着给这半年判输。",
                    "到了半年这个节点，人很容易先盯着没完成的那几项。",
                    "这半年或许没完全照着计划走，但它也不是白白过去的。",
                ),
            )
        if _uses_local_inner_settlement_homecoming_variant(payload):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "心总往外悬着的时候，热闹也像临时借住。先把自己安顿下来，日子才会落稳。",
                    "外面的风景再热闹，心里若没有归处，人还是会觉得漂。",
                ),
            )
        if any(token in corpus for token in ("心若不安", "此心安处", "一餐一饮", "一呼一吸", "静待花开")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "心一直悬着的时候，普通一天也像差一点没落地。",
                    "外面的事吵不吵先放一放，心里那口气没放下来，人就很难睡踏实。",
                ),
            )
        if any(token in corpus for token in ("睡不着", "翻来覆去", "夜里", "放不下")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "夜里安静下来，白天顾不上想的事，会一件件回到眼前。",
                    "白天能压住的心事，一到夜里，又在枕边坐下来。",
                ),
            )

    if mode == "self_worth_rebuild":
        if any(token in corpus for token in ("打折品", "奢侈品", "身价", "门槛", "标准收紧", "配得上")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "你不是没有标准，只是太习惯先把场面让过去，连自己那点不舒服也跟着往后放了。",
                    "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。",
                ),
            )
        if any(token in corpus for token in ("都可以", "算了", "我没事", "将就")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "那句“都可以”说出口的时候，你其实已经把自己往后让了一步。",
                    "你明明也有想法，可轮到自己时，还是习惯先说一句“算了，也行”。",
                ),
            )

    if mode == "supportive_appreciation":
        if any(token in corpus for token in ("并不傻", "拎得清", "心里比谁都拎得清", "不去计较")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "饭桌上那句话刚落下，他夹菜的手停了一下，又很快把话题接了过去。",
                    "消息里那句玩笑其实有点刺，他看了一会儿，最后只回了个轻一点的语气。",
                ),
            )
        if any(token in corpus for token in ("时有暴雨", "无尽暴雨", "去拥抱你", "四季平凡", "身边有你")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "他愿意替关系多留一点余地，也愿意在风雨来的时候，先把温柔递出去。",
                    "很多柔软都不是天生迟钝，而是明明看得清，还是愿意给在乎的人多留一点暖意。",
                ),
            )

    if mode == "self_reliance_inward_support":
        if _uses_local_self_reliance_shared_burden_variant(payload) or any(
            token in corpus for token in ("向内求", "自救自渡", "自己熬过寒冬", "负重前行", "只有靠自己", "没人可找", "大家都在忙", "先把自己稳住", "日子接回来", "向外等")
        ):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "电话拨出去之前，你先把桌上的单子理了一遍。",
                    "事情一多的时候，先把眼前能确定的一件事抓住。",
                ),
            )

    if mode == "emotional_engine_direct":
        if _uses_local_emotional_regret_forward_variant(payload):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "傍晚看见那件旧裙子时，阿婆的手在裙边停了很久。",
                    "有些旧东西一翻出来，人就忍不住替过去重新想一遍。",
                    "阿婆把那条洗得发白的裙子拿在手里时，嘴上没说遗憾，眼神已经先回去了。",
                ),
            )
        if _uses_local_emotional_endings_acceptance_variant(payload):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "路过以前常去的那家店时，你还是会下意识慢一点。",
                    "有些相遇没走到最后，却把看人的眼光和爱人的分寸留给了你。",
                ),
            )
        if _uses_local_emotional_forgiveness_release_variant(payload):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "有些人和事一直放在心里，最先被困住的往往不是别人，是你自己。",
                    "你以为一直计较是在替自己讨公道，后来才发现，心也被那口气拽住了很久。",
                ),
            )
        if "要是他还在就好了" in corpus:
            return "很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。"
        if any(token in corpus for token in ("背影", "擦肩", "街头", "像他")):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "街头一个像他的背影晃过去，你还是会下意识多看一眼。",
                    "你以为自己早就放下了，直到街上一个相似的背影，又把那段旧事轻轻带了回来。",
                ),
            )
        if any(token in corpus for token in ("旧相册", "聊天记录", "过客", "遗忘")):
            return "你以为自己已经把那段路放下了，可翻到旧照片、点开聊天记录的时候，心还是会轻轻一沉。"
        if _uses_local_emotional_memory_reflux_variant(payload):
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "往事最会挑人不设防的时候回来，路上一个身影，手机里一页旧记录，心就先顿了一下。",
                    "你以为那段路已经翻篇了，直到某个普通傍晚，它又被一个背影、一页旧记录轻轻带了回来。",
                ),
            )

    if mode == "response_priority":
        has_comment_like = "点赞" in corpus and "评论" in corpus
        has_photo_scene = any(token in corpus for token in ("晚霞", "夕阳", "落日", "朋友圈", "照片"))
        has_followup = any(token in corpus for token in ("多问一句", "追问", "补问", "我没事", "我有点累", "飞得累不累"))
        has_time_priority = any(
            token in corpus
            for token in ("没时间", "红灯30秒", "等红绿灯", "24小时在线", "优先", "优先级", "时间在哪儿", "心就在哪儿")
        )
        if has_comment_like and has_photo_scene:
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "朋友圈那张晚霞发出去以后，最后留在心里的，常常是那句认真追问。",
                    "你发了一张晚霞照，本来只想轻轻带过一天。可真正把你放在心上的人，还是会顺着那句配文多看一眼。",
                ),
            )
        if has_time_priority and not has_comment_like:
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "他说自己很忙那一刻，你把手机放下，心里那点期待也跟着安静了一下。",
                    "红灯的三十秒都能喝口水、切首歌、回一句“晚点找你”。有些在意，就藏在这些小空当里。",
                ),
            )
        if has_followup and "我没事" in corpus:
            return _pick_local_seeded_text_variant(
                payload,
                (
                    "你明明只回了一句“我没事”，真正在意你的人，还是会再追一句。",
                    "有时候最让人心里一松的，不是很多回应，而是你说“我没事”以后，还有人肯再问一句。",
                ),
            )
        if has_comment_like:
            return "很多互动都会路过你，最后留在心里的，常常是那句认真追问。"

    return ""


def _resolve_local_scene_first_outline_points(
    payload: Mapping[str, object],
    *,
    positive_direction: str,
    default_closing: str,
) -> tuple[str, str, str, str] | None:
    reference_corpus = _extract_local_reference_corpus(payload)
    cleaned_positive = _clean_local_fallback_instruction_phrase(positive_direction)
    point_four = default_closing
    if cleaned_positive and not _looks_like_local_fallback_instruction_fragment(cleaned_positive):
        point_four = cleaned_positive

    if _has_local_scene_first_office_markers(reference_corpus):
        return (
            "会议开始前，她把改过的方案又往后拨了一下，像是先替自己留了个退路。",
            "一句“今天先按老方案过吧”落下来，你明明看见问题了，还是先顺着场面把头点了下去。",
            "等人都散了，你又坐回原位，把那句本来该在当场说的话，在心里补了一遍又一遍。话总留到这里，位置也会跟着一点点往后退。",
            point_four or "下次再进会议室，别总把关键那句留到散会后。",
        )
    if _has_local_scene_first_transit_markers(reference_corpus):
        return (
            "雨停了，车还没来。她盯着那条没发出去的消息，像是在等一个能把话接下去的时机。",
            "对方只轻轻带过一句最近事多，你听懂了她在往后收，却还是先把追问压在了舌尖上。",
            "车门一开，两个人跟着人群上去，各自坐下，窗玻璃慢慢起了白气，刚才那个话头也就这么断在了路上。",
            point_four or "很多关系要想留住靠近，不是等懂事一点，而是别总把那句真话拖到转身以后。",
        )
    if _has_local_scene_first_household_markers(reference_corpus):
        return (
            "夜里进门时，餐桌还留着收了一半的样子，检查单和水壶都没动，孩子已经睡了。",
            "有些话明明就卡在嘴边，可一想到别把家里弄得更紧，那句追问又被你自己顺回了沉默里。",
            "第二天照常出门，饭照吃，消息照回，表面像是翻过去了，可那点没说开的东西还一直压在心里。",
            point_four or "真正重要的话，不该总输给维持表面平静的本能。",
        )
    return None


def _resolve_local_scene_first_packaging_copy(scene_variant: str) -> tuple[str, str, str]:
    mapping = {
        "office": (
            "会已经散了，那页改过的方案还亮在屏幕上。真正让人难受的，是那句你明明该在当场说的话，最后又留给了自己。",
            "该说的时候开口，才不会总在散会以后后悔。",
            "你有判断，只是总把场面放在前面。关键时刻肯开口，会把自己放回该在的位置。",
        ),
        "transit": (
            "她那句“最近有点忙”刚落下去，你就知道她不止这一句话。可摆渡车一到，今晚最该问的那一句，还是跟着风一起被你按了回去。",
            "那句该问的话，别总留到车开以后。",
            "很多走远，不是一下子发生的。常常就是那句该在当场说的话，被顺手留到了后来。话一再往后放，心也就跟着退了半步。",
        ),
        "household": (
            "药盒和检查单就在桌上，谁都看见了，谁都先没提。家里很多心事，不是没人想说，是大家都怕一开口，这个晚上会更沉。",
            "家里的难，不怕摊开说，就怕一直各自忍着。",
            "家里最怕的，不是遇到事，是大家都想体谅，结果谁都不肯先说。把心事说开，日子才真的稳得住。",
        ),
    }
    return mapping.get(scene_variant, ("", "", ""))


def _resolve_local_scene_first_publish_lead(scene_variant: str) -> str:
    mapping = {
        "office": "下一次再进会议室，别急着把关键那句留到散会后。你有判断，也该让它在当场有位置。",
        "transit": "有些话不是不能问，是总被车门、时间和那句“算了”顺手按回去。该问的时候多停半分钟，关系就少一点后来才懂的距离。",
        "household": "药盒和检查单都在桌上时，真正要紧的不是谁先装作没事。把话摊开一点，家里的那口气才会慢慢松下来。",
    }
    return mapping.get(scene_variant, "有些话别总留到转身以后。该在当场说清的那一句，早一点出口，关系就少一点绕远。")


def _has_local_pressure_interface_direct_focus(payload: Mapping[str, object]) -> bool:
    strategy_card = payload.get("strategy_card")
    mode_candidates: list[str] = []
    if isinstance(strategy_card, Mapping):
        mode_candidates.append(str(strategy_card.get("structure_mode") or "").strip())
    mode_candidates.extend(
        [
            str(payload.get("analysis_structure_mode") or "").strip(),
            str(payload.get("reference_article_analysis_structure_mode") or "").strip(),
        ]
    )
    if any(mode == "pressure_interface_direct" for mode in mode_candidates):
        return True
    if any(mode == "internal_pressure" for mode in mode_candidates):
        return True
    if _infer_tracked_article_pressure_guard(payload) == "internal_pressure":
        return True

    corpus = _extract_local_fallback_corpus(payload)
    if not corpus:
        return False
    pressure_hits = sum(
        1
        for token in (
            "体检",
            "复查",
            "复诊",
            "日历",
            "提醒",
            "自我照料",
            "照顾自己",
            "生活顺序",
            "排回今天",
            "排回前面",
            "把自己排回",
            "饭点",
            "按时吃",
            "被挪走",
            "往后挪",
            "往后推",
            "往后改",
        )
        if token in corpus
    )
    self_order_hits = sum(
        1
        for token in ("照顾自己", "自我照料", "把自己", "排回今天", "生活顺序", "该停", "饭按时", "先回稳")
        if token in corpus
    )
    family_responsibility_hits = sum(
        1
        for token in ("父母", "孩子", "伴侣", "家里", "家人", "一家人", "账单", "补习费用", "学费")
        if token in corpus
    )
    return pressure_hits >= 2 and self_order_hits >= 1 and family_responsibility_hits <= 1


def _looks_like_local_responsibility_shelter_payload(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_fallback_corpus(payload)
    if not corpus:
        return False
    if _has_local_pressure_interface_direct_focus(payload):
        return False
    if _has_local_scene_first_household_markers(corpus):
        household_scene_hits = sum(
            1
            for token in (
                "检查单",
                "水壶",
                "夜里回家",
                "孩子已经睡了",
                "明天再说吧",
                "收了回去",
                "说开",
                "想问一句",
            )
            if token in corpus
        )
        hard_responsibility_anchors = sum(
            1
            for token in ("没事，有我", "没事有我", "撑起一个家", "主心骨", "肩上", "把风雨先挡住")
            if token in corpus
        )
        if household_scene_hits >= 3 and hard_responsibility_anchors == 0:
            return False
    if any(
        token in corpus
        for token in (
            "简单快乐",
            "知己二三",
            "家人安康",
            "四季平安",
            "大富大贵",
            "知足",
            "香车美宅",
            "高朋满座",
        )
    ):
        return False
    hard_responsibility_hits = sum(
        1
        for token in (
            "没事，有我",
            "没事有我",
            "家稳住",
            "把家稳住",
            "家里一有事",
            "账单",
            "补习费用",
            "缴费",
            "请假",
            "绩效",
            "工作考核",
            "复查",
            "复诊",
            "医院",
            "校门口",
            "接孩子",
            "接送",
            "放学",
            "喉咙发紧",
            "撑起一个家",
            "父母的拐杖",
            "孩子的雨伞",
            "伴侣的靠山",
            "排班表",
            "肩上",
            "主心骨",
            "一家人",
            "把风雨先挡住",
        )
        if token in corpus
    )
    family_hits = sum(
        1
        for token in (
            "父母",
            "爸妈",
            "孩子",
            "伴侣",
            "家里",
            "家人",
            "老人",
            "生活费",
            "房贷",
            "学费",
            "补习",
            "复诊",
            "医院",
        )
        if token in corpus
    )
    core_responsibility_hits = sum(
        1
        for token in (
            "责任",
            "中年",
            "没事",
            "有我",
            "安排",
            "顺序",
            "排顺序",
            "家稳住",
            "复查",
            "医院",
            "请假",
            "接送",
            "放学",
            "扛住",
            "撑住",
            "安稳",
            "护住",
            "托住",
            "放稳",
            "重要的人",
        )
        if token in corpus
    )
    response_specific_hits = sum(
        1
        for token in ("评论", "点赞", "追问", "补问", "言外之意", "读懂", "轻互动", "回消息")
        if token in corpus
    )
    if hard_responsibility_hits <= 0 and not (
        family_hits >= 2 and core_responsibility_hits >= 3 and response_specific_hits <= 1
    ):
        return False
    responsibility_hits = sum(
        1
        for token in (
            "没事",
            "有我",
            "责任",
            "账单",
            "父母",
            "爸妈",
            "孩子",
            "伴侣",
            "家里",
            "家稳住",
            "安稳",
            "撑住",
            "中年",
            "肩上",
            "一家人",
            "主心骨",
        )
        if token in corpus
    )
    if responsibility_hits >= 4 and any(token in corpus for token in ("账单", "父母", "爸妈", "孩子", "伴侣", "家里", "安稳", "医院", "请假", "接送", "放学")):
        return True
    scene_hits = sum(
        1
        for token in ("缴费", "请假", "工作考核", "复查", "复诊", "医院", "校门口", "接孩子", "接送", "放学", "安排", "顺序", "排顺序")
        if token in corpus
    )
    return hard_responsibility_hits >= 1 and family_hits >= 1 and core_responsibility_hits >= 1 and scene_hits >= 1


def _should_use_local_responsibility_shelter_fallback(payload: Mapping[str, object]) -> bool:
    return _has_everyday_warmth_responsibility_shelter_focus(payload) or _looks_like_local_responsibility_shelter_payload(payload)


def _uses_local_responsibility_endurance_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    hard_endurance_hits = sum(
        1
        for token in (
            "成年人说过最多的谎",
            "值不值得",
            "熬过万般辛苦",
            "人间安稳",
            "不必感谢苦难",
        )
        if token in corpus
    )
    has_i_am_ok = "没事，有我" in corpus
    endurance_scene_hits = sum(
        1
        for token in (
            "辞职",
            "缴费窗口",
            "每一个黑夜",
            "撑起一片晴空",
            "暖黄灯光",
            "热气腾腾",
        )
        if token in corpus
    )
    return hard_endurance_hits >= 1 or (
        has_i_am_ok
        and "我没事" in corpus
        and endurance_scene_hits >= 2
    )


def _has_local_responsibility_endurance_concrete_duty(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    concrete_hits = sum(
        1
        for token in (
            "父母",
            "爸妈",
            "孩子",
            "账单",
            "补习",
            "请假",
            "绩效",
            "医院",
            "缴费",
            "伴侣",
        )
        if token in corpus
    )
    return concrete_hits >= 2


def _uses_local_responsibility_midlife_variant(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    midlife_hits = sum(
        1
        for token in (
            "中年",
            "半生风雨",
            "半生奔波",
            "日渐佝偻",
            "补习费用",
            "喉咙发紧",
            "请假",
            "工作考核",
            "绩效",
            "辞职",
            "值不值得",
            "暖黄灯光",
            "热气腾腾",
            "缴费窗口",
        )
        if token in corpus
    )
    family_hits = sum(1 for token in ("父母", "孩子", "账单", "伴侣", "家里") if token in corpus)
    return family_hits >= 3 and midlife_hits >= 4


def _resolve_local_responsibility_scene_kind(payload: Mapping[str, object]) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if not corpus:
        return "family"
    if _uses_local_responsibility_endurance_variant(payload) and any(
        token in corpus for token in ("没事", "值不值得", "万般辛苦", "人间安稳", "电话", "家里")
    ):
        return "call"
    if any(token in corpus for token in ("缴费窗口", "医院", "复诊", "复查", "病房", "走廊")):
        return "medical"
    scene_tokens: dict[str, tuple[str, ...]] = {
        "medical": ("缴费窗口", "医院", "复诊", "复查", "病房", "走廊"),
        "schedule": ("请假", "绩效", "工作考核", "排班", "会议", "工作"),
        "bills": ("账单", "补习费用", "补习", "缴费", "开销", "房贷", "生活费", "催款"),
        "pickup": ("放学", "校门口", "门口等", "接孩子", "接送", "画纸", "扑过来"),
        "call": ("电话", "来电", "接电话", "手机响", "手机一亮"),
    }
    candidates: list[tuple[int, str]] = []
    for scene, tokens in scene_tokens.items():
        if scene == "schedule" and not (
            "请假" in corpus and any(token in corpus for token in ("绩效", "工作考核", "排班", "会议", "工作"))
        ):
            continue
        positions = [corpus.find(token) for token in tokens if token in corpus]
        if positions:
            candidates.append((min(position for position in positions if position >= 0), scene))
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return "family"


def _resolve_local_responsibility_scene_title(payload: Mapping[str, object]) -> str:
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    title_by_scene = {
        "medical": "医院走廊里，你先让家人安心",
        "schedule": "请假前，你先把家里排稳",
        "bills": "账单摊开时，你先把日子排稳",
        "pickup": "校门口那一下，日子忽然有了光",
        "call": "那通电话后，你先把家安顿好",
        "family": "把家放在心上的人，也要被好好心疼",
    }
    return title_by_scene.get(scene_kind, title_by_scene["family"])


def _resolve_local_responsibility_endurance_topic_title(payload: Mapping[str, object]) -> str:
    return _pick_local_responsibility_text_variant(
        payload,
        (
            "家里一有事，你总会先把家稳住",
            "家里一有事，总是你先把顺序理出来",
        ),
    )


def _resolve_local_responsibility_endurance_packaging_title(payload: Mapping[str, object]) -> str:
    return _pick_local_responsibility_text_variant(
        payload,
        (
            "电话一响，你先翻日历",
            "电话一响，你先把顺序往前排",
            "手机一亮，你先算今天怎么排",
        ),
    )


def _pick_local_responsibility_text_variant(payload: Mapping[str, object], options: tuple[str, ...]) -> str:
    if not options:
        return ""
    seed = " ".join(
        str(payload.get(key) or "")
        for key in (
            "topic_title",
            "topic_angle",
            "project_title",
            "reference_article_summary",
            "reference_article_structure_notes",
            "reference_article_body_markdown",
        )
    )
    seed = seed or _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    return options[sum(ord(char) for char in seed) % len(options)]


def _resolve_local_responsibility_quote(payload: Mapping[str, object]) -> str:
    return "替家里多想的每一步，都会慢慢变成日子的底气。"


def _build_local_responsibility_probe(
    *,
    title: str = "",
    body_markdown: str = "",
    reference_source_markdown: str = "",
) -> dict[str, str]:
    return {
        "article_title": title,
        "topic_title": title,
        "project_title": title,
        "body_markdown": body_markdown,
        "reference_article_body_markdown": reference_source_markdown,
    }


def _resolve_local_responsibility_packaging_title(payload: Mapping[str, object]) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    scene_title = _resolve_local_responsibility_scene_title(payload)
    if _uses_local_responsibility_endurance_variant(payload) or _uses_local_responsibility_midlife_variant(payload):
        return _resolve_local_responsibility_endurance_packaging_title(payload)
    if any(token in corpus for token in ("请假", "账单", "补习", "缴费", "复查", "医院", "电话", "来电", "放学", "接送", "校门口", "接孩子", "门口等", "画纸", "扑过来")):
        return scene_title
    return "把家里日子托稳的人，也该被好好心疼"


def _resolve_local_responsibility_transition(payload: Mapping[str, object]) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if any(token in corpus for token in ("账单", "缴费", "催款")):
        return "账单被压在杯子下面，纸角微微卷起，却提醒人先把眼前的安排捋清。"
    if any(token in corpus for token in ("父母", "孩子", "伴侣")):
        return "饭桌还没摆好，父母的叮嘱和孩子的安排已经在心里排成一列。"
    if any(token in corpus for token in ("电话", "来电", "接电话")):
        return "那通电话挂断后，屋里安静了一会儿，下一步该怎么做反而更清楚。"
    return "水杯放在桌角，日子没有催人喊累，只催人把下一步安排好。"

def _clean_local_fallback_instruction_phrase(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(主线是|重点是|核心是)", "", cleaned).strip()
    cleaned = re.sub(r"^从[^：:]{0,32}切入[:：]?", "", cleaned).strip()
    cleaned = re.sub(r"^(先|再|最后)?写出[^：:\n]{0,80}[:：]", "", cleaned).strip()
    cleaned = re.sub(r"^把[“\"']?[^”\"'。！？!?；;\n]{0,80}[”\"']?写清楚[。！？!?]?$", "", cleaned).strip()
    cleaned = re.sub(
        r"^(先|再|最后)?(说清|写清|写出|拆开|落回|回到|结尾回到|最后把文章收回去|把代价落回真实生活|把事情为什么会变成这样|从那句“?没事.*?切入)[:：]?",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(r"^(先|再|最后)?(写|讲)(清|清楚|明|出|到)?", "", cleaned).strip()
    cleaned = re.sub(
        r"^[^：:\n]{0,18}(怎样|为什么|落在哪里|回到哪里|收成什么|写成什么)[^：:\n]{0,18}[:：]",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"^(责任|代价|结尾|最后|开头|中段|前半篇|后半篇|主线|包装|标题|导语)[^：:\n]{0,24}[:：]",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(r"^不要先讲道理，?", "", cleaned).strip()
    cleaned = re.sub(r"^先让读者看见[^，。]*[，。]?", "", cleaned).strip()
    cleaned = re.sub(r"[，,；;]?\s*把[^。！？!?；;\n]{0,48}写透[。！？!?]?$", "", cleaned).strip()
    cleaned = re.sub(r"[，,；;]?\s*让[^。！？!?；;\n]{0,48}写透[。！？!?]?$", "", cleaned).strip()
    cleaned = re.sub(r"[。；，]?\s*不要收成.*$", "", cleaned).strip()
    cleaned = re.sub(r"[。；，]?\s*不要只写.*$", "", cleaned).strip()
    cleaned = re.sub(r"[。；，]?\s*不要写成.*$", "", cleaned).strip()
    cleaned = cleaned.strip("：:，,；; ")
    return cleaned


def _looks_like_local_fallback_strategy_scaffold(text: str) -> bool:
    candidate = _clean_local_fallback_instruction_phrase(text)
    if not candidate:
        return False
    return bool(
        re.search(
            r"(为什么总在|为什么[^。]{0,80}怎样|后来又怎样|重点放在|重点写|不要停在|从[^。！？!?]{0,120}(切入|写起)|怎样重新|怎样慢慢|也写[^，。；;]{0,8}怎样|回到.*不要|写清楚|点出|说明|交代|拆开|收束到|为什么会变成常态)",
            candidate,
        )
    )


def _ensure_sentence_end(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if normalized[-1] in "。！？!?；;”’\"'":
        return normalized
    return normalized + "。"


def _compose_local_followup(primary: str, followup: str) -> str:
    primary_sentence = _ensure_sentence_end(primary)
    followup_sentence = _ensure_sentence_end(followup)
    primary_core = re.sub(r"[。！？!?；;”’\"']+$", "", primary_sentence).strip()
    followup_core = re.sub(r"[。！？!?；;”’\"']+$", "", followup_sentence).strip()
    if primary_core and primary_core in followup_sentence:
        return followup_sentence
    if followup_core and followup_core in primary_sentence:
        return primary_sentence

    def _compact_text(value: str) -> str:
        return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value)

    def _bigrams(value: str) -> set[str]:
        compact = _compact_text(value)
        if len(compact) < 2:
            return {compact} if compact else set()
        return {compact[index : index + 2] for index in range(len(compact) - 1)}

    primary_bigrams = _bigrams(primary_core)
    followup_bigrams = _bigrams(followup_core)
    if primary_bigrams and followup_bigrams:
        overlap_ratio = len(primary_bigrams & followup_bigrams) / min(len(primary_bigrams), len(followup_bigrams))
        if overlap_ratio >= 0.72:
            return followup_sentence if len(followup_core) <= len(primary_core) else primary_sentence
    return primary_sentence + followup_sentence


def _has_local_supportive_warmth_profile(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    return any(
        token in corpus
        for token in (
            "燃烧自己",
            "照亮别人",
            "你对他好",
            "别人递来一点暖意",
            "别人递来一点善意",
            "加倍把暖意还回去",
            "收到的暖意",
            "收到的善意",
            "温暖回给你",
            "你给他温暖",
            "回馈给你更多",
            "更多的温暖",
            "回暖别人的心",
            "真诚的道歉",
            "大方的原谅",
            "把歉意说出口时",
            "很多人就是在这种时候，误会了他",
            "他的分寸一直都在",
            "把在乎摆在了前面",
            "会先顾别人感受的人，也该有人反过来护住",
            "穿过无尽暴雨",
            "去拥抱你",
            "四季平凡",
            "身边有你",
        )
    )


def _has_local_supportive_apology_profile(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    return any(
        token in corpus
        for token in (
            "真诚的道歉",
            "大方的原谅",
            "把歉意说出口时",
            "道歉",
            "原谅",
            "歉意",
            "把语气放轻",
            "那份难受认认真真放在心上",
            "一句道歉不难",
        )
    )


def _has_local_supportive_misread_profile(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    return any(
        token in corpus
        for token in (
            "太好说话",
            "好欺负的错觉",
            "好欺负",
            "太过包容",
            "和好如初",
            "只要一句对不起",
            "一句“对不起”",
            "一句对不起就能换来",
        )
    )


def _has_local_supportive_discernment_profile(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    return any(
        token in corpus
        for token in (
            "并不傻",
            "拎得清",
            "心里比谁都拎得清",
            "不去计较",
            "输赢、对错和得失",
            "对错和得失",
            "谁是真心，谁在敷衍",
            "心里其实都分得清",
            "把情分看得更重",
            "把锋芒收回去",
            "夹菜的手停",
            "把话题接了过去",
            "把场面接住",
        )
    )


def _build_local_supportive_appreciation_paragraphs(
    *,
    payload: Mapping[str, object],
    intro: str,
) -> list[str]:
    stale_intro = any(token in (intro or "") for token in ("顺手让了一步", "先顾了别人感受", "场面放软"))
    if _has_local_supportive_misread_profile(payload):
        opening = intro.strip() if intro and intro.strip() and not stale_intro else "太好说话久了，别人很容易忘了，她也会疼。"
        return [
            opening,
            "对方道歉以后，她愿意把这件事往后放一放；心里那点不舒服还在，只是她把情分看得比一时的输赢更重。",
            "可惜关系里最容易出现的误会，偏偏就是这样来的。别人以为她肯退一步，是习惯让着；以为她愿意和好，是没有底线。",
            "其实她不是看不见，也不是分不清。谁在敷衍，谁把她的体谅当方便，谁只是仗着她心软一再往前试，她心里都有数。",
            "她之所以没有把话说重，往往不是因为没脾气，而是觉得一段关系能不伤就尽量别伤，能不散就先别散。",
            "体谅有分寸，也有底线。",
            "这种包容本来就很贵。因为不是每个人，都愿意在自己已经不舒服的时候，还先把场面顾一顾。",
            "所以别把她的和好如初，当成你可以继续随便的理由。她肯翻篇一次，是在给感情机会，不是在把自己交给你反复消耗。",
            "真正长久的关系，会珍惜这种体谅。看见她没有把话说绝，也会学着把分寸往回收，把尊重补上来。",
            "你若身边有这样的人，别只享受她带来的轻松。也要记得，她每一次没把话说重，都是在替关系留余地。",
            "余地被珍惜，温柔才会留得久。那份好，不该总靠她一个人扛着，也该有人认真地回过头来护住。",
        ]
    if _has_local_supportive_discernment_profile(payload):
        opening = intro.strip() if intro and intro.strip() and not stale_intro else "饭桌上那句话刚落下，他夹菜的手停了一下，又很快把话题接了过去。"
        return [
            opening,
            "心软的人，反应往往很快。谁是真心，谁在敷衍；哪句话只是无心，哪句话已经让自己不舒服，他心里都分得清。",
            "当场争个输赢不难，难的是还愿意看看眼前这个人值不值得继续走下去，这段关系还有没有必要被放回温柔里。",
            "旁人多半只看见他把气氛接住了，把难听的话轻轻带过去了。看不见的是，他已经把分寸在心里量过一遍。",
            "他不急着计较，心里有判断；他愿意包容，也会记得什么事不能一直被带过去。",
            "他肯把那些锋利先收一收，多半是因为心里还有在乎，还有舍不得。",
            "难得的地方也在这里。看得清以后还愿意体谅，明白得失以后还愿意把关系往暖处领，这份心软很有分量。",
            "别只记得他好说话。也要记得，这份温柔背后，藏着很多本可以说重、最后又轻轻收回去的话。",
            "能看懂这一层的人，自然会更珍惜。他递出来的，是一份有分寸的在乎，不会随手给谁。",
            "你若认真接住一次，他心里会记很久。温柔有了回应，才不会一点点往回收。",
            "这样的人若在你身边，别辜负他把锋芒收回去的那一下。你认真回一次，他的温柔才会一直亮着，心也会更安稳。",
        ]
    if _has_local_supportive_apology_profile(payload):
        opening = intro.strip() if intro and intro.strip() and not stale_intro else "明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。"
        return [
            opening,
            "很多人会把这一幕看成她心软，甚至觉得她好哄。可真正走进她心里的人会知道，她不是不疼，只是不想让关系一下子摔得太难看。",
            "她愿意把语气放轻，不是因为那点委屈不算什么。恰恰相反，正因为在乎，她才更希望这件事还有被说开的机会。",
            "一句道歉真正有分量的地方，也从来不只是把那两个字说出来。是有人看见她刚刚也难受了，愿意把那份难受接回来，而不是顺着她的退让就翻篇。",
            "她肯给台阶，是情分还在；她肯往前走一步，是想把关系往暖处带一带。",
            "可余地若总是她一个人在留，原谅若总是她一个人在给，心也会一点点凉下来。温柔不是拿来反复试探的，体谅也不是默认存在的。",
            "所以别只记得她最后还是算了。更要记得，在她把场面放软以后，认真问一句：“刚刚是不是让你受委屈了？”",
            "会原谅的人，本来就难得。更难得的，是有人懂她为什么还愿意原谅，也懂得从那以后把分寸放回心上。",
            "被这样珍惜过一次，温柔不会越来越薄。它会慢慢长成一段关系里最稳、也最让人安心的那部分。",
        ]
    if not _has_local_supportive_warmth_profile(payload):
        return [
            intro,
            _compose_local_followup(
                "性子柔的人也会有脾气。",
                "只是话到嘴边，她会先想一想：这句话说重了，对方会不会难过。",
            ),
            _compose_local_followup(
                "饭桌上有人说错了话，她会先笑一下，把气氛接过去。",
                "消息里有点委屈，她也会等情绪落下来，再挑一句不伤人的话回复。",
            ),
            _compose_local_followup(
                "她肯体谅，不代表她什么都不懂；她愿意把话放软，也不代表她不会受伤。",
                "谁让她难过，谁把她的体谅当成习惯，谁只在需要她的时候才想起她，她其实都知道。",
            ),
            _compose_local_followup(
                "她还愿意温柔，多半是情分还在。",
                "她愿意留台阶，是因为舍不得把一段关系推到更冷的地方。",
            ),
            _compose_local_followup(
                "可这份柔软一旦被当成理所当然，人就会慢慢失望。",
                "一次两次可以笑着过去，次数多了，那些没被回应的好意，也会一点点安静下来。",
            ),
            _compose_local_followup(
                "你若遇见这样的人，别只记得她容易消气。",
                "也要记得问一句：“刚才是不是让你不舒服了？”这句话落下来，她心里会暖很久。",
            ),
            _compose_local_followup(
                "我很喜欢一句话：“温柔到最后，看的是分寸，也看回应。”",
                "被认真回应过的柔软，会更愿意靠近；被一直轻慢的温柔，迟早会学会转身。真正让人安心的关系，会把她的柔软看作珍贵，而不是看作可以随便消耗。",
            ),
            _compose_local_followup(
                "能看懂这份心软，本来就很难。",
                "更难得的是，看见她的退让以后，也愿意反过来护住她的感受。",
            ),
            _compose_local_followup(
                "别把她的包容，当成不用珍惜的理由。",
                "她愿意把好脾气留给你，说明你在她心里有位置；你也该把认真和尊重还给她。",
            ),
            _compose_local_followup(
                "柔软被珍惜以后，会长出更踏实的爱。",
                "那份爱不喧哗，却很稳，像晚上有人给你留的一盏灯，安安静静地亮着。",
            ),
            _compose_local_followup(
                "这样的人若在你身边，别等她沉默了才想起她的好。",
                "她给出去的体谅，有人懂；她留下的台阶，有人轻轻走回来，关系才会一直暖。",
            ),
        ]

    return [
        "别人递来一点暖意，他常常会想办法再多还回去一点。",
        "你对他好一分，他会记在心里很久，转身又把这份好慢慢添一点还给你。",
        "这样的人，心里常常很软，也很重感情。不是不会累，只是看见别人对他的好，就舍不得让那份好落空。",
        "他未必把感谢说得很响，却会在很多小事里慢慢还回来：记得你的难处，留意你的情绪，也愿意在你需要的时候多往前走一步。",
        "心软的人最难得的地方，从来不只是脾气好。是他把关系看得认真，把别人给过的温暖，也认真放在心上。",
        "所以，别把他的柔软看得太轻。那份好脾气背后，是一个人愿意把善意继续传下去的能力。",
        "一生那么长，真正愿意把温暖回给你的人并不多。遇见了，就别只享受他的好，也要让他知道：他的真心有人看见。",
        "被认真珍惜过的温柔，会越来越亮。它会在平淡日子里慢慢长成踏实的爱，也会让两个人都更愿意靠近。",
    ]


def _build_local_inner_settlement_paragraphs(
    *,
    payload: Mapping[str, object],
    intro: str,
) -> list[str]:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    has_stage_restart = _uses_local_inner_settlement_stage_restart_variant(payload)
    has_homecoming = _uses_local_inner_settlement_homecoming_variant(payload)
    has_daily_ritual = any(
        token in corpus
        for token in ("一餐一饮", "把水烧开", "把饭吃完", "一顿饭", "把灯关好", "把明天要穿的衣服放好")
    )
    has_heart_knot = any(
        token in corpus for token in ("看似过不去的坎", "心结难解", "把心抚平", "把心看透", "郁结")
    )
    has_future_release = any(
        token in corpus
        for token in ("与时间同行", "静待花开", "已经过去的事", "还没发生的事", "不念过往", "不畏将来")
    )

    if has_stage_restart:
        return [
            intro,
            "年初写下的目标，到了这个时候再看，难免会有几项还空着。有人没等来想要的结果，有人没留住想留的人，也有人只是忙着把日子过下去，回头才发现，自己已经走了很远。",
            "可没完成，不等于没意义。计划没有全部兑现，不代表这半年只有遗憾。那些认真熬过的日子、及时伸手扶过你的人、你在低处也没有放弃的那点力气，都算数。",
            "人很容易在阶段节点上清算自己：为什么还没变好，为什么还是差一点，为什么别人好像都往前走了。可生活从来不是一张只看结果的成绩单，它也会把你怎么扛住、怎么调整、怎么重新开始，一笔一笔记下来。",
            "如果事与愿违，就先别急着把它判成坏事。有些路绕了一点，反而让你看清谁真的在身边；有些愿望晚了一点，也是在等你长出更合适的心力去接住它。",
            "下半年，不必一下子把人生追平。先把眼前事做好，把身边人珍惜好，把该休息的时候认真休息，把还能努力的地方继续往前推一点。",
            "愿你回头看这半年时，不只看见没完成的清单，也看见那个一路没有停下来的自己。前面还有新的日子，你带着这些经验和温暖继续走，就不算白走。",
        ]

    if has_homecoming and not has_future_release:
        return [
            intro,
            "回到家关上门，外面的声音还在，心里那口气也还没放下来。你给自己倒杯水，坐了好一会儿，才发现人悬着久了，连安静都需要慢慢适应。",
            "以前你总想等一个结果，等一句认可，等事情完全顺起来，再允许自己安心。可日子不会每一步都提前给答案，越把心交给外面，越容易被一点动静牵着走。",
            "把鞋摆好，把饭吃热，把水杯洗干净放回原处。心安先落在这些能亲手做的小事里，人也从这些小事里一点点回到自己身上。",
            "苏轼说：“此心安处是吾乡。”这句话动人的地方，在于它把归处放回心里。外面的风还会吹，脚下的路却可以一天一天走稳。",
            "所以今晚别急着把世界理顺。先把自己带回屋里这盏灯、这口热饭、这张能睡下来的床。心回来了，日子就有了安放。",
        ]

    if not has_future_release and not has_heart_knot:
        return [
            intro,
            "白天忙的时候还顾不上。一安静下来，那句没接住的话、那个没想明白的决定，就又自己浮上来了。",
            "人一悬着，就容易把很多小事都听重了。别人一句随口的话，你会反复想；手机亮一下，心里也先紧一下。",
            "别急着催自己马上想通。先把水烧开，把饭吃完，把明天要穿的衣服放在手边。一个人能照顾好眼前，心就有地方落下来。",
            "有些事不用今晚解决。有些人，也不用今晚想明白。先把日子过回眼前，心才会慢慢从那些反复里退出来。",
            "等你能好好睡一觉，能把早饭吃下去，很多结其实已经在松了。把心放回今天，明天才有力气继续往前。",
        ]

    paragraph_two = (
        "有些坎当时像堵在胸口，回头再看，卡住人的常常是那口气一直绷着，非要马上给自己一个说法。"
        if has_heart_knot
        else "白天忙的时候还顾不上。一安静下来，那句没接住的话、那个没想明白的决定，就又自己浮上来了。"
    )
    paragraph_three = (
        "已经过去的事，今天先别再一遍遍回头想；还没发生的事，也不必提前在心里演很多遍。人一这么预支，心就更难落回现在。"
        if has_future_release
        else "人一悬着，就容易把很多小事都听重了。别人一句随口的话，你会反复想；手机亮一下，心里也先紧一下。"
    )
    paragraph_four = (
        "心安可以很小：水烧开，饭吃完，明天要穿的衣服放在手边，今天就先到这里。"
        if has_daily_ritual
        else "别急着催自己马上有答案。今晚先把水喝完，把灯关好，把反复翻出来的事轻轻放回明天。"
    )
    paragraph_five = (
        "把今天先过稳，把这顿饭吃完，把灯关好。很多答案不会今晚就来，但心会先慢慢安静下来。"
        if has_future_release
        else "有些事不用今晚解决。有些人，也不用今晚想明白。先把日子过回眼前，心才会慢慢从那些反复里退出来。"
    )
    paragraph_six = (
        "等你肯把脚下这点日常重新拾起来，郁结就不会再那样死死拽着你。心安不靠世界突然安静，先靠你肯让自己喘一口气。"
        if has_heart_knot or has_future_release
        else "等你能好好睡一觉，能把早饭吃下去，很多结其实已经在松了。把心放回今天，明天才有力气继续往前。"
    )

    return [
        intro,
        paragraph_two,
        paragraph_three,
        paragraph_four,
        paragraph_five,
        paragraph_six,
    ]


def _looks_like_local_fallback_instruction_fragment(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if any(
        token in candidate
        for token in (
            "结构性压力",
            "写透",
            "被催缴的现实",
            "家庭支持变薄",
            "养育成本",
            "照护责任",
            "必须扛",
            "快没油的灯",
            "排优先级",
            "留应急空间",
            "写清楚",
            "点出",
            "说明",
            "交代",
            "拆开",
            "收束到",
            "为什么会变成常态",
            "为什么连",
        )
    ):
        return True
    prefix = candidate[:28]
    if "：" in prefix or ":" in prefix:
        return True
    return bool(
        re.search(
            r"^(怎样|为什么|落在哪里|回到|结尾|开头|中段|包装|标题|导语|主线是|重点是|核心是|不要收成|不要写成|写成|写我们|写人|写一个人|先写|再写|最后(?:回到|把|还是))",
            prefix,
        )
    )


def _resolve_local_fallback_point(raw_text: str, *, default: str) -> str:
    cleaned = _clean_local_fallback_instruction_phrase(raw_text)
    if (
        not cleaned
        or _looks_like_local_fallback_instruction_fragment(cleaned)
        or _looks_like_local_fallback_strategy_scaffold(cleaned)
    ):
        return default
    return cleaned


def _resolve_local_responsibility_ending(text: str) -> str:
    cleaned = _clean_local_fallback_instruction_phrase(text)
    if cleaned and not _looks_like_local_fallback_instruction_fragment(cleaned):
        if any(token in cleaned for token in ("安稳", "等你", "没有白熬", "灯", "分担", "托稳")):
            return "灯还亮着，饭还热着，有人愿意和你一起想办法，日子就有了继续往前的底气。"
        return _ensure_sentence_end(cleaned)
    return "灯还亮着，饭还热着，有人愿意和你一起想办法，日子就有了继续往前的底气。"


def _normalize_local_responsibility_cost_point(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if any(
        token in normalized
        for token in (
            "被透支的是睡眠",
            "睡眠、耐心",
            "身体和自我感受",
            "自我感受",
            "长期压缩",
            "变得麻木",
            "不是突然崩",
            "突然崩",
            "睡眠、情绪",
            "判断力",
            "透支",
            "快没油的灯",
        )
    ):
        return "父母少一点担心，孩子多一点底气，家里多一点踏实，这些都在告诉你，自己没有白忙"
    normalized = normalized.replace(
        "让硬撑不是抽象形容，而是日常里留下的痕迹",
        "让辛苦落成看得见的踏实",
    )
    normalized = normalized.replace(
        "睡眠变浅、委屈不说、情绪硬吞、身体先报警，这些都是硬撑留下来的痕迹",
        "父母少一点担心，孩子多一点底气，家里多一点踏实，这些都在告诉你，自己没有白忙",
    )
    normalized = normalized.replace(
        "这些都是硬撑留下来的痕迹",
        "这些都在告诉你，自己没有白忙",
    )
    return normalized


def _normalize_local_responsibility_burden_point(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if any(
        token in normalized
        for token in (
            "家庭分工",
            "经济压力",
            "长期习惯",
            "默认的承担者",
            "默认承担者",
            "角色要求",
            "情感牵引",
            "失序的恐惧",
            "家庭支持变薄",
            "养育成本",
            "照护责任",
            "结构性压力",
            "必须扛",
            "被催缴的现实",
            "资源不足",
            "时间被挤占",
            "情绪无处安放",
            "高压运转",
            "喘气都要算成本",
            "亲情、养育、收入和体面",
            "不是不想轻松",
            "停下来",
            "没有余地",
            "切入",
            "写出",
            "只顾自己",
            "先顾别人",
            "父母少一点担心",
            "孩子多一点底气",
            "家里多一点踏实",
        )
    ):
        return "父母的事要惦记，孩子的事要跟上，工作那头也不能松"
    normalized = normalized.replace("上有父母、下有孩子、工作也不敢松", "上有父母，下有孩子，工作也不敢松")
    normalized = normalized.replace("上有父母，下有孩子，工作也不敢松", "父母的事要惦记，孩子的事要跟上，工作那头也不能松")
    normalized = normalized.replace("上有父母、下有孩子，工作也不能松", "父母的事要惦记，孩子的事要跟上，工作那头也不能松")
    normalized = normalized.replace(
        "很多人慢慢学会先稳住别人，再往后放自己",
        "时间久了，你就习惯先把家里那头安顿好，再给自己留一口气",
    )
    normalized = normalized.replace(
        "责任长期落在一个人肩上，不是因为他更强，而是因为家庭、工作与关系默认他会接住，于是情绪只能往后排",
        "责任落在一个人肩上，不是因为他不需要被照顾，而是因为他心里一直装着要守护的人",
    )
    return normalized


def _resolve_local_responsibility_pressure_detail(payload: Mapping[str, object]) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if "请假" in corpus and "绩效" in corpus:
        return "你先把能协调的时间圈出来，再给家里留出一个更稳的安排。"
    if "辞职" in corpus:
        return "念头涌上来的时候，你会先停一停，想想怎样让眼前这一步走得更稳。"
    if any(token in corpus for token in ("账单", "缴费", "催款")):
        return "消息一来，你先把能调的地方调一调，让家里的灯照常亮着。"
    return "很多时候，你也想松一口气，只是更想让家里的人安心一点。"


def _resolve_local_responsibility_warmth_detail(payload: Mapping[str, object]) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if "缴费窗口" in corpus and "孩子" in corpus:
        return "后来再看，父母遇事少一点慌，孩子说话多一点底气，家里那些原本容易紧张的时刻，也慢慢多了一点余地。"
    if all(token in corpus for token in ("父母", "孩子", "伴侣")):
        return "你认真走过的那些夜，最后会变成父母少一点迟疑，孩子多一点底气，也让伴侣在风雨来的时候还有地方靠。"
    if any(token in corpus for token in ("放学", "门口等", "画纸", "扑过来")):
        return "孩子从学校门口朝你跑过来的那一下，会让你忽然觉得，这一天再难也不是白过。"
    if any(token in corpus for token in ("夜灯", "灯还亮着", "回来了", "热汤", "晚饭")):
        return "回到家那盏还亮着的灯，会把一个人从一天的奔忙里轻轻接回来。"
    if any(token in corpus for token in ("父母", "爸妈")) and "孩子" in corpus and any(
        token in corpus for token in ("电话", "来电", "路上")
    ):
        return "后来再看，爸妈再遇事时，电话那头没以前那么慌了；孩子碰上事情，也知道先稳一下再想办法了。"
    if "父母" in corpus and any(token in corpus for token in ("电话", "来电", "路上")):
        return "电话那头一句“你慢点”，就够让悬着的心往下落一点。"
    return "推门时屋里还有一盏灯亮着，这件事本身就是继续往前走的底气。"


def _resolve_local_responsibility_draft_opening(payload: Mapping[str, object]) -> str:
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    opening_by_scene = {
        "medical": "医院走廊的灯亮得很白，你先想的是怎么让家里人少一点慌。",
        "schedule": "请假申请还没点下去，你已经先把工作、父母和孩子的事排了一遍。",
        "bills": "账单摊在桌上时，你先把能调整的地方圈了出来。",
        "pickup": "站在学校门口等孩子出来时，一天的奔忙忽然有了很具体的答案。",
        "call": "电话一响，你先把手里的事停了一下。还没接起来，心里已经开始替父母、孩子和今天的安排排顺序。",
        "family": "家里临时有事时，你先想的是眼前这件事该怎么接。",
    }
    followup_by_scene = {
        "medical": "你先把缴费、复查和回家的安排理清，让家里人心里都有一个落点。",
        "schedule": "你先把工作、父母和孩子的事排一遍，想让每一头都稳一点。",
        "bills": "你先把能调整的地方圈出来，想让这个家照常往前走。",
        "pickup": "那一刻，辛苦不是一下子消失了，而是突然有了值得继续往前的光。",
        "call": "你先把声音放稳，把父母、孩子和家里的安排一件件理清。",
        "family": "你先想的是眼前这件事该怎么接，家里的心才不会跟着乱。",
    }
    intro = opening_by_scene.get(scene_kind, opening_by_scene["family"])
    return _compose_local_followup(intro, followup_by_scene.get(scene_kind, followup_by_scene["family"]))


def _resolve_local_responsibility_daily_detail(payload: Mapping[str, object]) -> str:
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    detail_by_scene = {
        "medical": "很多中年人的一天，都是从把慌张先按住开始的。先看医院那边谁去跑，先问老人还缺什么，再把孩子和工作那头的时间一起排好。",
        "schedule": "很多中年人的一天，都是从把自己往后放半步开始的。先看工作能不能协调，先想爸妈那边谁去跑，再把孩子这周的安排补上。",
        "bills": "很多中年人的一天，都是从把开销一项项摆清楚开始的。先看哪笔必须今天处理，先想哪里还能挪一点，再把家里接下来的日子往稳处排。",
        "pickup": "很多中年人的一天，都是从一件件小事里被重新点亮的。忙归忙，只要校门口有人朝你跑来，那些奔波就有了很具体的答案。",
        "call": "很多中年人的一天，都是从把自己往后放半步开始的。先想爸妈那边谁去跑，先看孩子这周怎么接，再把这个月哪笔开销得先处理过一遍。",
        "family": "很多中年人的一天，都是从把家里的顺序理清开始的。先顾哪一头，先办哪件事，先让谁心里别慌，都要在脑子里过一遍。",
    }
    return detail_by_scene.get(scene_kind, detail_by_scene["family"])


def _resolve_local_responsibility_teaser(payload: Mapping[str, object]) -> str:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    teaser_by_scene = {
        "medical": "医院走廊里，你先把家人的心安顿下来。那些一件件理清的安排，最后都会变成日子的踏实。",
        "schedule": "请假前，你先把工作、父母和孩子的事排了一遍。心里装着家的人，总会先让日子稳一点。",
        "bills": "账单摊开时，你先想的是日子怎么继续往前。那些被你一点点排稳的琐事，后来都会变成家的底气。",
        "pickup": "站在校门口等孩子出来时，一天的辛苦会忽然松一点。有人朝你奔来，日子就有了很具体的光。",
        "call": "电话一响，你先想父母那边谁陪、孩子这边谁接。这些事你都得先想在前面，家里的安稳才能被你慢慢托住。",
        "family": "你把很多事安排妥了，家里的灯才会这样稳稳亮着。",
    }
    if scene_kind in teaser_by_scene:
        return teaser_by_scene[scene_kind]
    if "请假" in corpus:
        return teaser_by_scene["schedule"]
    if any(token in corpus for token in ("账单", "缴费", "电话")):
        return teaser_by_scene["family"]
    return "有些辛苦不张扬，却一直在把家里的日子托稳。"


def _resolve_local_responsibility_publish_lead(payload: Mapping[str, object]) -> str:
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    lead_by_scene = {
        "medical": (
            "医院走廊的灯很亮，你先想的是让家人别慌。"
            "缴费、复查、回家的安排一件件理顺，心也慢慢落下来。"
        ),
        "schedule": (
            "请假申请还没点下去，你已经先把今天的事排了一遍。"
            "父母那边、孩子那边、工作那边，都想照顾妥当一点。"
        ),
        "bills": (
            "账单摊在桌上时，你先把能调的地方圈出来。"
            "日子不一定一下变轻，但家里的心会先稳一点。"
        ),
        "pickup": (
            "站在校门口等孩子出来时，一天的紧绷会松一点。"
            "有人朝你跑来，日子就突然有了很具体的亮光。"
        ),
        "call": (
            "电话一响，你先想的不是自己累不累。"
            "父母那边谁陪、孩子这边谁接，家里的安排都要一件件往前排。"
            "把顺序理清，家里的心也就稳一点。"
        ),
        "family": (
            "家里临时有事时，你先把手里的事停一下。"
            "把顺序理清，人心也就慢慢稳了。"
        ),
    }
    return lead_by_scene.get(scene_kind, lead_by_scene["family"])


def _resolve_local_responsibility_publish_abstract(payload: Mapping[str, object]) -> str:
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    abstract_by_scene = {
        "medical": "医院走廊、缴费窗口和复查安排，会让人一瞬间变得很清醒。你先把事情理顺，是为了让家人少一点慌。那些被你安顿好的细节，最后都会慢慢变成家的踏实。",
        "schedule": "请假前先把工作、父母和孩子的安排过一遍，是很多成年人很真实的一刻。你不是只会硬撑，而是心里一直装着要照顾的人。把眼前的顺序理清，日子就会多一点安稳。",
        "bills": "账单和开销摆到眼前时，人会先想着怎样让日子照常往前。你把能调的地方一点点排稳，那份细小的认真，会慢慢变成一家人的底气。",
        "pickup": "校门口那一下很小，却能把一天的辛苦轻轻接住。有人朝你奔来，有人等你回家，生活就不只是忙和累，也有值得继续往前的光。",
        "call": "嘴上那句“没事”后面的辛苦，常常藏在一通电话里。父母那边谁陪、孩子这边谁接、家里那口悬着的气，都要有人先稳住。等到家里的灯又稳稳亮着，日子照常往前，你会知道这些年真没白忙。",
        "family": "家里临时有事时，你总会先把人安顿好，再想自己。那些不张扬的认真，会在父母安心、孩子踏实和屋里那盏灯里慢慢显出意义。",
    }
    return abstract_by_scene.get(scene_kind, abstract_by_scene["family"])


def _resolve_local_responsibility_intro_options(payload: Mapping[str, object], publish_lead: str) -> list[str]:
    scene_kind = _resolve_local_responsibility_scene_kind(payload)
    options_by_scene = {
        "medical": [
            "医院走廊里，最先要稳住的往往不是事情，而是家人的心。",
            "把复查、缴费和回家的路都理清，人心就会慢慢落下来。",
        ],
        "schedule": [
            "请假前先排一遍家里的事，是很多成年人没说出口的认真。",
            "你把今天排稳，家里那头也就少一点慌。",
        ],
        "bills": [
            "账单摊开时，日子会提醒人先把眼前这一步走稳。",
            "那些被你一点点调顺的开销，最后会变成家的底气。",
        ],
        "pickup": [
            "校门口那一下奔向你的人，会把一天的累轻轻接住。",
            "日子不只是在忙，也藏着这些忽然亮起来的瞬间。",
        ],
        "call": [
            "那通电话后，你先把声音放稳，也把家里的事理清。",
            "你多想的那一步，后来都会慢慢落成安心。",
        ],
        "family": [
            "家里临时有事时，最先把顺序理清的人，也值得被好好心疼。",
            "把今天接住，后面的事才有地方慢慢排。",
        ],
    }
    return _dedupe_nonempty_text_options([publish_lead, *options_by_scene.get(scene_kind, options_by_scene["family"])])


def _resolve_local_generic_fallback_mode(payload: Mapping[str, object]) -> str:
    mode = _resolve_local_fallback_mode(payload)
    if mode in _TRACKED_ARTICLE_SELECTION_SUPPORTED_MODES:
        return mode
    return ""


def _resolve_local_fallback_mode(payload: Mapping[str, object]) -> str:
    if _has_local_trust_boundary_focus(payload):
        return "trust_boundary"
    title = str(
        payload.get("article_title")
        or payload.get("topic_title")
        or payload.get("project_title")
        or payload.get("reference_article_title")
        or ""
    ).strip()
    corpus = _extract_local_fallback_corpus(payload)
    if _payload_looks_like_scene_first_progression(payload):
        return "scene_first_progression"
    if (
        _uses_local_emotional_memory_presence_variant(payload)
        or _uses_local_emotional_memory_reflux_variant(payload)
        or _uses_local_emotional_endings_acceptance_variant(payload)
        or _uses_local_emotional_regret_forward_variant(payload)
        or _uses_local_emotional_forgiveness_release_variant(payload)
    ):
        return "emotional_engine_direct"
    if _has_local_pressure_interface_direct_focus(payload):
        return "pressure_interface_direct"
    if _should_use_local_responsibility_shelter_fallback(payload):
        return "responsibility_shelter"
    if _uses_local_self_reliance_shared_burden_variant(payload):
        return "self_reliance_inward_support"
    mode = _resolve_tracked_article_expected_selection_mode(payload)
    if mode:
        return mode
    candidate_mode = _resolve_tracked_article_candidate_mode(title=title, markdown=corpus)
    if candidate_mode:
        return candidate_mode
    if any(
        token in f"{title} {corpus}"
        for token in ("韧性", "重新长出力量", "最难走的路", "筋骨", "被生活按回去", "重新起身")
    ):
        return "resilience_reconstruction"
    emotional_text = f"{title} {str(payload.get('topic_angle') or '').strip()} {corpus}"
    emotional_hits = sum(
        1
        for token in (
            "感谢相遇",
            "不谈亏欠",
            "允许一切结束",
            "接纳离开",
            "关系结束",
            "走到最后",
            "没走到最后",
            "走散",
            "停在半路",
            "白忙一场",
            "白走",
            "看人的眼光",
            "爱人的分寸",
            "认真爱人",
            "回到自己生活",
            "白费",
            "告别",
            "离开",
            "回忆",
            "遗憾",
            "释怀",
            "放下",
            "过去",
        )
        if token in emotional_text
    )
    if emotional_hits >= 2:
        return "emotional_engine_direct"
    if any(
        token in corpus
        for token in (
            "把自己养贵",
            "把自己看重一点",
            "身价",
            "门槛",
            "标准收紧",
            "边界",
            "打折品",
            "奢侈品",
            "配得上",
            "将就",
            "都可以",
            "把自己放轻",
            "把自己放低",
            "往后让",
            "体面",
            "分寸",
            "把自己放回前面",
        )
    ):
        return "self_worth_rebuild"
    if any(
        token in f"{title} {corpus}"
        for token in (
            "信任",
            "谎言",
            "隐瞒",
            "坦诚",
            "说到做到",
            "赤诚",
            "出轨",
            "背叛",
            "不查手机",
            "不追问行踪",
        )
    ):
        return "trust_boundary"
    if _has_local_trust_boundary_focus({"source_type": "tracked_article", "article_title": title, "body_markdown": corpus}):
        return "trust_boundary"
    everyday_text = f"{title} {corpus}"
    everyday_hits = sum(
        1
        for token in (
            "热饭",
            "一盏灯",
            "灯还亮着",
            "饭桌",
            "饭香",
            "厨房",
            "吃饭",
            "回家",
            "知己",
            "家人平安",
            "有家可回",
            "有人可爱",
            "有人惦记",
            "人间烟火",
            "平安健康",
            "简单日子",
            "好日子",
            "烟火",
        )
        if token in everyday_text
    )
    if everyday_hits >= 2 or any(token in everyday_text for token in ("知己二三", "家人安康", "四季平安", "一顿热饭")):
        return "everyday_warmth_return"
    if _uses_local_response_priority_time_priority_variant(payload):
        return "response_priority"
    if any(
        token in f"{title} {corpus}"
        for token in (
            "没时间",
            "时间在哪儿",
            "时间分配",
            "碎片时间",
            "回应顺序",
            "回应优先级",
            "排在前面",
            "放在心上",
            "被看见",
            "评论",
            "点赞",
            "追问",
            "补问",
            "言外之意",
            "读懂",
            "轻互动",
            "回消息",
            "回一条消息",
        )
    ):
        return "response_priority"
    if any(
        token in f"{title} {corpus}"
        for token in ("心安", "此心安处", "内心安顿", "内在归处", "与内心和解", "心放平", "把心抚平", "心若不安", "心若不定")
    ):
        return "inner_settlement"
    if any(
        token in corpus
        for token in (
            "自救自渡",
            "向内求",
            "自己安顿",
            "求助",
            "帮扶",
            "先把眼前这一步走稳",
            "悬着",
            "把自己托住",
            "扛事久了",
            "把自己接回来",
            "散掉的力气",
            "四周都腾不出空",
            "先让自己缓下来",
            "先把今晚过稳",
            "先给自己点一盏灯",
        )
    ):
        return "self_reliance_inward_support"
    supportive_text = f"{title} {corpus}"
    if any(
        token in supportive_text
        for token in (
            "心软",
            "好说话",
            "包容",
            "体谅",
            "原谅",
            "一生难遇",
            "牵紧他的手",
            "场面放软",
            "先顾别人感受",
            "别人感受放在前面",
            "把语气放软",
            "把语气放轻",
            "值得被珍惜",
            "好好珍惜",
            "被好好接住",
            "留余地",
            "理所当然",
        )
    ):
        return "supportive_appreciation"
    if any(
        token in corpus
        for token in ("吵架", "争吵", "冷暴力", "妥协", "不理不睬", "达成共识", "回归理性")
    ):
        return "relationship_aftercare"
    if any(
        token in corpus
        for token in ("评论", "点赞", "追问", "补问", "言外之意", "读懂", "我没事", "有点累", "轻互动")
    ):
        return "response_priority"
    if _has_broad_emotional_release_focus(
        {
            "source_type": "tracked_article",
            "article_title": title,
            "body_markdown": corpus,
            "summary": corpus,
            "topic_angle": str(payload.get("topic_angle") or "").strip(),
        }
    ):
        return "emotional_engine_direct"
    return ""


def _looks_like_stale_local_mode_opening(mode: str, text: str) -> bool:
    normalized = text.strip().rstrip("。！？!?；;")
    if not normalized:
        return False
    if mode == "self_worth_rebuild":
        return "一句“都可以”" in normalized and "自己其实已经不舒服" in normalized
    if mode == "self_reliance_inward_support":
        stale_self_reliance_markers = (
            "外面的帮扶一时赶不上",
            "没人能立刻搭把手",
            "没有人能随时赶来",
            "四周都腾不出空",
            "每个人都在各自扛事",
            "每个人手里都压着自己的事",
            "想找人倾诉",
            "先把自己从慌里带出来",
            "即使没有帮助",
            "孤立无援",
        )
        return any(marker in normalized for marker in stale_self_reliance_markers)
    if mode == "inner_settlement":
        return "心明明还悬着" in normalized and "普通安排慢慢接回今天" in normalized
    if mode == "trust_boundary":
        return "一句谎话" in normalized and "原本放心的关系" in normalized
    if mode == "pressure_interface_direct":
        stale_pressure_markers = (
            "那口一直绷着的气",
            "先把那口气松下来",
            "身体和情绪已经先替人扛不住",
            "身体和情绪会怎样慢慢替你记账",
            "真正先开始吃力的",
            "心里那套一直紧绷的运转",
        )
        return any(marker in normalized for marker in stale_pressure_markers)
    return False
def _resolve_local_generic_opening(
    *,
    payload: Mapping[str, object],
    mode: str,
    hook: str,
    theme_axis: str,
    core_conflict: str,
) -> str:
    strategy_card = payload.get("strategy_card")
    candidates: list[str] = [str(hook or "").strip()]
    if isinstance(strategy_card, Mapping):
        candidates.extend(
            [
                str(strategy_card.get("hook_trigger") or "").strip(),
                str(strategy_card.get("packaging_hook") or "").strip(),
            ]
        )
    candidates.extend(
        [
            str(payload.get("analysis_hook_trigger") or "").strip(),
            str(payload.get("reference_article_analysis_hook_trigger") or "").strip(),
        ]
    )
    title_like = {
        str(payload.get("topic_title") or "").strip(),
        str(payload.get("project_title") or "").strip(),
        str(payload.get("article_title") or "").strip(),
        str(payload.get("reference_article_title") or "").strip(),
        str(payload.get("topic_angle") or "").strip(),
        str(theme_axis or "").strip(),
        str(core_conflict or "").strip(),
    }
    mode_reference_opening = _resolve_local_mode_reference_opening(payload, mode)
    for raw in candidates:
        cleaned = _clean_local_fallback_instruction_phrase(raw)
        if not cleaned or cleaned in title_like:
            continue
        if _looks_like_local_fallback_instruction_fragment(cleaned):
            continue
        if _looks_like_local_fallback_strategy_scaffold(cleaned):
            continue
        if _looks_like_packaging_instruction_leakage(cleaned):
            continue
        if mode == "everyday_warmth_return" and any(
            token in cleaned for token in ("更大的目标突然失重", "小日常重新有了分量", "幸福误认成更大目标")
        ):
            continue
        if _looks_like_stale_local_mode_opening(mode, cleaned):
            continue
        if extract_generic_reflective_openers(cleaned):
            continue
        if mode == "response_priority" and mode_reference_opening and any(
            token in cleaned for token in ("轻描淡写的话", "多问一句", "被听懂")
        ):
            continue
        if mode == "response_priority" and mode_reference_opening and re.search(r"不是[^，。；\n]{1,20}[，,、]?\s*而?是", cleaned):
            continue
        if mode == "inner_settlement" and mode_reference_opening and any(
            token in cleaned for token in ("屋里安静下来以后", "一直没落地的事", "原来比外面更吵")
        ):
            continue
        if mode == "self_worth_rebuild" and mode_reference_opening and any(
            token in cleaned for token in ("都可以", "真实想法", "先出了口")
        ):
            continue
        if mode == "supportive_appreciation" and mode_reference_opening and any(
            token in cleaned for token in ("顺手让了一步", "先顾了别人感受", "场面放软")
        ):
            continue
        if mode == "emotional_engine_direct" and mode_reference_opening and any(
            token in cleaned for token in ("后来你才明白", "真正难熬的", "分开的那天")
        ):
            continue
        return _ensure_sentence_end(cleaned)
    if mode_reference_opening:
        return _ensure_sentence_end(mode_reference_opening)
    resilience_opening = (
        "训练没做完的那天，她坐在泳池边缓了一会儿；第二天，还是重新下了水。"
        if _has_local_resilience_pool_profile(payload)
        else "训练没做完的那天，你坐在原地缓了一会儿；第二天，还是重新站回了起点。"
    )
    mode_openings = {
        "everyday_warmth_return": "有些晚上，推开家门闻到饭香，人才忽然不想再和谁比较了。",
        "inner_settlement": "忙完一天回到家，把鞋摆好，给自己倒杯水；没有答案也没关系，心先有地方安静下来。",
        "self_reliance_inward_support": "把桌上的几件事重新排一遍，你先挑最能做的那件落下去；人稳住了，日子就有了下一步。",
        "self_worth_rebuild": "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。",
        "supportive_appreciation": "饭桌上她先问一句“还吃吗？”，像什么都没发生；可她把那口气咽下去的样子，只有熟悉她的人看得见。",
        "relationship_aftercare": "门关上以后，屋里安静了几分钟；他去厨房倒了杯水，回来时没有继续争输赢，只问你刚才是不是难受。",
        "trust_boundary": "听见前后两个版本时，手里的筷子会先停一下。",
        "response_priority": "晚霞照片发出去以后，点赞很快就铺满屏幕；真正让你停下来的，是有人问你今天是不是很累。",
        "resilience_reconstruction": resilience_opening,
        "emotional_engine_direct": "路过那家旧店时，你脚步慢了一下，才发现有些告别并不会在当天结束。",
        "scene_first_progression": "那句话停在嘴边的时候，关系其实已经轻轻往后退了一步。",
        "pressure_interface_direct": "复查提醒弹出来的时候，手指先停一下。那张被改过几次的预约，终于又被你圈回日历上。",
    }
    default = mode_openings.get(mode)
    if default:
        return default
    for raw in (core_conflict, theme_axis):
        cleaned = _resolve_local_fallback_point(raw, default="")
        if cleaned:
            return _ensure_sentence_end(cleaned)
    return "很多事走到后来，才会慢慢看清真正重要的地方。"

def _resolve_local_generic_outline_hook(
    *,
    payload: Mapping[str, object],
    mode: str,
    topic_title: str,
    topic_angle: str,
    theme_axis: str,
    core_conflict: str,
) -> str:
    strategy_card = payload.get("strategy_card")
    candidates: list[str] = []
    if mode == "scene_first_progression":
        scene_hook = _resolve_local_scene_first_hook(payload, topic_angle=topic_angle)
        if scene_hook:
            return scene_hook
    if isinstance(strategy_card, Mapping):
        candidates.extend(
            [
                str(strategy_card.get("hook_trigger") or "").strip(),
                str(strategy_card.get("packaging_hook") or "").strip(),
            ]
        )
    candidates.extend(
        [
            str(payload.get("analysis_hook_trigger") or "").strip(),
            str(payload.get("reference_article_analysis_hook_trigger") or "").strip(),
            topic_title,
            topic_angle,
            core_conflict,
            theme_axis,
        ]
    )
    title_like = {
        _clean_local_fallback_instruction_phrase(value)
        for value in (topic_title, topic_angle, core_conflict, theme_axis)
        if str(value or "").strip()
    }
    for raw in candidates:
        cleaned = _clean_local_fallback_instruction_phrase(raw)
        if not cleaned:
            continue
        if cleaned in title_like:
            continue
        if _looks_like_local_fallback_instruction_fragment(cleaned):
            continue
        if _looks_like_local_fallback_strategy_scaffold(cleaned):
            continue
        if _looks_like_packaging_instruction_leakage(cleaned):
            continue
        if mode == "everyday_warmth_return" and any(
            token in cleaned for token in ("更大的目标突然失重", "小日常重新有了分量", "幸福误认成更大目标")
        ):
            continue
        if _looks_like_stale_local_mode_opening(mode, cleaned):
            continue
        if extract_generic_reflective_openers(cleaned):
            continue
        return _ensure_sentence_end(cleaned)
    return _resolve_local_generic_opening(
        payload=payload,
        mode=mode,
        hook="",
        theme_axis=theme_axis,
        core_conflict=core_conflict,
    )


_LOCAL_MODE_OUTLINE_DEFAULTS: dict[str, tuple[str, str, str, str]] = {
    "everyday_warmth_return": (
        "人走到后来才会发现，最让人惦记的常常是饭桌上还有人给你留位置",
        "一路追着更大的目标往前跑，日子反而容易把眼前的饭香、电话和笑声放轻",
        "眼前的日常一旦被放轻，人就算站在热闹里，心里也还是不踏实",
        "等你肯把脚步放慢，重新看见这些细小照应，生活的甜意也会慢慢回来",
    ),
    "inner_settlement": (
        "屋里安静下来以后，人才会听见，心里那点一直没落地的事，原来比外面更吵",
        "越急着一口气把所有答案想通，越容易把自己困在反复里",
        "心一直悬着，饭会凉得快，觉也睡不实，连普通一天都像没落地",
        "先把今天过回今天，把眼前的小事照顾好，心才会慢慢安稳下来",
    ),
    "self_reliance_inward_support": (
        "你想找人商量，也知道别人手里可能正压着自己的事",
        "先把慌乱放低，把眼前能做的事处理好",
        "你还愿意照顾自己、处理手边事，也知道什么时候请别人一起分担",
        "你可以求助，也可以先自救；两件事都不丢人",
    ),
    "self_worth_rebuild": (
        "很多人一开始并不是没脾气，只是太怕冲突，也太怕把关系弄僵，所以总习惯先说“都可以”",
        "你总替别人圆场、替关系找补，时间久了，别人也会顺着这个习惯，把你的退让当成应该的",
        "边界一退再退、委屈一忍再忍，最后最先被放轻的，往往就是你自己",
        "等你肯把那点别扭当回事，分寸、体面和尊重，才会一点点回到你这边",
    ),
    "trust_boundary": (
        "从前你愿意相信，是因为对方给过你不用设防的心安",
        "让人心里发沉的，常常是那一句话后来才发现没有说真",
        "信任一旦裂开，人就会开始反复确认、反复猜，也开始怀疑自己当初是不是太轻易交出了心",
        "一段关系要走得长久，坦诚、交代和说到做到，都要在日常里慢慢兑现",
    ),
    "response_priority": (
        "同样一条消息发出去，有人看过就算了，也有人会停下来再问你一句是不是还没说完",
        "真正把你放在前面的人，不一定时时都在线，但会留神你的语气，也会记得把那句没回完的话接回来",
        "总替对方解释忙、累、没看见，心里的失落就会一点点往下压",
        "把时间和真心留给那些愿意认真回应你的人，关系里的踏实感才会慢慢长出来",
    ),
    "supportive_appreciation": (
        "有些人每次都会先把场面放软，不想让在乎的人太难堪",
        "可越是总替别人留余地的人，越容易被人误会成不会计较，连那份退让也会被看轻",
        "等到委屈一层层攒下来，最先难受的，往往也是那个总在替别人留余地的人",
        "能看懂这份柔软，还舍得认真回应的人，才配把这颗心稳稳接过去",
    ),
    "relationship_aftercare": (
        "有些架明明已经停了，可屋里安静下来以后，那股别扭还一直挂着",
        "如果每次都是同一个人先回来缓和、先开口善后，心就会一点点凉下来",
        "表面上像是翻篇了，不代表心里那一下也跟着翻过去了，很多距离就是从这里慢慢出来的",
        "肯回来把话说完、把情绪接住的人，才是真的想把关系继续往前走",
    ),
    "resilience_reconstruction": (
        "真正的韧性，不是嘴上说不怕，而是被生活按回去很多次以后，还肯一次次把自己接起来",
        "很多看起来很轻松的重新出发，背后都藏着别人看不见的疼、反复和咬牙",
        "那些日复一日的坚持，不会立刻把命运改写，却会先把一个人的筋骨慢慢立住",
        "等你熬过那段最难的路，再回头看，会发现自己早已不是当初那个只会被动承受的人",
    ),
    "emotional_engine_direct": (
        "很多人迟迟走不出来，不是因为那段相遇全错了，而是总想替它要一个圆满收场",
        "可有些关系走到这里，并不代表那些陪伴、眼界和改变就跟着一起作废了",
        "一直把自己留在回忆里打转，今天的生活就很难真的轻下来",
        "等你肯把那段路收进心里，再把今天的饭吃热、灯关好，人就会慢慢回到自己的生活里",
    ),
    "scene_first_progression": (
        "很多关系的变化，都不是从大事开始的，而是从一句话停在嘴边、一点委屈没有说出来开始的",
        "当下那一秒也许只是想算了，可往后拖着拖着，误会、失望和距离就都跟着长出来了",
        "话不说破的时候，人表面上还在往前走，心却已经慢慢退后了",
        "等你愿意把真话说出来，很多原本拧着的关系，才有机会重新转回去",
    ),
    "pressure_interface_direct": (
        "复查提醒、饭点和休息时间一次次被往后挪时，生活已经在提醒你该把自己排回日程里",
        "真正需要调回来的，不是一句漂亮大道理，而是体检照约、饭按时吃、该停的时候肯停一停",
        "人把自己的那一步放回前面，判断会更清楚，照顾别人也会更稳",
        "从今天先调回一个小接口，日子就会一点点恢复顺序",
    ),
}


def _resolve_local_mode_outline_defaults(mode: str) -> tuple[str, str, str, str]:
    return _LOCAL_MODE_OUTLINE_DEFAULTS.get(
        mode,
        (
            "很多事刚发生时都不算大，真正让人过不去的，往往是那一下心里先沉了沉",
            "人会一步步走到这里，常常不是因为一件事，而是一些细节反复堆到了一起",
            "那些没被说出口的委屈和代价，最后都会落进日常里",
            "等你把这件事看清一点、也把自己往回接一点，很多原本拧着的地方才会慢慢松开",
        ),
    )


def _resolve_local_generic_outline_points(
    *,
    payload: Mapping[str, object],
    mode: str,
    topic_angle: str,
    theme_axis: str,
    core_conflict: str,
    positive_direction: str,
) -> tuple[str, str, str, str]:
    reference_corpus = _extract_local_reference_corpus(payload)
    defaults = _resolve_local_mode_outline_defaults(mode)
    if mode == "scene_first_progression":
        scene_points = _resolve_local_scene_first_outline_points(
            payload,
            positive_direction=positive_direction,
            default_closing=defaults[3],
        )
        if scene_points:
            return scene_points
    point_one = _resolve_local_fallback_point(topic_angle, default=defaults[0])
    point_two = _resolve_local_fallback_point(core_conflict, default=defaults[1])
    point_three = _resolve_local_fallback_point(theme_axis, default=defaults[2])
    point_four = defaults[3]
    if mode in _LOCAL_MODE_OUTLINE_DEFAULTS:
        point_three = defaults[2]
    if mode == "self_worth_rebuild":
        point_two = defaults[1]
        point_three = defaults[2]
    if mode == "supportive_appreciation":
        point_two = defaults[1]
        point_three = defaults[2]
    if mode == "relationship_aftercare":
        point_two = defaults[1]
    if mode == "self_worth_rebuild" and any(
        token in reference_corpus for token in ("打折品", "奢侈品", "贱卖", "廉价")
    ):
        point_one = "那句“都可以”说得太顺口时，边界就会悄悄往后退"
    cleaned_positive = _clean_local_fallback_instruction_phrase(positive_direction)
    if cleaned_positive and not _looks_like_local_fallback_instruction_fragment(cleaned_positive):
        point_four = cleaned_positive
    return point_one, point_two, point_three, point_four


def _resolve_local_generic_mode_bridge(mode: str) -> str:
    mapping = {
        "everyday_warmth_return": "日子过得越久，越知道热闹不一定把人安顿好。能让心落下来的，常常是一口热饭、一通报平安的电话。",
        "inner_settlement": "那股非要今晚想明白的劲一松，心才有地方落下来。",
        "self_worth_rebuild": "很多委屈都不是大事砸下来的。更多时候，是你一次次先说算了，先把自己往后挪半步。",
        "relationship_aftercare": "有些关系最磨人的，不是吵起来的那一刻。是吵完以后，屋里忽然冷下来的那几小时。",
        "resilience_reconstruction": "人真正重新站起来的时候，常常没有掌声。只是某一天又把该做的训练做完，把该走的路走下去。",
        "emotional_engine_direct": "有些告别不是当场就痛完了。它常常隔很久，才在某个普通傍晚，让你承认这段路真的走完了。",
        "scene_first_progression": "很多距离，都是从一句话停在嘴边开始的。当时看着只是算了，后来才知道，那一下其实已经往后退了半步。",
        "pressure_interface_direct": "很多失序不是一下子发生的。它常常从一次改约、一次晚饭推迟、一次提醒被划掉开始。",
    }
    return mapping.get(mode, "很多事真正落到日子里，才会看清它的分量。")


def _resolve_local_generic_mode_reframe(mode: str) -> str:
    mapping = {
        "everyday_warmth_return": "能把平凡日子过热乎，本身就是一种本事。",
        "inner_settlement": "心安可以很小：把水烧开，把灯关好，把今天先过完。",
        "self_worth_rebuild": "把真实想法说出来，不是在计较，是把自己重新放回这段关系里。",
        "relationship_aftercare": "两个人都没再吵，可屋里比刚才更冷。",
        "resilience_reconstruction": "真正的韧性不是一直不痛，而是痛过以后还肯重新生长。",
        "emotional_engine_direct": "往前走，不是把过去赶出去，而是终于肯把那段经历放回它该在的位置。",
        "scene_first_progression": "有些话早点说出口，关系就不会在沉默里绕那么远的路。",
        "pressure_interface_direct": "照顾自己这件事，落到日子里，就是把饭点、检查和休息重新放回该在的位置。",
    }
    return mapping.get(mode, "换一个角度看，事情也许就没有那么拧了。")


def _resolve_local_generic_mode_consequence(mode: str) -> str:
    mapping = {
        "everyday_warmth_return": "有人记得你爱吃什么，有人问一句到哪了，有朋友愿意听你把话说完，这些小事凑在一起，心就会稳下来。",
        "inner_settlement": "能把饭吃完，能安稳睡一觉，心就已经在慢慢回到今天。",
        "self_worth_rebuild": "你把自己看重一点，关系里的轻重，才会慢慢回到该有的位置。",
        "relationship_aftercare": "一次两次还能劝自己算了，先睡吧。次数多了，人先学会的，往往就是把期待收小。",
        "resilience_reconstruction": "那些被生活按下去又重新起身的日子，会把人的筋骨一点点养出来。",
        "emotional_engine_direct": "那段路安放好了，今天的日子才不会总被昨天拽回去。",
        "scene_first_progression": "等真话被好好说出来，很多悬着的误会，才有机会落回地面。",
        "pressure_interface_direct": "复查约回日历，那顿饭也认真吃完以后，人会一点点回到自己手里。",
    }
    return mapping.get(mode, "等你把这件事看清一点，心里就会慢慢有路。")


def _resolve_local_generic_mode_closing(mode: str) -> str:
    mapping = {
        "everyday_warmth_return": "今晚就把饭吃热一点，把话说慢一点。桌边的人还在，电话那头的人还肯惦记你，日子就有了踏实的回声。",
        "inner_settlement": "先把今天过回今天，放不下的事，日子会慢慢替你松一松。",
        "self_worth_rebuild": "下次那句“都可以”到嘴边时，先停一下。别再让委屈替你懂事收尾。",
        "relationship_aftercare": "心里有这段关系的人，不会让你独自站在那阵冷气里。他会回来，把话说完，把情绪接住，也把那份失望一点点接回去。",
        "resilience_reconstruction": "被生活打磨过以后，人身上的光不是喊出来的。它藏在第二天还肯站回起点的那一步里。",
        "emotional_engine_direct": "把那些好收好，也把那些疼放回过去。今晚先把这一页合上，明天再认真去过新的日子。",
        "scene_first_progression": "下一次遇到重要的人和事，先把真话留在当场。话说得早一点，自己也会站得稳一点。",
        "pressure_interface_direct": "先把今天这一个提醒接住。人回稳了，后面的安排才不会总靠硬扛往前推。",
    }
    return mapping.get(mode, "先把眼前的日子慢慢过顺，也把自己好好带回今天。")


def _build_local_response_priority_followup_corpus(payload: Mapping[str, object]) -> str:
    parts = [_extract_local_fallback_corpus(payload)]
    for key in ("cover_copy", "social_teaser", "recommended_title"):
        value = str(payload.get(key) or "").strip()
        if value:
            parts.append(value)
    title_options = payload.get("title_options")
    if isinstance(title_options, list):
        parts.extend(str(item or "").strip() for item in title_options if str(item or "").strip())
    social_teaser_options = payload.get("social_teaser_options")
    if isinstance(social_teaser_options, list):
        parts.extend(str(item or "").strip() for item in social_teaser_options if str(item or "").strip())
    outline = payload.get("outline")
    if isinstance(outline, Mapping):
        parts.extend(
            [
                str(outline.get("hook") or "").strip(),
                str(outline.get("outline_body") or "").strip(),
            ]
        )
    return " ".join(part for part in parts if part)

def _uses_local_response_priority_followup_variant(payload: Mapping[str, object]) -> bool:
    corpus = _build_local_response_priority_followup_corpus(payload)
    if not corpus:
        return False

    followup_hits = sum(
        1
        for keyword in (
            "评论的人",
            "给你评论",
            "多问一句",
            "追问",
            "愿意停下来",
            "言外之意",
            "读懂",
            "没说完",
            "接住",
            "注意力分给你",
            "我没事",
            "我有点累",
            "飞得累不累",
        )
        if keyword in corpus
    )
    interaction_hits = sum(
        1 for keyword in ("评论", "追问", "多问一句", "读懂", "没说完", "停下来", "我没事", "我有点累", "注意力")
        if keyword in corpus
    )
    care_hits = sum(1 for keyword in ("在意", "在乎", "关心", "理解", "珍惜") if keyword in corpus)
    classic_hits = sum(
        1
        for keyword in (
            "没时间",
            "很忙",
            "红灯30秒",
            "等红绿灯",
            "24小时在线",
            "优先",
            "优先级",
            "顺序",
            "时间在哪儿",
            "心就在哪儿",
            "不够重要",
            "忙不是借口",
            "没时间也不是理由",
        )
        if keyword in corpus
    )
    return followup_hits >= 3 and interaction_hits >= 4 and care_hits >= 1 and (followup_hits + interaction_hits) >= classic_hits + 2


def _uses_local_response_priority_time_priority_variant(payload: Mapping[str, object]) -> bool:
    corpus = _build_local_response_priority_followup_corpus(payload)
    if not corpus:
        return False

    classic_hits = sum(
        1
        for keyword in (
            "没时间",
            "很忙",
            "红灯30秒",
            "红灯的三十秒",
            "等红绿灯",
            "碎片时间",
            "24小时在线",
            "优先",
            "优先级",
            "回应顺序",
            "回应优先级",
            "顺序",
            "时间在哪儿",
            "时间留给谁",
            "心就在哪儿",
            "放在心上",
            "被看见",
            "不够重要",
            "忙不是借口",
            "没时间也不是理由",
            "回一条消息",
            "回一句",
            "右手吃饭",
            "左手给你回信息",
            "盯着手机屏幕",
            "快速给你发语音",
            "回应补回来",
            "很忙那一刻",
        )
        if keyword in corpus
    )
    followup_hits = sum(
        1
        for keyword in ("评论", "追问", "多问一句", "读懂", "没说完", "停下来", "我没事", "我有点累", "注意力")
        if keyword in corpus
    )
    return classic_hits >= 3 and classic_hits >= followup_hits


def _has_local_self_worth_luxury_profile(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    luxury_hits = sum(
        1
        for token in ("打折品", "奢侈品", "身价", "门槛", "标准收紧", "配得上", "把自己养贵", "贱卖")
        if token in corpus
    )
    return luxury_hits >= 2


def _uses_local_everyday_warmth_small_things_variant(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if not corpus:
        return False
    anchor_hits = sum(
        1
        for token in (
            "做大事",
            "大事",
            "不起眼的小事",
            "很小的事",
            "祛魅",
            "人间烟火",
            "陪在爱的人身边",
            "灯火辉煌",
            "接孩子放学",
            "牵着她的手",
            "晒太阳",
            "饭香",
        )
        if token in corpus
    )
    return anchor_hits >= 2


def _uses_local_everyday_warmth_small_things_priority(payload: Mapping[str, object]) -> bool:
    topic_parts = [
        str(payload.get(key) or "").strip()
        for key in ("topic_title", "topic_angle", "title", "draft_title", "recommended_title", "project_title")
    ]
    topic_corpus = " ".join(part for part in topic_parts if part)
    if not topic_corpus:
        return False
    priority_hits = sum(
        1
        for token in ("做大事", "大事", "不起眼的小事", "这些小事", "小事", "祛魅", "成就叙事", "宏大叙事")
        if token in topic_corpus
    )
    return priority_hits >= 1 and _uses_local_everyday_warmth_small_things_variant(payload)


def _uses_local_everyday_warmth_simple_happiness_variant(payload: Mapping[str, object]) -> bool:
    corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
    if not corpus:
        return False
    strong_anchor_hits = sum(
        1
        for token in (
            "大富大贵",
            "简单快乐",
            "知己二三",
            "有家人有知己",
            "知己仍在",
            "知己还在",
            "家人安康",
            "一家温暖",
            "四季平安",
            "高朋满座",
            "香车美宅",
        )
        if token in corpus
    )
    support_hits = sum(
        1
        for token in ("家人平安", "家里人平安", "有家可回", "有人可爱", "一日三餐", "平淡日子")
        if token in corpus
    )
    return strong_anchor_hits >= 2 or (strong_anchor_hits >= 1 and support_hits >= 1)


def _uses_local_self_reliance_shared_burden_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    strong_hits = sum(
        1
        for token in (
            "没人能立刻搭把手",
            "搭把手",
            "负重前行",
            "朋友也愁眉不展",
            "焦头烂额",
            "风雨中蹒跚摇晃",
            "自己熬过寒冬",
            "自救自渡",
            "向内求",
            "只有靠自己",
            "各自扛事",
            "每个人手里都压着自己的事",
            "手里都压着自己的事",
            "消息框开了又关",
            "先把今天过完",
            "大家都被生活拽着",
            "没人腾得出手",
            "判断还在",
            "行动还在",
            "请别人一起分担",
            "把选择重新拿回来",
            "帮助在该出现的时候进得来",
        )
        if token in corpus
    )
    support_hits = sum(
        1
        for token in (
            "不再向别人哭诉",
            "不再向别人索求",
            "默默承受",
            "默默向内求",
            "咽下生活的苦",
            "大家都在",
            "束手无策",
            "最累最难的时候",
            "各自承压",
            "腾得出手",
            "外面的善意会有",
        )
        if token in corpus
    )
    return strong_hits >= 2 or (strong_hits >= 1 and support_hits >= 2)


def _uses_local_inner_settlement_bedtime_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    anchor_hits = sum(
        1
        for token in (
            "今夜",
            "晚安",
            "把心放平",
            "把事看淡",
            "已经过去的事",
            "还没发生的事",
            "不念过往",
            "不畏将来",
            "静待花开",
        )
        if token in corpus
    )
    return anchor_hits >= 2


def _uses_local_inner_settlement_stage_restart_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    anchor_hits = sum(1 for token in _INNER_SETTLEMENT_STAGE_RESTART_TOKENS if token in corpus)
    stage_hits = sum(1 for token in ("阶段", "节点", "清单", "目标", "计划", "年初", "半年", "下半年") if token in corpus)
    return anchor_hits >= 2 or (anchor_hits >= 1 and stage_hits >= 2)


def _uses_local_inner_settlement_homecoming_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    anchor_hits = sum(
        1
        for token in (
            "此心安处",
            "吾乡",
            "心有归处",
            "心无挂碍",
            "真正的归宿",
            "找到真正的归宿",
            "淡定与从容",
            "与内心和解",
            "和自己和解",
            "内在的心安",
            "内心的淡定与从容",
            "内心的显化",
            "能落脚的地方",
            "心里有了归处",
        )
        if token in corpus
    )
    support_hits = sum(
        1
        for token in (
            "心若不安",
            "心若不定",
            "安顿好自己的心",
            "向阳而生",
            "澄明",
            "自在独行",
            "来去随风",
            "把心抚平",
            "把心看透",
            "内在的枷锁",
            "把重心一点点收回自己身上",
            "不再把自己交给外面的起伏",
            "把那颗总往外追的心轻轻带回来",
        )
        if token in corpus
    )
    return anchor_hits >= 2 or (anchor_hits >= 1 and support_hits >= 2)


def _uses_local_emotional_memory_reflux_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    strong_hits = sum(
        1
        for token in (
            "要是他还在",
            "他还在就好了",
            "背影",
            "擦肩",
            "旧相册",
            "聊天记录",
            "旧关系",
            "回潮",
            "普通时刻",
            "往事会自行爬上来",
            "碰不到摸不着",
            "未能圆满",
            "遗忘再长",
        )
        if token in corpus
    )
    support_hits = sum(
        1
        for token in (
            "灯火阑珊",
            "久久伫立",
            "心绪翻涌",
            "低眉叹息",
            "没说完的话",
            "没兑现的承诺",
            "没被接住",
            "收藏",
            "眷恋难忘",
            "明天和以后",
        )
        if token in corpus
    )
    return strong_hits >= 2 or (strong_hits >= 1 and support_hits >= 2)


def _uses_local_emotional_memory_presence_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    strong_hits = sum(
        1
        for token in (
            "要是他还在",
            "他还在就好了",
            "碰不到摸不着",
            "随处可见",
            "依然存在于你的世界里",
            "明明这段相遇很短暂",
        )
        if token in corpus
    )
    scene_hits = sum(
        1
        for token in (
            "背影",
            "擦肩",
            "街头",
            "灯火阑珊",
            "久久伫立",
            "心绪翻涌",
            "低眉叹息",
            "那年那天那一刻",
            "随处可见",
            "存在于你的世界里",
        )
        if token in corpus
    )
    return strong_hits >= 2 or (strong_hits >= 1 and scene_hits >= 1) or scene_hits >= 3


def _uses_local_emotional_endings_acceptance_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    anchor_hits = sum(
        1
        for token in (
            "感谢相遇",
            "不谈亏欠",
            "允许一切发生",
            "允许一切结束",
            "接纳离开",
            "接纳结束",
            "关系结束",
            "聚散终有时",
            "过客",
            "停在半路",
            "没走到最后",
            "走散",
            "白忙一场",
            "白走",
            "圆满结局",
            "圆满收场",
            "认真过的关系",
            "认真过的相遇",
            "成全后来的你",
            "悄悄成全",
            "看人的眼光",
            "爱人的分寸",
            "认真爱人",
            "饭吃热",
            "灯关好",
            "觉睡稳",
            "回到自己生活",
            "留下来的温暖",
            "任务完成了",
            "自然会退场",
            "最好的祝福",
            "整理行囊",
            "未知的山海",
        )
        if token in corpus
    )
    return anchor_hits >= 2


def _uses_local_emotional_regret_forward_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    old_object_hits = sum(
        1
        for token in (
            "旧裙",
            "碎花裙",
            "旧衣物",
            "旧物",
            "旧东西",
            "游园会",
            "旧相片",
            "旧车票",
            "旧信",
        )
        if token in corpus
    )
    regret_hits = sum(
        1
        for token in (
            "如果当初",
            "当年要是",
            "会不会不一样",
            "没走成的路",
            "反复设想",
            "遗憾",
            "过往",
            "不念过往",
            "旧事",
            "回不去",
            "改一个结局",
            "回头",
            "错过",
        )
        if token in corpus
    )
    forward_hits = sum(
        1
        for token in (
            "往前走",
            "朝前延伸",
            "不回头",
            "放下从来都不是遗忘",
            "更轻盈的去处",
            "新裙子",
            "浅紫色连衣裙",
            "广场舞",
            "没吹过的晚风",
            "没看过的晚霞",
            "前路漫漫",
            "继续生活",
        )
        if token in corpus
    )
    return old_object_hits >= 1 and regret_hits >= 2 and forward_hits >= 1


def _uses_local_emotional_forgiveness_release_variant(payload: Mapping[str, object]) -> bool:
    corpus = " ".join(
        part
        for part in (
            _extract_local_reference_corpus(payload),
            _extract_local_fallback_corpus(payload),
        )
        if part
    )
    if not corpus:
        return False
    strong_hits = sum(
        1
        for token in (
            "原谅",
            "宽恕",
            "放过自己",
            "宽宥自己",
            "世事尽可原谅",
            "看透了无常",
            "胸中养着一条毒蛇",
            "灵魂的园子里栽种荆棘",
        )
        if token in corpus
    )
    support_hits = sum(
        1
        for token in (
            "计较",
            "埋怨",
            "憎恨",
            "恩怨",
            "纠葛",
            "伤痛",
            "矛盾",
            "隔阂",
            "打扫自己的心房",
            "腾出地方",
            "多晒晒太阳",
        )
        if token in corpus
    )
    return strong_hits >= 2 or (strong_hits >= 1 and support_hits >= 2)


def _has_local_emotional_memory_reflux_result_focus(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(
        token in normalized
        for token in (
            "背影",
            "擦肩",
            "旧相册",
            "聊天记录",
            "回潮",
            "普通时刻",
            "想起",
            "旧关系",
            "没收好",
            "没收尾",
            "没说完",
            "碰不到摸不着",
            "要是他还在",
        )
    )


def _build_local_self_worth_rebuild_paragraphs(
    *,
    payload: Mapping[str, object],
    intro: str,
) -> list[str]:
    if not _has_local_self_worth_luxury_profile(payload):
        return [
            intro,
            "点菜时你想吃辣，最后还是说“都可以”。别人临时改约，你明明失落，也只回一句：没事。",
            "委屈常常就是这样攒起来的。你一次次先说算了，先说随便，先把自己往后挪半步。你有想法，也在意，只是太习惯先顾全场面。",
            "关系里最怕的，是你让着让着，连别人都开始默认：你真的什么都行。",
            "把真实想法说出来，是把自己重新放回关系里。想吃什么就说，改了约会失落也可以直说。把你放在心上的人，会因为你终于说真话，知道该怎样好好对你。",
            "把自己放回前面，并不会突然变得强硬。只是别再让委屈替你懂事收尾，别再让沉默替你一次次点头。",
            "下次那句“都可以”到嘴边时，先停一下。先在心里过一遍：这次我是真的愿意，还是又想赶紧把场面圆过去。",
            "你把自己看重一点，日子里的轻重，关系里的分寸，才会慢慢回到该有的位置。",
        ]

    return [
        intro,
        "很多人心里都有底线，只是太习惯先把场面顾过去。别人临时改主意，你先说行；不合适的请求递过来，你也总想再扛一下。",
        "时间久了，别人会以为你好商量，你自己也会差点忘了，那些不想答应、不想将就的感觉，本来就该算数。",
        "所谓把自己养贵一点，说到底，是开始知道什么关系值得花时间，什么要求不必硬着头皮接。",
        "门槛摆在那里，是给自己留一道提醒：别再为了显得懂事，把尊重和体面一并让掉。",
        "你把标准慢慢收回来，不会失去愿意珍惜你的人。对方也会因为你终于认真对待自己，知道该怎样认真对待你。",
        "关系里有要求并不可怕。可惜的是，你连自己都默认：随便一点也行。",
        "把自己放回前面以后，人会清醒很多。你先把自己看重，别人才能慢慢学会看重你。",
    ]


def _build_local_response_priority_time_priority_paragraphs(
    *,
    payload: Mapping[str, object],
    intro: str,
) -> list[str]:
    opening = intro.strip()
    if not opening or any(token in opening for token in ("轻描淡写的话", "多问一句", "被听懂")):
        opening = _pick_local_seeded_text_variant(
            payload,
            (
                "他说自己很忙那一刻，你把手机放下，心里那点期待也跟着安静了一下。",
                "红灯只有三十秒，也够喝口水、切首歌、回一句“晚点找你”。有些答案，就藏在这些小空当里。",
            ),
        )

    return [
        opening,
        "把你放在心上的人，也会忙，也会顾不上。可他会先留一句交代，忙完以后，也会回来把那句落下的话接完。",
        "红灯的三十秒、排队的几分钟、到家换鞋前那会儿，都够发一句“我看到了，晚点说”。你可以等一会儿，可一直等不到交代，心就会慢慢凉下来。",
        "你一次次替对方解释：他只是太忙了，今天事情太多了。解释得久了，连失落都像成了自己不懂事。",
        "一个人把时间给谁，答案常常藏在那些细小空当里。愿意把回应补回来的人，心里一直有你的位置。",
        "好的回应不需要二十四小时黏着。忙完记得回来，临时顾不上也愿意说明白，这就够让人安心。",
        "把真心留给愿意回应你的人。你不需要反复催，也不必在等待里，把自己的位置慢慢放轻。",
        "被这样放在顺序里，人会安心很多。关系也不必总靠猜，因为对方会用时间告诉你：你到底重不重要。",
    ]

def _build_local_response_priority_followup_paragraphs(
    *,
    payload: Mapping[str, object],
    intro: str,
) -> list[str]:
    corpus = _build_local_response_priority_followup_corpus(payload)
    has_comment_like = "点赞" in corpus and "评论" in corpus
    has_photo_scene = any(token in corpus for token in ("晚霞", "夕阳", "落日", "照片", "朋友圈"))
    has_followup = any(token in corpus for token in ("追问", "补问", "多问一句", "我随时在", "打电话", "我没事", "我有点累"))
    has_share_noise = any(token in corpus for token in ("毫无意义的废话", "喜怒哀乐", "晚霞与风雪", "注意力分给你"))
    has_fly_tired = any(token in corpus for token in ("飞得高不高", "飞得累不累"))
    has_specific_comment_scene = any(
        token in corpus
        for token in ("终于下班了", "项目又出岔子了", "领导痛批", "工作受了委屈", "吐槽给我打电话")
    )

    opening = intro.strip()
    if not opening or any(token in opening for token in ("轻描淡写的话", "多问一句", "被听懂")):
        if has_photo_scene and has_comment_like:
            opening = "一张晚霞照发出去，点赞很快铺满屏幕；让人心里一松的，是那句认真追问。"
        else:
            opening = "很多回应都会路过你，难得的是有人真的停下来。"

    paragraphs = [
        opening,
        "你明明只说了一句很轻的话，像是随手带过。可在意你的人会顺着那点语气再往前走一步，听出你为什么忽然只发了这一句。",
    ]
    if has_specific_comment_scene:
        paragraphs.extend(
            [
                "那天你不过发了一句：\"今天的夕阳真美，终于下班了。\"别人顺手点了赞，只有一个人看出了不对劲，问你：是不是项目又出岔子了？",
            ]
        )
    else:
        paragraphs.extend(
            [
                (
                    "他不会急着把话题带开，也不会只留一个表情就算回应。"
                    "他只是多问一句：你是不是还有话没说完。"
                )
                if has_followup
                else "他不会急着把话题带开，也不会只留一个表情就算回应。他会停一下，听你把那句轻描淡写慢慢说完。",
            ]
        )
    paragraphs.extend(
        [
            "这句追问看起来不大，落在心里却很重。你终于不用把那点情绪再往回收，也不用把“我没事”来回说给自己听。",
            (
                "有人陪你热闹，有人顺手点赞，有人寒暄两句就走。等屏幕暗下来，留在心里的，还是那个肯停下来的人，是那句补问，也是那份被认真听见的感觉。"
                if has_comment_like
                else "有人会顺手回应你，也有人愿意把你的话再听深一点。那句追问落下来，心里悬着的地方会先松一下。"
            ),
            "在意会变成很具体的注意力。它不会被一句“我没事”轻轻带过去，也不会把你的情绪当成顺手划过去的动态。它愿意听完你没说完的话，也愿意在忙完以后，再回来把那句轻描淡写接下去。",
        ]
    )
    if has_photo_scene:
        paragraphs.append("你随手发一张晚霞，别人看见的是风景，他看见的却是你那天为什么只想发这一张图。")
    if has_share_noise:
        paragraphs.append("那些看起来没什么意义的废话，他也肯回。因为他在意的，从来不只是事情本身，还有你说这句话时的心情。")
    if has_fly_tired:
        paragraphs.append("别人问你飞得高不高，他会先问一句：你今天是不是太累了。")
    paragraphs.append(
        "被这样接住过一次，人就会知道什么样的关系值得珍惜。以后再看热闹不热闹、互动多不多，心里自然会分得清：谁只是路过，谁愿意为你停下来。"
    )
    return paragraphs
def _build_local_mode_shaped_generic_paragraphs(
    *,
    payload: Mapping[str, object] | None = None,
    mode: str,
    intro: str,
    point_one: str,
    point_two: str,
    point_three: str,
    point_four: str,
    bridge: str,
    reframe: str,
    consequence: str,
    closing: str,
) -> list[str]:
    if mode == "everyday_warmth_return":
        if payload and _uses_local_everyday_warmth_simple_happiness_variant(payload):
            return [
                f"{intro}鞋还没换好，厨房里有人探头说：“回来啦？先洗手。”这句话不响，却把一天的奔波接住了一半。",
                "年轻时很容易把幸福想得很满。钱要再多一点，房子要再大一点，认识的人要再广一点，才觉得日子算往上走。",
                "可走着走着，人会慢慢换一套算法。身体少点毛病，家里少点挂心，饭点有人等，话到嘴边有人愿意听，心就会踏实很多。",
                "下班路过菜市场，买两把青菜、一条鱼，回家听见锅铲碰到锅边的声音，那种安心不需要发朋友圈，也不需要谁来证明。",
                "孩子把今天学校里的小事讲得乱七八糟，父母在电话里反复叮嘱天气，老朋友约你下周喝茶。都不是大事，却都在告诉你：你不是一个人在过日子。",
                "知己也不用很多。能在你把话说到一半时不抢着下结论，能在你沉默时陪你坐一会儿，能在你高兴时真心替你高兴，三两个就够珍贵。",
                "家也不一定要多漂亮。推门有人应，饭桌有你的位置，累了能歇一会儿，病了有人递水，天冷有人催你加衣，就是很具体的福气。",
                "苏轼写过一句：“人间有味是清欢。”越往后越觉得，这清欢不在热闹里，常常就在一碗汤、一盏灯、几句寻常话里。",
                "所以别总觉得自己拥有得不够多。家里人平安，知己还在，一日三餐能安稳吃完，已经是很多人走过半生后最想守住的踏实。",
                "往后，把心放宽一点，把日子过实一点。能珍惜眼前的人，能守好平淡的饭香和灯光，日子就有了值得回味的地方。",
            ]
        return [
            f"{intro}鞋还没换好，厨房里有人探头说：“回来啦？先洗手。”这句话不响，却像把一天的风尘轻轻拍了拍。",
            "年轻时总觉得幸福要有很大的样子：账户数字再漂亮一点，房子再大一点，朋友圈再热闹一点。",
            "可人走到后来，常常会被很小的事劝住：父母电话里一句“别太累”，朋友饭桌上一句“你先说完”，孩子回头喊你一声，心就落了地。",
            "有个朋友前阵子说，他最开心的一天，没有升职，也没有买什么贵东西，只是下班早了半小时，陪父母去菜市场买了一把青菜。",
            "回家时，孩子在楼下等他，手里攥着一根快化的冰棍，非要分他一口；饭桌上没什么大菜，母亲还是把鱼肚子那块夹到他碗里。",
            "那一刻他才承认，自己这几年追得那么急，想要的不过是这样的晚上：人都在，饭还热，话可以慢慢说。",
            "朋友不用很多。能在你话说到一半时不急着评价，能在你沉默时问一句“是不是累了”，这份懂得已经很难得。",
            "家也不一定要多大。推门有人应，饭桌有你的位置，生病时有人递水，天冷时有人催你加衣，就是很多人想守住的福气。",
            "苏轼写过一句：“人间有味是清欢。”这句话好，是因为它把幸福从高处请回了日常，也把热闹之外的踏实留给了我们。",
            "家里少点挂心事，三两老友还在，饭能趁热吃，话能慢慢说，这些小事放在年轻时不觉得贵，走过一些风雨才知道样样难得。",
            "今晚不必急着和世界比输赢。把饭吃热，把话说慢，家里人平安，知己还在，日子就有了很实在的回声。",
        ]
    if mode == "inner_settlement":
        return _build_local_inner_settlement_paragraphs(payload=payload or {}, intro=intro)
    if mode == "self_worth_rebuild":
        return _build_local_self_worth_rebuild_paragraphs(payload=payload or {}, intro=intro)
    if mode == "response_priority" and payload and _uses_local_response_priority_time_priority_variant(payload):
        return _build_local_response_priority_time_priority_paragraphs(payload=payload, intro=intro)
    if mode == "resilience_reconstruction":
        has_pool_training = _has_local_resilience_pool_profile(
            payload,
            extra_text=f"{intro} {point_one} {point_two} {point_three}",
        )
        if has_pool_training:
            return [
                intro,
                "最难的，从来不只是疼那一下。是疼完以后，第二天还得继续练，继续把那副还没适应过来的身体一点点带回水里。",
                "别人后来看到的是成绩，是名字被念出来的那一刻。她真正花掉的力气，更多都留在那些没人鼓掌的日常里: 下水、转身、呛水、再来一遍，五十米一趟趟地磨过去。",
                "没有右臂帮她稳住平衡，没有右腿替她把水蹬开，每多划出去一下，都是实打实地拿力气往前换。连肩伤、背痛和炎症，也没有给她留多少轻松的时候。",
                "韧性，是疼过以后还继续。",
                "可人就是这样一点点被练出来的。不是靠一句“不服输”，也不是靠谁替她把苦说得多动人，而是靠今天做完，明天还肯继续做。",
                "那段最难走的路没有白走。它后来都长成了她身上的筋骨、耐心和分寸，也让她更知道，命运给过什么，不等于人生就只能停在什么地方。",
                "所以你再回头看，会知道真正托住一个人的，常常就是这些重复、这些重来、这些咬牙之后依然没有放下的动作。路就是这样一点点重新长出来的。",
            ]
        return [
            intro,
            "低谷最磨人的，往往不是那一下突然压过来，而是后面很长一段时间里，你还得自己把散掉的力气一点点拢回来。",
            "很多重新站起来的时刻，看着都不响亮。只是你又把今天该做的事做完了，又把本来想逃掉的那一步走过去了。",
            "重新开始，本来就很了不起。",
            "重建这件事，本来就不是一夜之间发生的。它常常藏在重复里，藏在重来里，也藏在别人看不见、你却没有放下的那些小动作里。",
            "时间久了你会发现，真正留在身上的，不只是那段路有多难，还有你是怎么一步步把自己重新托住的。",
            "那些被生活按下去又重新起身的日子，会把人的筋骨慢慢养出来。等你回头看，路早就不是原来那条路了，人也不是原来那个只会被动承受的人了。",
        ]
    if mode == "scene_first_progression":
        reference_scene_corpus = _extract_local_reference_corpus(payload)
        scene_corpus = f"{intro} {point_one} {point_two} {point_three} {reference_scene_corpus}"
        has_meeting_room = _has_local_scene_first_office_markers(scene_corpus)
        has_transit_scene = _has_local_scene_first_transit_markers(scene_corpus)
        has_household_scene = _has_local_scene_first_household_markers(scene_corpus)
        if has_meeting_room:
            return [
                intro,
                "领导把杯子往桌边一放，话题就顺着旧方案往下走了。你昨晚改到很晚的那一页还停在屏幕上，可那个本来该接上的提醒，最后还是被你自己咽了回去。",
                "等人散得差不多了，你再去想刚才那几句话该怎么说，已经不像表达，更像一个人给自己补课。你反复回放那个瞬间，想的不是问题本身，而是自己为什么又把场面放在了前面。",
                "话在会上咽回去一次，下一次就更容易继续往后放。判断你一直有，问题你也看见了。只是每回轮到自己开口，你总先把场面稳住，再把自己那句更重要的留到最后。",
                "这样久了，人先退掉的往往不是能力，是那股“我也可以在这里说话”的劲。你太习惯先顾全气氛，慢慢就连自己都忘了，那句话本来就该在当场出现。",
                "话留在当场，人才站得稳。",
                "很多位置，不是等谁慢慢分给你的。你肯把那句话留在当场，别人才能慢慢听见你，你自己也会更站得住。下次再进那间会议室，不用一下子说很多。把最该说的那一句留住，就已经是在往前走了。",
            ]
        if has_transit_scene:
            return [
                intro,
                "她抬手拢了拢围巾，只说这阵子事多。你听得出那句话后面还有东西，也看见她眼里的疲惫，可嘴边那句真正想问的，还是被你自己按住了。",
                "等摆渡车靠边，两个人跟着人群上去，各自看向窗外。玻璃很快蒙起一层白气，刚才那个话头也就这么断在了路上，像是谁都没刻意回避，可谁也没有再往前走一步。",
                "关系不是在这一晚突然远掉的。更多时候，是你明明想再靠近一点，却还是先替对方把台阶铺好，替那句真话选了沉默。",
                "那天并没有人把话说重，可话一直不往前走，误会和疏远就会顺着这些空白慢慢长出来。",
                "靠近，也需要一句及时的话。",
                "所以后来最该认出来的，不只是对方有没有变，而是自己是怎么一次次把靠近撤回去的。那句话早点说出口，很多路就不会绕那么远。",
            ]
        if has_household_scene:
            return [
                intro,
                "桌上的药盒还摆着，那张单子也没收起来。你站在那儿看了一会儿，还是先把那句想问的话咽了回去。孩子早就睡下了，屋里静得只剩一点水声，你最先顾的，还是别让这个晚上一下子沉下去。",
                "家里最难的，往往是每个人都想等对方先缓一缓。于是饭先吃完，灯先关掉，孩子先安顿好，那件真正该说清楚的事，也就这样被顺到了明天。",
                "第二天照常出门，消息照回，饭也照吃，表面上像什么都没发生。可心里那根线一直在那里，你们谁都没提，它就一直没有松。",
                "家里的心事，越拖越沉。",
                "家要稳住，靠的从来不是谁一直忍着。真正托住一个家的，是还能坐下来慢慢说，把慌张、担心和那句没来得及说出口的话，一点点说开。",
            ]
        return [
            intro,
            "当下看着只是算了，后面却常常不是这么轻。那句没说出口的话，会在你心里来回停很久，也会把原本不该长出来的距离一点点带出来。",
            "很多变化都不是从大事开始的。更多时候，是一个人先替场面让路，先替对方想好了“算了吧”，于是最重要的话总在关键那一秒被压后。",
            "表面上人还在往前走，心里其实已经退了半步。等沉默攒多了，误会、别扭和疏远也就跟着有了位置。",
            "别把真话一直留给后来。",
            "后来真正该做的，不是反复替那一刻找理由，而是认出自己是怎么把真话一次次往后拖的。你肯把话说出来，很多悬着的地方才有机会重新落回地面。",
        ]
    if mode == "emotional_engine_direct":
        if payload and _uses_local_emotional_regret_forward_variant(payload):
            return [
                intro,
                "那一刻最扎人的，其实不是一条裙子旧了，而是人会突然想起：如果当年换一种选择，后来会不会真的不一样。",
                "很多遗憾都是这样留在心里的。它不吵，也不天天出现，只是在你经过某个地方、翻到某样旧物时，轻轻把人拉回去一下。",
                "可后来你会慢慢懂，过去最让人放不下的，不一定是那件事本身，而是我们总想替它改一个结局。",
                "一条裙子没有去成游园会，一段话没来得及说出口，一次机会没能抓住。它们都是真的遗憾，但也真的已经停在了那一年。",
                "放下不是把它从生命里删掉。放下是承认它来过，也承认今天的风还在吹，眼前的路还在往前铺。",
                "后来阿婆把旧裙子收了起来，换上孙女陪她买的新裙子去公园。你会发现，人心真正松开的瞬间，不是忽然忘了过去，而是终于愿意把日子过回现在。",
                "旧事可以好好收着，别再拿它困住自己。人这一生，总要把一些来不及还给昨天，也把更多的可能留给明天。",
            ]
        if payload and _uses_local_emotional_forgiveness_release_variant(payload):
            return [
                intro,
                "那些让你不痛快的人和事，未必每天都在眼前，却会在你心里占着地方。你越反复想，越像替它们留了一间屋子，自己反而没地方好好休息。",
                "原谅不是说那件事没发生，也不是替谁开脱。原谅是你终于不再让一段旧怨，继续决定今天的心情。",
                "一直计较下去，未必能让对方付出什么代价，却会让你一次次回到那口气里。夜里想起，心还是紧；白天碰到相似的人，情绪又被牵走。",
                "所以放过别人，有时候更像是在放过自己。把那些无足轻重的争执、误会和旧伤慢慢清出去，心里才有地方晒太阳，也有地方重新种花。",
                "真正的宽恕，不是委屈自己继续忍，而是看清事情已经过去，自己不必再跟着它一起受困。你可以记得教训，也可以把生活重新交还给今天。",
                "往后的日子，少一点纠缠，多一点舒展。不是所有事都值得反复争赢，能让自己睡个安稳觉，已经是很大的胜利。",
            ]
        if payload and _uses_local_emotional_memory_reflux_variant(payload):
            return [
                intro,
                "最让人措手不及的，往往不是夜深人静时那场大哭，而是你以为已经过得差不多了，它却借一个背影、一首老歌、一页旧记录，又把那段路轻轻带回来。",
                "你反复想起的，也不一定只是那个人。更多时候，是那句没说完的话，是当年没等到的回应，也是那个在关系里没有被好好接住的自己。",
                "所以很多人会误以为，自己是还没放下。其实未必。你只是还没有替那段旧关系找到一个安稳的位置，才会在生活松动的缝隙里，一次次被往事敲一下。",
                "想起并不丢人，舍不得也不是软弱。认真爱过、认真期待过的人，本来就不可能像删掉一条消息那样，把一段路立刻删干净。",
                "真正让回忆慢慢退下去的，也不是逼自己快点忘。是你终于肯承认：那段相遇确实来过，也确实停在了那里；你不用回头重走，但可以把它认真收好。",
                "等你不再拿今天去补昨天，不再一遍遍替旧结局找新的说法，心里的位置才会慢慢空出来。那个人留下的好、留下的分寸、留下的教训，也会一点点回到你自己身上。",
                "后来再想起时，你还是会停一下。但那一下不再只是发酸，而是终于能对自己说：我记得，我也愿意继续过好现在的生活。",
            ]
        return [
            intro,
            "日子已经继续往前走了，可有些痕迹不会立刻退场。路过熟悉的地方，听见一句像他的话，或者只是傍晚风一吹过来，心里那块地方还是会轻轻发酸。",
            "你反复想起的，也未必是一定要回去。更多时候，是舍不得把那几年一起走过的路，简单归成一句白忙一场。",
            "可人和人走散，并不会把那段路上得到的东西一并带走。你后来更懂分寸了，更知道自己要什么了，也更明白被好好对待是什么感觉。",
            "这些留下来的部分，没有消失。它们安静长在你身上，变成你现在看人的眼光，做选择的底气，也变成你下一次认真爱人的能力。",
            "偶尔想起时，不必急着给那段关系下结论。它走到这里就停在这里，曾经照亮过你的部分，也确实留在了你身上。",
            "走散不等于白来。",
            "把那段路好好收进心里，再把今天的饭吃热、灯关好、觉睡稳。人是这样一点点回到自己生活里的。",
        ]
    if mode == "supportive_appreciation":
        return _build_local_supportive_appreciation_paragraphs(payload=payload or {}, intro=intro)
    if mode == "relationship_aftercare":
        return [
            intro,
            "桌上的水杯还在原处，两个人都没再吵，可屋里比刚才更冷。刚才那些重话像没收干净的碎片，谁走过去都会被扎一下。",
            "一场争执真正伤人的地方，很多时候不在声音有多大。而是你难过了很久，对方却像什么都没发生；你还停在原地，他已经把这件事当成了过去。",
            "有些人吵完就躲进沉默里，把问题交给时间。可时间只能把场面晾干，接不住心里的失望。",
            "一次两次还能劝自己算了，先睡吧。次数多了，人先学会的，往往就是把期待收小。",
            "好的关系当然会有争执。更要紧的，是争执以后还有人肯把门重新打开，肯把刚才那句重话慢慢收回来。",
            "愿意回来的人，会先把声音放低，会承认刚才哪句话说重了，也会问一句：你刚刚是不是很难受。",
            "愿意修复的人，才是真的舍不得。",
            "输赢放到一边，关系才有机会从那阵冷气里回暖。真正想继续走下去的人，会回来把话说完，把情绪接住，也把那份失望一点点接回去。",
        ]
    if mode == "self_reliance_inward_support":
        stale_markers = (
            "外面的帮扶",
            "没人能立刻搭把手",
            "没有人能随时赶来",
            "等不到外面的手",
            "等外面的安慰",
            "即使没有帮助",
            "外面的安慰",
            "向内稳住",
            "自我托底",
            "今天先撑过去",
            "孤立无援",
            "每个人都在各自扛事",
            "四周都腾不出空",
            "想找人倾诉",
            "消息框开了又关",
            "先把今天过完",
            "事情压到眼前",
            "把顺序重新理回来",
            "把慌乱收回一个动作",
            "能让人重新站稳的",
            "当眼前这一小步被接住",
            "主心骨",
            "重新有光",
            "一点点亮",
            "下一步",
        )

        def _self_reliance_point(value: str, default: str) -> str:
            cleaned = _clean_local_fallback_instruction_phrase(value)
            if (
                not cleaned
                or _looks_like_local_fallback_instruction_fragment(cleaned)
                or _looks_like_local_fallback_strategy_scaffold(cleaned)
                or any(marker in cleaned for marker in stale_markers)
            ):
                return default
            return cleaned

        if "不是不想开口" in point_one:
            point_one = "你想找人商量，也知道别人手里可能正压着自己的事"
        point_one = _self_reliance_point(point_one, "你想找人商量，也知道别人手里可能正压着自己的事")
        point_two = _self_reliance_point(point_two, "向内求不是硬撑，是先把情绪放低，把眼前最要紧的一件事处理好")
        point_three = _self_reliance_point(point_three, "真正托住人的，是你还愿意照顾自己、处理手边事，也知道什么时候请别人一起分担")
        point_four = _self_reliance_point(point_four, "你可以求助，也可以先自救；两件事都不丢人")
        if "你可以求助" in point_four or ("自救" in point_four and "求助" in point_four):
            point_four = "求助不丢人，自救也不丢人"
        return [
            _compose_local_followup(intro, point_one),
            "电话拿起来又放下时，你没有继续在原地打转，而是先把桌上的单子理顺，把今晚必须处理的事写成三行。",
            "人就是在这样的动作里慢慢回稳的。先喝一口水，先把灯打开，先把最要紧的一件事放到眼前。",
            _compose_local_followup(point_two, "能有人马上帮你当然很好；一时等不到，也不代表你只能停在那里。"),
            "先把顺序理出来，心里的慌就会退一点；先把能做的做完，外面的帮助来了，也更容易接得住。",
            _compose_local_followup(point_three, "你不再把全部希望压在某一个人的回应上，也不会因为暂时没人搭手，就把眼前事彻底放下。"),
            "成年人很重要的一份底气，是需要的时候敢开口，没人立刻回应时，也能先把自己照顾住。",
            _compose_local_followup(point_four, "等你把自己稳住，再去找那个真正愿意分担的人，很多话会说得更清楚，很多事也会处理得更稳。"),
        ]
    if mode == "pressure_interface_direct":
        return [
            intro,
            "你当然记得那件事。只是工作群一响，手边的事一接上，体检可以改到下周，晚饭可以拖到很晚，休息也总能被一句“先忙完”挤到后面。",
            "日子表面还照常走，顺序却一点点乱了。该吃饭的时候又说等一会儿，该休息的时候再看一眼表格，该复查的时候又给自己找了个理由。",
            "照顾自己，也是把日子照顾好。",
            "真正该被看见的，除了那条复查短信，还有桌上凉下来的饭、日历里改过好几次的预约、以及那个本来可以早一点停下来的晚上。",
            "把自己排回前面，不是把责任丢下。饭点稳一点，检查按时一点，节奏慢一点，后面要照顾的人和事，反而更容易被你稳稳接住。",
            "可以先从一个很小的接口开始。把复查约回日历，把那顿饭认真吃完，把今天能停下来的十分钟留给自己。",
            "这些动作都不大，却会把人从乱掉的顺序里慢慢拉回来。你不必一下子改变所有安排，先别再把自己一次次往后挪。",
            "今晚如果手机又亮了一下，也可以先把筷子放慢，把饭吃热，把明天那条预约确认好。",
            "那一刻，生活不会突然轻松，却会重新有一点落点。你把自己放回今天，今天也会慢慢托住你。",
        ]
    if mode == "trust_boundary":
        return [
            intro,
            _compose_local_followup(
                "人不一定会当场追问。",
                "更多时候，是那一下停顿，让你忽然知道：心里的放心，已经悄悄松了一点。",
            ),
            _compose_local_followup(
                "你当然可以继续笑，也可以告诉自己别小题大做。",
                "可心里那块地方已经变了：以前一句解释就能安稳，现在会忍不住把前后细节重新想一遍。",
            ),
            _compose_local_followup(
                "愿意相信你的人，给出去的不只是自由。",
                "他把一段关系里的心安交给你，也默认你会在容易误会的地方主动说清。",
            ),
            _compose_local_followup(
                "临时改了安排，可以主动说一声；答应过的事做不到，也可以把原因讲明白。",
                "真正让人心凉的，是明明有机会坦白，却先想着绕过去。",
            ),
            _compose_local_followup(
                "你把话说透，对方就不用在沉默里替你补全另一个故事。",
                "放到日常里，就是把容易误会的地方提前摊开，把答应过的事情尽量做到。",
            ),
            _compose_local_followup(
                "坦诚不靠大段解释，很多时候就藏在提前半步的交代里。",
                "话别只说一半，事别总让对方猜；能给清楚的时间，就别留下含糊的空白。",
            ),
            _compose_local_followup(
                "被辜负过的人会变敏感，这不丢人。",
                "那是心在提醒你：别再把赤诚交给含糊。",
            ),
            "关系是会被日常慢慢养回来的。一次主动说明，一次准时兑现，一次把话摊开说完，都会让那道裂缝少疼一点。",
            _compose_local_followup(
                "值得珍惜的人，会把你的放心当成责任。",
                "你给他自由，他给你踏实；你把心交给他，他舍得用日常的一件件小事托住。",
            ),
            _compose_local_followup(
                "请好好护住那份愿意交出来的相信。",
                "信任一旦被认真对待，爱才有了落脚的地方。",
            ),
        ]
    if mode == "response_priority":
        if payload and _uses_local_response_priority_followup_variant(payload):
            return _build_local_response_priority_followup_paragraphs(payload=payload, intro=intro)
        return [
            intro,
            "真正让人放松的，不一定是立刻得到答案。有人愿意把手里的事停一下，听你把绕来绕去的话说完，已经是一种很具体的重视。",
            "有些关心看起来很轻：记得你昨天说过的难处，在你语气变慢时不急着换话题，见面时把水推近一点。它没有排场，却让人知道自己没有被敷衍。",
            "被认真听完一次，很多悬着的情绪就会自己落下来。你不必把每句话说得漂亮，也不用先证明自己的难受够不够重要。",
            "好的关系不需要时时在线。你真正需要开口的时候，对方愿意在场；你把真心交出去的时候，他也舍得认真接住。",
        ]
    return [
        intro,
        bridge,
        _ensure_sentence_end(point_one),
        f"{_ensure_sentence_end(point_two)}{reframe}",
        _compose_local_followup(point_three, consequence),
        _compose_local_followup(point_four, closing),
    ]

def _build_local_responsibility_shelter_draft(payload: Mapping[str, object]) -> tuple[str, str]:
    outline = payload.get("outline")
    outline_body = ""
    if isinstance(outline, Mapping):
        outline_body = str(outline.get("outline_body") or "").strip()
    points = _extract_local_draft_outline_points(outline_body)
    strategy_card = payload.get("strategy_card")
    positive_direction = ""
    if isinstance(strategy_card, Mapping):
        positive_direction = str(strategy_card.get("positive_direction") or "").strip()

    raw_title = str(payload.get("topic_title") or payload.get("project_title") or "").strip()
    title = raw_title or "肩上有责任的人，心里也要留一盏灯"
    if any(token in title for token in ("没事，有我", "这个月的绩效", "缴费窗口")):
        title = "肩上有责任的人，心里也要留一盏灯"
    if (
        _uses_local_responsibility_endurance_variant(payload)
        and title == "肩上有责任的人，心里也要留一盏灯"
    ):
        title = (
            _resolve_local_responsibility_packaging_title(payload)
            if _has_local_responsibility_endurance_concrete_duty(payload)
            else _resolve_local_responsibility_endurance_topic_title(payload)
        )
    quote = _resolve_local_responsibility_quote(payload)
    second_point = _resolve_local_fallback_point(
        points[1] if len(points) > 1 else "",
        default="父母的事要惦记，孩子的事要跟上，工作那头也不能松",
    )
    second_point = _normalize_local_responsibility_burden_point(second_point)
    third_point = _resolve_local_fallback_point(
        points[2] if len(points) > 2 else "",
        default="父母少一点担心，孩子多一点底气，家里多一点踏实，这些都在告诉你，自己没有白忙",
    )
    third_point = _normalize_local_responsibility_cost_point(third_point)
    ending = _resolve_local_responsibility_ending(positive_direction)
    pressure_detail = _resolve_local_responsibility_pressure_detail(payload)
    warmth_detail = _resolve_local_responsibility_warmth_detail(payload)
    responsibility_opening = _resolve_local_responsibility_draft_opening(payload)
    responsibility_daily_detail = _resolve_local_responsibility_daily_detail(payload)

    if _uses_local_responsibility_endurance_variant(payload):
        if _uses_local_responsibility_midlife_variant(payload):
            paragraphs = [
                f"{responsibility_opening}很多中年人的“我没事”，都是在这种时候先说出口的。",
                responsibility_daily_detail,
                "生病了不是不想请假，委屈了也不是没想过转身。只是申请还没点下去，脑子里已经先把手头的工作考核、家里的支出和后面的安排排了一遍。",
                "很多时候你不是比谁更有答案，只是知道这会儿不能让家里那头先乱。于是声音先放稳，最急的那件事先接过来，自己的那口气再晚一点慢慢喘。",
                "很喜欢一句话：“肩上有牵挂的人，脚下才会长出路。”人到中年，许多选择看起来是在往前赶，其实都是在替爱的人把路铺平一点。",
                "夜里躺下以后，脑子还在给白天那几件事排先后。你也会问一句：这样忙，到底值不值得。问完没有答案，只能翻个身，告诉自己明早先把哪件事办了。",
                "后来再看，父母遇到医院的事没那么慌了，孩子碰上难题也知道先稳一下再想办法，伴侣累的时候终于肯说一句“你帮我想想”。这些变化都不响亮，却让你知道，忙过的路没有白走。",
                "你忙这一圈，心里惦记的其实很简单：爸妈来电话别先慌，孩子碰上事知道还有人顶着。家里的日子不必多体面，只要每个人遇事时都还有一点底气。",
                "推门回家的时候，桌上给你留着一口热饭，屋里有人顺手接过你的包，说一句先坐会儿。那一刻人不会一下子被治愈，却会真真切切地松一口气。",
                "把家里顾好的人，也该轮到别人心疼你一下。别总等所有事都稳了，才想起自己也累。你替一家人认真走过的那些日常，后来也会一点点变成照回自己身上的光。",
            ]
            return title, "\n\n".join(paragraphs)
        paragraphs = [
            f"{responsibility_opening}很多中年人的“我没事”，都是在这种时候先说出口的。",
            "成年人最常说的谎，大概就是“我没事”。不是没觉得难，也不是没觉得累，只是你心里明白，自己这一乱，家里那几个人就会更没底。",
            "生病了想请假，先想到的是手头的工作考核；心里发涩的时候想转身，先想到的是家里的开销和孩子接下来的安排。不是谁天生更会扛，只是轮到你时，你总会先把自己放到后面。",
            "很喜欢一句话：“肩上有牵挂的人，脚下才会长出路。”那些被你反复排顺的日常，最后都会替一家人攒下看得见的底气。",
            "你也会在夜里问一句：这样熬，到底值不值得。可第二天一早，水烧开了，消息响了，家里那头等着回话，你还是会把该做的事一件件接起来。",
            "真正把人撑住的，常常不是一句“再坚持一下”，而是你慢慢看见，那些咽下去的辛苦，真的在替家里换来一点安稳。",
            "父母去医院时少一点踌躇，孩子遇事时多一点底气，伴侣在风雨来的时候，知道这个家还有人一起撑。原来你熬过的每一晚，都没有白熬。",
            "所谓人间安稳，从来不是生活忽然不难了。是账单还会来，责任还在肩上，可家里的灯还亮着，饭还是热的，有人见你回来，会先问一句：“累了吧，先坐会儿。”",
            "那一刻，你不会突然觉得自己有多了不起，只会忽然松一口气。原来这些年拼命往前，不是为了赢过谁，只是想让爱的人少一点慌。",
            "所以别总把自己只看成那个会扛事的人。你替家里挡过的风，会慢慢变成一家人的底气；你守住的日常，也会在某一天反过来安慰你。",
            "把日子往前托的人，也该被日子温柔托住。你可以继续认真生活，也别忘了给自己留一点光。",
            "天亮之前总有一段路最黑，但只要心里还有牵挂，家里还有灯，你走过的万般辛苦，最后都会落成想要的人间安稳。",
        ]
        return title, "\n\n".join(paragraphs)

    paragraphs = [
        f"{responsibility_opening}很多责任，都是在一次次先把家里安顿好的过程中，慢慢落到了肩上。",
        "先看哪张单子得今天处理，先想谁能去跑这一趟，先把孩子那边的安排补上。责任看起来并不轰烈，临时有事时，你会本能地把下一步先想出来。",
        f"{_ensure_sentence_end(quote)}落到日常，不过是一盒药提前买好，把校服洗出来晾着，把冰箱里缺的菜顺手记下来。家里能少一分慌，人心就能多一分稳。",
        f"{_resolve_local_responsibility_transition(payload)}时间久了，你就习惯先把家里那头安顿好，再回头看自己还能不能缓一口气。{_ensure_sentence_end(second_point)}{pressure_detail}",
        "事情一多，你会把能办的先办，把能问的先问。牵挂多了，人就会自然往前站半步。到这种时候，顾不上逞强不逞强，你只知道，今天要是自己先乱了，屋里那几个等你的人也会跟着慌。",
        "你不是天生会扛事，只是轮到你时，习惯先说一句“我来想办法”。久而久之，父母有事先找你，孩子有事先喊你，连家里那些零碎安排，也都默认你会接上。",
        "会扛事的人，也要被人接住。",
        f"真正让人继续往前走的，常常是你回头一看，家里确实比从前稳了一点。{_ensure_sentence_end(third_point)}{warmth_detail}",
        "所以后来你会明白，一个家真正的底气，是有人肯把事接住，也有人愿意在你回头的时候接住你。一个家要走得稳，靠的是彼此都愿意搭一把手。",
        "那口热饭、那句“先吃饭，别急”、那盏一直亮着的灯，看起来都很小。可人忙了一整天，最后靠的往往就是这些细碎的回应，把心重新安顿下来。",
        f"把日子往前托的人，也该被日子温柔托住。某个晚上，你推门回家，桌上给你留着一口热饭，屋里有人问你累不累。那个瞬间你会明白，你替家里挡过的风，也会慢慢变成照回自己身上的光。{ending}",
    ]
    return title, "\n\n".join(paragraphs)


def _build_local_generic_tracked_article_draft(payload: Mapping[str, object]) -> tuple[str, str]:
    outline = payload.get("outline")
    hook = ""
    outline_body = ""
    if isinstance(outline, Mapping):
        hook = str(outline.get("hook") or "").strip()
        outline_body = str(outline.get("outline_body") or "").strip()
    points = _extract_local_draft_outline_points(outline_body)
    problem_brief = payload.get("problem_brief")
    theme_axis = ""
    core_conflict = ""
    if isinstance(problem_brief, Mapping):
        theme_axis = str(problem_brief.get("theme_axis") or "").strip()
        core_conflict = str(problem_brief.get("core_conflict") or "").strip()
    strategy_card = payload.get("strategy_card")
    positive_direction = ""
    if isinstance(strategy_card, Mapping):
        positive_direction = str(strategy_card.get("positive_direction") or "").strip()
    mode = _resolve_local_generic_fallback_mode(payload)
    mode_defaults = _resolve_local_mode_outline_defaults(mode)

    title = str(payload.get("topic_title") or payload.get("project_title") or "把眼前这件事重新说清").strip()
    title = _normalize_self_reliance_local_title(payload, title)
    if mode == "relationship_aftercare":
        title = _normalize_relationship_aftercare_local_title(title)
    intro = _resolve_local_generic_opening(
        payload=payload,
        mode=mode,
        hook=hook,
        theme_axis=theme_axis,
        core_conflict=core_conflict,
    )
    if mode == "response_priority":
        intro = intro.replace("有没有人愿意继续多问一句", "有没有人肯继续多问一句")
    point_one = _resolve_local_fallback_point(
        points[0] if len(points) > 0 else "",
        default=mode_defaults[0],
    )
    point_two = _resolve_local_fallback_point(
        points[1] if len(points) > 1 else "",
        default=mode_defaults[1],
    )
    point_three = _resolve_local_fallback_point(
        points[2] if len(points) > 2 else "",
        default=mode_defaults[2],
    )
    point_four = _resolve_local_fallback_point(
        points[3] if len(points) > 3 else "",
        default=_clean_local_fallback_instruction_phrase(positive_direction) or mode_defaults[3],
    )
    if mode == "scene_first_progression":
        scene_hook = _resolve_local_scene_first_hook(payload, topic_angle=str(payload.get("topic_angle") or "").strip())
        if scene_hook:
            intro = scene_hook
        scene_points = _resolve_local_scene_first_outline_points(
            payload,
            positive_direction=positive_direction,
            default_closing=point_four or mode_defaults[3],
        )
        if scene_points:
            point_one, point_two, point_three, point_four = scene_points
    if mode == "response_priority":
        point_one = point_one.replace("有人愿意继续多问一句", "有人肯继续多问一句")
        point_two = point_two.replace("有人愿意停下来读懂你没说完的话", "有人肯停下来听完你没说完的话")
    bridge = _resolve_local_generic_mode_bridge(mode)
    reframe = _resolve_local_generic_mode_reframe(mode)
    consequence = _resolve_local_generic_mode_consequence(mode)
    closing = _resolve_local_generic_mode_closing(mode)
    paragraphs = _build_local_mode_shaped_generic_paragraphs(
        payload=payload,
        mode=mode,
        intro=intro,
        point_one=point_one,
        point_two=point_two,
        point_three=point_three,
        point_four=point_four,
        bridge=bridge,
        reframe=reframe,
        consequence=consequence,
        closing=closing,
    )
    return title, "\n\n".join(paragraphs)


def _build_local_tracked_article_draft_fallback(payload: Mapping[str, object]) -> tuple[str, str]:
    if _resolve_local_fallback_mode(payload) == "responsibility_shelter":
        return _build_local_responsibility_shelter_draft(payload)
    return _build_local_generic_tracked_article_draft(payload)


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
) -> _InitialDraftCandidateResult:
    def _finish(body: str, current_title: str) -> _InitialDraftCandidateResult:
        reference_source_markdown = _get_project_reference_source_markdown(project)
        normalized_title = _normalize_responsibility_shelter_draft_title(
            title=current_title,
            body_markdown=body,
            topic_title=str(project["topic_title"] or ""),
            project_title=str(project["title"] or ""),
            reference_source_markdown=reference_source_markdown,
        )
        reference_title = current_title
        reference_body_markdown = body
        current_body, changed_steps = _apply_initial_draft_candidate_cleanups(
            title=normalized_title,
            body_markdown=body,
            source_type=str(project["source_type"]),
            reference_source_markdown=reference_source_markdown,
        )
        return _InitialDraftCandidateResult(
            title=normalized_title,
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
        )
        finalized_body_markdown, finalized_title = _maybe_retry_draft_for_positive_payoff(
            project=project,
            outline_row=outline_row,
            tone_profile=tone_profile,
            review_comment=review_comment,
            polish_instruction=polish_instruction,
            strategy_bundle_payload=strategy_bundle_payload,
            reference_article_payload=reference_article_payload,
            generator=generator,
            candidate_title=finalized_title,
            candidate_body_markdown=finalized_body_markdown,
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


def _maybe_retry_draft_for_positive_payoff(
    *,
    project: sqlite3.Row,
    outline_row: sqlite3.Row,
    tone_profile: ToneProfileItem,
    review_comment: str | None,
    polish_instruction: str | None,
    strategy_bundle_payload: dict[str, object],
    reference_article_payload: dict[str, object],
    generator,
    candidate_title: str,
    candidate_body_markdown: str,
) -> tuple[str, str]:
    current_title = candidate_title
    current_markdown = candidate_body_markdown
    target_word_count = tone_profile.target_word_count

    for _ in range(_creative_quality_retry_max_attempts()):
        if not _should_retry_for_positive_payoff(
            strategy_bundle_payload=strategy_bundle_payload,
            candidate_markdown=current_markdown,
            target_word_count=target_word_count,
        ):
            return current_markdown, current_title

        retry_result = generator.generate_draft(
            _build_nested_draft_retry_payload(
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
                "polish_instruction": _build_positive_payoff_retry_instruction(
                    strategy_bundle_payload=strategy_bundle_payload,
                    candidate_markdown=current_markdown,
                    base_instruction=polish_instruction,
                    target_word_count=target_word_count,
                ),
                "allow_structure_recomposition": False,
                "preserve_structure_anchors": True,
                "focused_quality_retry_mode": True,
                "draft": {
                    "title": current_title,
                    "body_markdown": current_markdown,
                },
                **strategy_bundle_payload,
                **reference_article_payload,
                },
                generator=generator,
            )
        )
        retried_title = str(retry_result["title"])
        retried_markdown = str(retry_result["body_markdown"])
        if _positive_payoff_candidate_rank(
            strategy_bundle_payload=strategy_bundle_payload,
            candidate_markdown=retried_markdown,
            target_word_count=target_word_count,
        ) < _positive_payoff_candidate_rank(
            strategy_bundle_payload=strategy_bundle_payload,
            candidate_markdown=current_markdown,
            target_word_count=target_word_count,
        ):
            current_title = retried_title
            current_markdown = retried_markdown

    return current_markdown, current_title


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
            _build_nested_draft_retry_payload(
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
                },
                generator=generator,
            )
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


def _looks_like_scene_first_progression_candidate(markdown: str) -> bool:
    paragraphs = _extract_non_heading_paragraphs(markdown)
    if len(paragraphs) < 4:
        return False

    opening_blocks = paragraphs[:3]
    scene_time_markers = (
        "第二天",
        "清晨",
        "早上",
        "傍晚",
        "夜里",
        "周一早会开始前",
        "散会以后",
        "午休回来",
        "雨停以后",
        "回到家",
        "送孩子",
        "出门前",
        "车来了",
        "推开门",
        "会议已经结束",
        "消息发出去时",
    )
    scene_action_markers = (
        "推开门",
        "放下",
        "放在",
        "坐下来",
        "坐在原位",
        "站在",
        "听见",
        "看见",
        "看着",
        "盯着",
        "压回",
        "换鞋",
        "进门",
        "翻了一页",
        "低头",
        "上去",
        "拉了拉",
        "问了一句",
        "响了一下",
        "删过",
        "发成私聊",
        "咽回去",
        "收住",
        "停在",
        "刷卡",
        "进站",
    )
    scene_object_markers = (
        "餐桌",
        "厨房",
        "屋子",
        "手机屏幕",
        "药盒",
        "检查单",
        "茶几",
        "玄关",
        "会议",
        "投影幕布",
        "咖啡",
        "资料",
        "屏幕",
        "水杯",
        "地铁口",
        "接驳车",
        "围巾",
        "窗户",
        "白雾",
        "输入框",
        "私聊",
        "消息框",
    )
    early_explainer_markers = (
        "很多人",
        "关系里",
        "其实",
        "说到底",
        "人总是这样",
        "我们总以为",
    )

    scene_like_blocks = 0
    early_explainer_hits = 0

    for index, block in enumerate(opening_blocks):
        time_hits = sum(1 for marker in scene_time_markers if marker in block)
        action_hits = sum(1 for marker in scene_action_markers if marker in block)
        object_hits = sum(1 for marker in scene_object_markers if marker in block)
        if (time_hits >= 1 and action_hits >= 1) or (action_hits >= 1 and object_hits >= 1):
            scene_like_blocks += 1
        if index < 2 and any(marker in block for marker in early_explainer_markers):
            early_explainer_hits += 1

    if scene_like_blocks < 2:
        return False
    if early_explainer_hits >= 2:
        return False

    summary = evaluate_ai_flavor_risk(title="tracked-scene-first-check", body_markdown=markdown)
    if summary.score > 18:
        return False
    if extract_not_ab_skeletons(markdown):
        return False
    if len(extract_generic_reflective_openers(markdown)) >= 2:
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
    residual_orphaned_rebound_tails = extract_orphaned_rebound_tails(candidate_markdown)
    residual_short_judgments = extract_short_judgment_paragraphs(candidate_markdown)
    residual_cadence_pairs = count_short_long_cadence_pairs(candidate_markdown)
    residual_embedded_banners = extract_embedded_banner_paragraphs(candidate_markdown)
    residual_quote_paragraphs = extract_isolated_quote_paragraphs(candidate_markdown)
    residual_explanatory_paragraphs = extract_explanatory_bridge_paragraphs(candidate_markdown)
    residual_yi_cadence = len(_extract_clause_leading_yi_phrases(candidate_markdown))
    explainer_shell_hits = [
        hit
        for hit in candidate_summary.hits
        if "第二人称整篇讲解密度偏高" in hit or "中长段整篇过于齐整" in hit
    ]
    opening_explainer_hits = [
        hit for hit in candidate_summary.hits if "开头讲稿式先答后证" in hit
    ]
    if candidate_summary.score < 20:
        if residual_yi_cadence >= 6:
            return True
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
            and residual_yi_cadence < 6
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
    if residual_yi_cadence >= 6:
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
    if residual_yi_cadence >= 5 and (
        candidate_summary.score >= 20 and candidate_summary.score >= source_summary.score + 4
    ):
        return True
    if (
        len(residual_short_judgments) >= 3
        or residual_cadence_pairs >= 1
        or len(residual_embedded_banners) >= 2
        or len(residual_quote_paragraphs) >= 2
        or len(residual_explanatory_paragraphs) >= 2
        or residual_yi_cadence >= 5
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
    if _has_unbalanced_quote_fusion_signal(candidate_markdown):
        return True
    candidate_summary = evaluate_ai_flavor_risk(title=candidate_title, body_markdown=candidate_markdown)
    residual_not_ab = extract_not_ab_skeletons(candidate_markdown)
    residual_openers = extract_generic_reflective_openers(candidate_markdown)
    residual_cliches = extract_growth_cliches(candidate_markdown)
    residual_rebound_tails = extract_rebound_explainer_tails(candidate_markdown)
    residual_orphaned_rebound_tails = extract_orphaned_rebound_tails(candidate_markdown)
    residual_truncated_fragments = extract_truncated_fragment_paragraphs(candidate_markdown)
    residual_short_judgments = extract_short_judgment_paragraphs(candidate_markdown)
    residual_cadence_pairs = count_short_long_cadence_pairs(candidate_markdown)
    residual_embedded_banners = extract_embedded_banner_paragraphs(candidate_markdown)
    residual_quote_paragraphs = extract_isolated_quote_paragraphs(candidate_markdown)
    residual_explanatory_paragraphs = extract_explanatory_bridge_paragraphs(candidate_markdown)
    residual_yi_cadence = len(_extract_clause_leading_yi_phrases(candidate_markdown))
    repeated_quote_paragraphs = len(residual_quote_paragraphs) if len(residual_quote_paragraphs) >= 2 else 0
    repeated_explanatory_paragraphs = (
        len(residual_explanatory_paragraphs) if len(residual_explanatory_paragraphs) >= 2 else 0
    )
    residual_total = (
        len(residual_not_ab)
        + len(residual_openers)
        + len(residual_cliches)
        + len(residual_rebound_tails)
        + len(residual_orphaned_rebound_tails)
        + len(residual_truncated_fragments)
    )
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
        and residual_yi_cadence < 5
        and any("解释连接词偏多" in hit for hit in candidate_summary.hits)
        and candidate_summary.score <= 18
    )
    yi_cadence_only_residue = (
        residual_shape_total == 0
        and len(residual_short_judgments) <= 2
        and residual_cadence_pairs == 0
        and len(residual_embedded_banners) == 0
        and residual_yi_cadence >= 5
        and candidate_summary.score <= 34
    )
    minor_residue_only = (
        residual_shape_total == 0
        and len(residual_embedded_banners) == 0
        and len(residual_short_judgments) <= 2
        and residual_cadence_pairs <= 2
        and residual_yi_cadence < 5
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
    if residual_orphaned_rebound_tails:
        return True
    if residual_truncated_fragments:
        return True
    if connector_only_residue or minor_residue_only:
        return False
    if yi_cadence_only_residue:
        return True
    if (
        residual_shape_total == 0
        and len(residual_rebound_tails) == 0
        and len(residual_orphaned_rebound_tails) == 0
        and len(residual_truncated_fragments) == 0
        and len(residual_short_judgments) < 2
        and residual_cadence_pairs == 0
        and len(residual_embedded_banners) == 0
        and residual_yi_cadence < 5
    ):
        return False
    if residual_shape_total > 3 and not (allow_four_not_ab_only or allow_five_not_ab_only):
        return False
    if len(residual_not_ab) > 3 and not (allow_four_not_ab_only or allow_five_not_ab_only):
        return False
    if (
        len(residual_openers) > 2
        or len(residual_cliches) > 2
        or len(residual_rebound_tails) > 4
        or len(residual_orphaned_rebound_tails) > 0
        or len(residual_truncated_fragments) > 0
    ):
        return False
    if len(residual_short_judgments) > 4 or residual_cadence_pairs > 2 or residual_yi_cadence > 8:
        return False
    if len(residual_embedded_banners) > 2:
        return False
    if repeated_quote_paragraphs > 2 or repeated_explanatory_paragraphs > 2:
        return False
    return True


def _get_strategy_resonance_targets(
    strategy_bundle_payload: Mapping[str, object],
) -> tuple[str, str, str, str, str]:
    problem_brief = strategy_bundle_payload.get("problem_brief")
    strategy_card = strategy_bundle_payload.get("strategy_card")
    if not isinstance(problem_brief, Mapping) or not isinstance(strategy_card, Mapping):
        return "", "", "", "", ""

    structure_mode = str(strategy_card.get("structure_mode") or "").strip()
    emotional_value_goal = str(problem_brief.get("emotional_value_goal") or "").strip()
    positive_direction = str(strategy_card.get("positive_direction") or "").strip()
    quotable_line_goal = str(strategy_card.get("quotable_line_goal") or "").strip()
    packaging_focus = str(strategy_card.get("packaging_focus") or "").strip()
    return structure_mode, emotional_value_goal, positive_direction, quotable_line_goal, packaging_focus


def _get_strategy_contract_targets(strategy_bundle_payload: Mapping[str, object]) -> dict[str, object]:
    problem_brief = strategy_bundle_payload.get("problem_brief")
    strategy_card = strategy_bundle_payload.get("strategy_card")
    if not isinstance(problem_brief, Mapping) or not isinstance(strategy_card, Mapping):
        return {
            "theme_axis": "",
            "anti_drift_axis": "",
            "scene_anchor_requirements": [],
            "realism_texture_goal": "",
            "quotable_line_seeds": [],
            "packaging_hook": "",
        }

    scene_anchor_requirements_value = strategy_card.get("scene_anchor_requirements")
    quotable_line_seeds_value = strategy_card.get("quotable_line_seeds")
    writing_texture_notes_value = strategy_card.get("writing_texture_notes")
    writing_texture_notes = (
        [str(item).strip() for item in writing_texture_notes_value if str(item).strip()]
        if isinstance(writing_texture_notes_value, list)
        else []
    )
    scene_anchor_requirements = (
        [str(item).strip() for item in scene_anchor_requirements_value if str(item).strip()]
        if isinstance(scene_anchor_requirements_value, list)
        else []
    )
    quotable_line_seeds = (
        [str(item).strip() for item in quotable_line_seeds_value if str(item).strip()]
        if isinstance(quotable_line_seeds_value, list)
        else []
    )
    return {
        "theme_axis": str(problem_brief.get("theme_axis") or "").strip(),
        "anti_drift_axis": str(problem_brief.get("anti_drift_axis") or "").strip(),
        "writing_texture_notes": writing_texture_notes,
        "scene_anchor_requirements": scene_anchor_requirements,
        "realism_texture_goal": str(strategy_card.get("realism_texture_goal") or "").strip(),
        "quotable_line_seeds": quotable_line_seeds,
        "packaging_hook": str(strategy_card.get("packaging_hook") or "").strip(),
    }


def _positive_direction_markers(structure_mode: str) -> tuple[str, ...]:
    mapping: dict[str, tuple[str, ...]] = {
        "everyday_warmth_return": ("日子", "生活", "陪伴", "家人", "人间烟火", "平安", "温暖", "已经拥有"),
        "responsibility_shelter": ("责任", "家里", "安排", "顺序", "灯", "热气", "安稳", "托住"),
        "inner_settlement": ("心安", "放平", "安顿", "回到今天", "从容", "静下来", "和解"),
        "self_reliance_inward_support": ("托住", "稳住", "撑过去", "把自己", "运转起来", "自救", "自渡"),
        "self_worth_rebuild": ("边界", "门槛", "标准", "体面", "尊重自己", "把自己放回前面", "不再将就", "养贵"),
        "response_priority": ("顺序", "时间", "收回来", "值得", "优先", "留给自己", "读懂", "理解", "被看见", "安稳", "珍惜", "接住"),
        "supportive_appreciation": ("珍惜", "被珍惜", "温柔", "牵紧", "值得", "尊重"),
        "relationship_aftercare": ("修复", "回来", "沟通", "接住", "继续走下去", "态度"),
        "resilience_reconstruction": ("重建", "继续", "不被定义", "向前", "站起来"),
        "emotional_engine_direct": ("安放", "收好", "放回过去", "想起也没关系", "今天重新过好", "一点点亮起来", "感谢相遇", "不谈亏欠", "继续往前"),
        "scene_first_progression": ("认出", "看清", "往前", "还有路", "终于"),
        "pressure_interface_direct": ("排序", "照顾自己", "回到生活", "看见", "慢下来"),
    }
    return mapping.get(structure_mode, ("往前", "温暖", "稳住", "继续"))


def _packaging_focus_markers(structure_mode: str) -> tuple[str, ...]:
    mapping: dict[str, tuple[str, ...]] = {
        "everyday_warmth_return": ("大事", "小事", "简单快乐", "家人", "平安", "知己", "人间烟火"),
        "responsibility_shelter": ("责任", "来电", "电话", "日历", "安排", "顺序", "家里", "托住"),
        "inner_settlement": (
            "心安",
            "放平",
            "从容",
            "归处",
            "和解",
            "安顿",
            "半年",
            "年初",
            "计划",
            "清单",
            "阶段",
            "重新出发",
        ),
        "self_reliance_inward_support": ("向内求", "自救", "自渡", "靠自己", "托住", "稳住"),
        "self_worth_rebuild": ("养贵", "边界", "门槛", "标准", "体面", "尊重自己", "将就", "放轻"),
        "response_priority": ("没时间", "优先", "顺序", "回应", "在乎", "时间在哪儿", "评论", "追问", "读懂", "理解", "被看见", "安稳"),
        "supportive_appreciation": ("心软", "柔软", "珍惜", "牵紧", "包容"),
        "relationship_aftercare": ("吵架", "冷暴力", "修复", "回来", "态度"),
        "resilience_reconstruction": ("韧性", "重建", "训练", "命运", "不被定义"),
        "emotional_engine_direct": ("背影", "擦肩", "旧相册", "聊天记录", "回潮", "普通时刻", "想起", "安放", "感谢相遇", "不谈亏欠", "聚散", "过客"),
        "scene_first_progression": ("地铁口", "会议室", "现场", "那句话", "没问出口"),
        "pressure_interface_direct": ("体检", "复查", "代价", "提醒", "排序"),
    }
    return mapping.get(structure_mode, ())


def _strategy_contract_keywords(text: str) -> tuple[str, ...]:
    normalized = str(text or "").strip()
    if not normalized:
        return ()
    keyword_groups: list[str] = []
    if "阶段节点" in normalized or any(token in normalized for token in ("上半年", "下半年", "这半年", "年初", "清单", "目标", "计划")):
        keyword_groups.extend(["上半年", "下半年", "这半年", "年初", "清单", "目标", "计划", "阶段"])
    if "回应接口" in normalized or "回应顺序" in normalized or "碎片时间" in normalized or any(
        token in normalized for token in ("没时间", "顺序", "时间给了谁", "回消息", "电话", "点赞", "评论", "追问", "接住", "回复", "读懂", "理解", "被看见", "安稳", "补问")
    ):
        keyword_groups.extend(["没时间", "顺序", "时间", "回消息", "回复", "电话", "点赞", "评论", "追问", "接住", "红灯", "秒", "读懂", "理解", "看见", "安稳", "补问"])
    if "家里日常" in normalized or "陪伴动作" in normalized or any(
        token in normalized for token in ("晚饭", "散步", "回家", "放学", "灯火", "陪伴", "家里")
    ):
        keyword_groups.extend(["晚饭", "散步", "回家", "放学", "灯", "家里", "孩子", "父母", "爱人", "爷爷"])
    if "现实承压接口" in normalized or "向内托住" in normalized or any(
        token in normalized for token in ("托住", "稳住", "撑过去", "今天过完", "日子接回来", "靠自己")
    ):
        keyword_groups.extend(["托住", "稳住", "撑过去", "今天", "日子", "靠自己", "自己"])
    if "自我价值" in normalized or "边界" in normalized or any(
        token in normalized
        for token in ("都可以", "算了", "我没事", "不方便", "改约", "边界", "门槛", "标准", "体面", "尊重自己", "养贵")
    ):
        keyword_groups.extend(
            ["都可以", "算了", "我没事", "不方便", "改约", "边界", "门槛", "标准", "体面", "尊重自己", "养贵", "将就", "放轻"]
        )
    if "身体提醒" in normalized or any(
        token in normalized for token in ("体检", "复查", "医院", "手术", "训练", "疼痛", "炎症", "报警", "代价")
    ):
        keyword_groups.extend(["体检", "复查", "医院", "手术", "训练", "疼痛", "炎症", "身体", "报警", "代价"])
    if "争执后空" in normalized or any(token in normalized for token in ("吵完", "争执", "冷暴力", "修复", "回来善后", "沉默")):
        keyword_groups.extend(["吵架", "争执", "冷暴力", "修复", "回来", "沉默", "失望"])
    if "柔软被误读" in normalized or any(token in normalized for token in ("心软", "柔软", "珍惜", "牵紧", "包容")):
        keyword_groups.extend(["心软", "柔软", "珍惜", "牵紧", "包容", "对不起"])
    if "连续现场" in normalized or any(token in normalized for token in ("现场", "会议", "当场", "没说出口", "补救")):
        keyword_groups.extend(["现场", "会议", "当场", "没说出口", "补救", "那句话"])
    if "误判" in normalized or any(token in normalized for token in ("回神", "误认", "原来", "后来才发现")):
        keyword_groups.extend(["误判", "回神", "原来", "后来", "发现"])
    if "现实接口" in normalized:
        keyword_groups.extend(["消息", "电话", "晚饭", "体检", "会议", "清单", "目标", "房租", "手机", "沙发"])
    deduped: list[str] = []
    for item in keyword_groups:
        if item and item not in deduped:
            deduped.append(item)
    return tuple(deduped)


def _count_strategy_scene_anchor_hits(
    candidate_markdown: str,
    scene_anchor_requirements: list[str],
) -> int:
    if not scene_anchor_requirements:
        return 0
    paragraphs = _extract_non_heading_paragraphs(candidate_markdown)[:6]
    if not paragraphs:
        return 0
    leading_text = "\n".join(paragraphs)
    hits = 0
    for requirement in scene_anchor_requirements:
        keywords = _strategy_contract_keywords(requirement)
        if keywords and any(keyword in leading_text for keyword in keywords):
            hits += 1
    return hits


_STRUCTURE_MODE_DRIFT_GUARDS: dict[str, tuple[str, ...]] = {
    "everyday_warmth_return": (
        "体检",
        "复查",
        "手术",
        "身体提醒",
        "代价",
        "报警",
        "待办",
        "没时间",
        "回消息",
        "回复",
        "顺序",
        "冷暴力",
        "吵架",
        "修复",
        "善后",
    ),
    "self_reliance_inward_support": (
        "没时间",
        "回消息",
        "回复",
        "顺序",
        "点赞",
        "红灯",
        "冷暴力",
        "吵架",
        "修复",
        "善后",
        "大富大贵",
        "香车美宅",
        "知己二三",
    ),
    "self_worth_rebuild": (
        "没时间",
        "回消息",
        "回复",
        "顺序",
        "点赞",
        "红灯",
        "谁先回头",
        "冷暴力",
        "吵架",
        "修复",
        "善后",
        "打了又删",
        "说不出口",
        "感谢相遇",
        "不谈亏欠",
        "聚散",
        "过客",
    ),
}


def _count_structure_mode_focus_hits(candidate_markdown: str, structure_mode: str) -> int:
    markers = _packaging_focus_markers(structure_mode)
    if not markers:
        return 0
    return sum(1 for marker in markers if marker in candidate_markdown)


def _has_structure_mode_drift(
    *,
    structure_mode: str,
    candidate_markdown: str,
) -> bool:
    drift_tokens = _STRUCTURE_MODE_DRIFT_GUARDS.get(structure_mode)
    if not drift_tokens:
        return False
    bleed_hits = sum(1 for token in drift_tokens if token in candidate_markdown)
    if bleed_hits < 2:
        return False
    focus_hits = _count_structure_mode_focus_hits(candidate_markdown, structure_mode)
    return bleed_hits > focus_hits


def _has_strategy_packaging_hook(
    values: list[str],
    packaging_hook: str,
) -> bool:
    keywords = _strategy_contract_keywords(packaging_hook)
    if not keywords:
        return True
    combined = "\n".join(value for value in values if value)
    if not combined:
        return False
    return any(keyword in combined for keyword in keywords)


def _has_responsibility_shelter_packaging_floor(values: list[str]) -> bool:
    combined = "\n".join(value for value in values if value)
    if not combined:
        return False
    title_hits = sum(
        1
        for token in ("责任", "电话", "日历", "顺序", "家里", "托稳", "安稳", "灯")
        if token in combined
    )
    family_hits = sum(1 for token in ("父母", "爸妈", "孩子", "家里", "一家人", "家人") if token in combined)
    payoff_hits = sum(1 for token in ("安稳", "踏实", "托稳", "安心", "底气", "留一盏灯") if token in combined)
    return title_hits >= 2 and family_hits >= 1 and payoff_hits >= 1


def _has_strategy_positive_landing(
    *,
    structure_mode: str,
    candidate_markdown: str,
) -> bool:
    paragraphs = _extract_non_heading_paragraphs(candidate_markdown)
    if not paragraphs:
        return False
    tail_text = "\n".join(paragraphs[-3:])
    markers = _positive_direction_markers(structure_mode)
    if not any(marker in tail_text for marker in markers):
        return False

    # Broad words such as "生活" or "继续" can appear in an unresolved
    # conclusion. Require one concrete landing marker so the payoff is tied
    # to this article's theme rather than passing on generic encouragement.
    concrete_markers: dict[str, tuple[str, ...]] = {
        "everyday_warmth_return": ("家人", "陪伴", "平安", "温暖", "人间烟火", "已经拥有", "安稳"),
        "inner_settlement": ("心安", "安顿", "从容", "和解", "归处"),
        "self_reliance_inward_support": ("自己", "自救", "自渡", "托住", "稳住"),
        "self_worth_rebuild": ("边界", "门槛", "标准", "体面", "尊重自己", "不再将就"),
        "response_priority": ("理解", "被看见", "留给自己", "值得", "安稳", "珍惜"),
        "supportive_appreciation": ("被珍惜", "温柔", "牵紧", "包容", "尊重"),
        "relationship_aftercare": ("修复", "沟通", "接住", "继续走下去", "态度"),
        "resilience_reconstruction": ("重建", "不被定义", "站起来", "向前"),
    }
    concrete = concrete_markers.get(structure_mode)
    return any(marker in tail_text for marker in concrete) if concrete else True


def _has_repetitive_structural_cues(candidate_markdown: str) -> bool:
    paragraphs = _extract_non_heading_paragraphs(candidate_markdown)
    if len(paragraphs) < 10:
        return False
    cue_counts = Counter()
    text = "\n".join(paragraphs)
    cue_patterns = {
        "先": r"先(?!生)",
        "然后": r"然后",
        "于是": r"于是",
        "慢慢": r"慢慢",
        "后来": r"后来",
        "其实": r"其实",
        "只是": r"只是",
    }
    for cue, pattern in cue_patterns.items():
        cue_counts[cue] = len(re.findall(pattern, text))
    threshold = max(6, int(len(paragraphs) * 0.35))
    return any(count >= threshold for count in cue_counts.values())


def _has_obvious_repeated_character(candidate_markdown: str) -> bool:
    natural_repeats = set("人人时时年年天天慢慢渐渐常常往往处处点点件件层层阵阵")
    return any(
        match.group(1) not in natural_repeats
        for match in re.finditer(r"([\u4e00-\u9fff])\1", candidate_markdown)
    )


def _has_unfinished_dialogue_sentence(candidate_markdown: str) -> bool:
    for paragraph in _extract_non_heading_paragraphs(candidate_markdown):
        normalized = paragraph.strip()
        if normalized.endswith(("”", '"', "’", "'")) and not normalized.endswith(("。”", "！ ”", "！”", "？ ”", '。”', '！”', '？”')):
            return True
    return False


def _has_author_meta_commentary(candidate_markdown: str) -> bool:
    normalized = re.sub(r"\s+", "", candidate_markdown)
    return bool(
        re.search(
            r"(?:这篇(?:文章|稿子)?(?:不是想|想说|要讲)|本文(?:想说|主要讲)|作者(?:想说|认为)|我想说的是)",
            normalized,
        )
    )


def _positive_payoff_candidate_rank(
    *,
    strategy_bundle_payload: Mapping[str, object],
    candidate_markdown: str,
    target_word_count: int,
) -> tuple[int, int, int, int, int]:
    structure_mode, _, positive_direction, quotable_line_goal, _ = _get_strategy_resonance_targets(
        strategy_bundle_payload
    )
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    scene_requirements = contract_targets["scene_anchor_requirements"]
    required_scene_hits = 2 if len(scene_requirements) >= 2 else 1 if scene_requirements else 0
    hard_defects = sum(
        (
            _has_obvious_repeated_character(candidate_markdown),
            _has_unfinished_dialogue_sentence(candidate_markdown),
            _has_author_meta_commentary(candidate_markdown),
            len(extract_not_ab_skeletons(candidate_markdown)) > 1,
            _has_structure_mode_drift(structure_mode=structure_mode, candidate_markdown=candidate_markdown),
        )
    )
    contract_defects = sum(
        (
            bool(positive_direction)
            and not _has_strategy_positive_landing(
                structure_mode=structure_mode,
                candidate_markdown=candidate_markdown,
            ),
            bool(quotable_line_goal) and not extract_short_judgment_paragraphs(candidate_markdown),
            required_scene_hits > 0
            and _count_strategy_scene_anchor_hits(candidate_markdown, scene_requirements) < required_scene_hits,
            len(extract_generic_reflective_openers(candidate_markdown)) >= 2,
            _has_repetitive_structural_cues(candidate_markdown),
        )
    )
    compact_length = len(re.sub(r"\s+", "", candidate_markdown))
    minimum_content_length = max(650, int(target_word_count * 0.65)) if target_word_count > 0 else 0
    length_deficit = max(0, minimum_content_length - compact_length)
    ai_score = evaluate_ai_flavor_risk(title="", body_markdown=candidate_markdown).score
    return hard_defects, contract_defects, length_deficit, ai_score, -compact_length


def _should_retry_for_positive_payoff(
    *,
    strategy_bundle_payload: Mapping[str, object],
    candidate_markdown: str,
    target_word_count: int = 0,
) -> bool:
    structure_mode, emotional_value_goal, positive_direction, quotable_line_goal, _ = _get_strategy_resonance_targets(
        strategy_bundle_payload
    )
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    scene_anchor_requirements = contract_targets["scene_anchor_requirements"]
    if not any(
        (
            structure_mode,
            emotional_value_goal,
            positive_direction,
            quotable_line_goal,
            contract_targets["theme_axis"],
            contract_targets["anti_drift_axis"],
            contract_targets["realism_texture_goal"],
            contract_targets["packaging_hook"],
            scene_anchor_requirements,
        )
    ):
        return False

    missing_positive_landing = bool(positive_direction) and not _has_strategy_positive_landing(
        structure_mode=structure_mode,
        candidate_markdown=candidate_markdown,
    )
    short_judgments = extract_short_judgment_paragraphs(candidate_markdown)
    missing_quotable_line = bool(quotable_line_goal) and not short_judgments
    required_scene_hits = 2 if len(scene_anchor_requirements) >= 2 else 1 if scene_anchor_requirements else 0
    scene_anchor_hits = _count_strategy_scene_anchor_hits(candidate_markdown, scene_anchor_requirements)
    missing_scene_anchor = required_scene_hits > 0 and scene_anchor_hits < required_scene_hits
    opening_generic = len(extract_generic_reflective_openers(candidate_markdown)) >= 2
    repetitive_structural_cues = _has_repetitive_structural_cues(candidate_markdown)
    repeated_character = _has_obvious_repeated_character(candidate_markdown)
    excessive_not_ab_skeletons = len(extract_not_ab_skeletons(candidate_markdown)) > 1
    unfinished_dialogue_sentence = _has_unfinished_dialogue_sentence(candidate_markdown)
    author_meta_commentary = _has_author_meta_commentary(candidate_markdown)
    structure_mode_drift = _has_structure_mode_drift(
        structure_mode=structure_mode,
        candidate_markdown=candidate_markdown,
    )
    compact_length = len(re.sub(r"\s+", "", candidate_markdown))
    minimum_content_length = max(650, int(target_word_count * 0.65)) if target_word_count > 0 else 0
    missing_content_depth = minimum_content_length > 0 and compact_length < minimum_content_length
    return (
        missing_positive_landing
        or missing_content_depth
        or missing_quotable_line
        or missing_scene_anchor
        or opening_generic
        or repetitive_structural_cues
        or repeated_character
        or excessive_not_ab_skeletons
        or unfinished_dialogue_sentence
        or author_meta_commentary
        or structure_mode_drift
    )


def _build_positive_payoff_retry_instruction(
    *,
    strategy_bundle_payload: Mapping[str, object],
    candidate_markdown: str,
    base_instruction: str | None,
    target_word_count: int = 0,
) -> str:
    structure_mode, emotional_value_goal, positive_direction, quotable_line_goal, _ = _get_strategy_resonance_targets(
        strategy_bundle_payload
    )
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    scene_anchor_requirements = contract_targets["scene_anchor_requirements"]
    notes: list[str] = []
    if base_instruction:
        notes.append(str(base_instruction).strip())
    if contract_targets["theme_axis"]:
        notes.append(f"主题主线继续守住：{contract_targets['theme_axis']}")
    if contract_targets["anti_drift_axis"]:
        notes.append(f"不要再漂去：{contract_targets['anti_drift_axis']}")
    if emotional_value_goal:
        notes.append(f"这次必须把读者真正带到这个情绪回报：{emotional_value_goal}")
    if positive_direction and not _has_strategy_positive_landing(
        structure_mode=structure_mode,
        candidate_markdown=candidate_markdown,
    ):
        notes.append(f"结尾现在还不够回正，请把最后两段明确收回这里：{positive_direction}")
    compact_length = len(re.sub(r"\s+", "", candidate_markdown))
    minimum_content_length = max(650, int(target_word_count * 0.65)) if target_word_count > 0 else 0
    if minimum_content_length > 0 and compact_length < minimum_content_length:
        notes.append(
            f"当前正文只有约 {compact_length} 字，信息和情绪推进不足；在不拉长段落的前提下补到至少 {minimum_content_length} 字，"
            "新增一层现实阻力、一层家人反馈和一处情绪回收，不要靠重复观点凑字数。"
        )
    required_scene_hits = 2 if len(scene_anchor_requirements) >= 2 else 1 if scene_anchor_requirements else 0
    scene_anchor_hits = _count_strategy_scene_anchor_hits(candidate_markdown, scene_anchor_requirements)
    if required_scene_hits > 0 and scene_anchor_hits < required_scene_hits:
        notes.append(f"前六段补回这些现实抓手：{' / '.join(scene_anchor_requirements)}")
    if contract_targets["realism_texture_goal"] and len(extract_generic_reflective_openers(candidate_markdown)) >= 2:
        notes.append(f"开头现在还是太像讲稿，请按这个真实质感重写前屏：{contract_targets['realism_texture_goal']}")
    if _has_structure_mode_drift(structure_mode=structure_mode, candidate_markdown=candidate_markdown):
        notes.append("这版正文已经被别的题型词汇带偏了，请把重心拉回当前主题，不要滑成身体告警、关系回应排序或争执善后稿。")
    if _has_repetitive_structural_cues(candidate_markdown):
        notes.append("这版正文的动作推进词重复过密，尤其不要连续用‘先、然后、于是、慢慢’排队推进；保留必要动作，其余改成不同的观察、停顿或后果，让句子像真人在回忆一件事。")
    if _has_obvious_repeated_character(candidate_markdown):
        notes.append("发现疑似重复字或词，请逐句检查模型输出的残字，例如‘接住住’这类错误必须直接修掉。")
    if len(extract_not_ab_skeletons(candidate_markdown)) > 1:
        notes.append("对照句已经超过一处，不要继续使用‘不是A，是B’的整齐翻转；把其中一处改回具体动作、关系反馈或现实后果。")
    if _has_unfinished_dialogue_sentence(candidate_markdown):
        notes.append("发现一句话停在引号上没有收口，请补完整的说话动作或句号，不要留下像模型截断的半句对话。")
    if _has_author_meta_commentary(candidate_markdown):
        notes.append("删掉‘这篇想说、本文、作者想说’等创作说明，让观点直接从场景、动作和关系反馈里成立，不要让作者跳出来解释文章。")
    if quotable_line_goal and not extract_short_judgment_paragraphs(candidate_markdown):
        notes.append(f"前半篇或中后段补 1 处自然长出来的短句，要求满足：{quotable_line_goal}")
        quotable_line_seeds = contract_targets["quotable_line_seeds"]
        if quotable_line_seeds:
            notes.append(f"这句优先从这些地方长出来：{' / '.join(quotable_line_seeds)}")
    notes.append("不要把整篇重写成鸡汤稿，只补足回正落点和一句像人话的短判断。")
    return " ".join(note for note in notes if note).strip()


def _looks_like_packaging_title_judgment_template(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip())
    if not normalized or len(normalized) > 48:
        return False
    return bool(re.search(r"不是[^。！？!?；;\n]{1,24}(?:而是|只是|就是|(?<!不)是)[^。！？!?；;\n]{1,32}", normalized))


def _looks_like_explanatory_packaging_title(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip())
    if not normalized or len(normalized) < 24:
        return any(token in normalized for token in ("有一种人", "总有一种人", "相信你也有过这样的时刻"))
    if len(normalized) > 42:
        return True
    return bool(
        re.search(r"[，,：:；;].{8,}", normalized)
        or any(token in normalized for token in ("为什么", "怎么", "如何", "其实", "原来", "后来", "一直", "总是"))
    )


def _looks_like_explanatory_responsibility_shelter_title(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip())
    if not normalized:
        return False
    if _looks_like_packaging_title_judgment_template(normalized):
        return True
    if any(
        token in normalized
        for token in (
            "中年人的世界",
            "才懂自己认真走着什么",
            "认真走着什么",
            "先翻日历的人",
            "还在把家托稳",
            "电话一响，才懂",
            "电话一响才懂",
        )
    ):
        return True
    if len(normalized) < 24:
        return False
    return any(
        token in normalized
        for token in (
            "多想一步的人",
            "把你推成了",
            "总想先把家里安排稳",
            "总是怎么把家里稳住",
            "总会先把家里理顺",
            "不只是因为能扛",
            "为什么会先成为你的优先级",
            "为什么会先成了你的优先级",
            "最不敢倒下的人",
            "后来为什么会变成那个",
            "更不敢说自己累",
            "挂在嘴边的人",
            "先把家里理顺",
            "说自己累",
            "代价其实是",
            "一再往后放",
            "先把家里安顿好",
            "总想先把家里安顿好",
            "久了最容易被忽略",
            "需要被接住",
            "承担本身",
            "被忽略的，是",
            "家里的事往前放",
            "我来处理",
            "我来安排",
            "累却都留在你身上",
            "后来家里安稳了",
            "安稳了，累",
            "总把自己排在最后",
            "先把家里理顺",
            "代价不只是累",
            "长期不敢乱",
            "更需要你先留一点余地",
            "定心骨",
            "定盘星",
        )
    )


def _strip_responsibility_title_label(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^\s*#+\s*", "", cleaned)
    cleaned = re.sub(r"^\s*(?:title|标题)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^\s*(?:\d+\s*[\.\)：:]?\s*)?(?:\*{1,2}\s*)?(?:标题|title)(?:\s+title)?(?:\s*\*{1,2})?\s*[:：]?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _starts_with_generic_packaging_openers(text: str) -> bool:
    normalized = re.sub(r"^[\s#>*\-—·•「『“”\"'《【（(]+", "", text.strip())
    return normalized.startswith(
        (
            "很多人",
            "有些人",
            "总有人",
            "不少人",
            "大多数人",
            "这篇",
            "我们总以为",
            "人这一生",
            "人总会",
            "人总是",
            "先抓",
            "包装优先",
            "标题、导语",
            "标题和开头",
            "开头先",
        )
    )


def _has_generic_packaging_openers(values: list[str]) -> bool:
    return any(_starts_with_generic_packaging_openers(value) for value in values if value)


def _looks_like_packaging_instruction_leakage(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip())
    if not normalized:
        return False
    if normalized.startswith(("先抓", "包装优先", "标题、导语", "标题和开头", "开头先")):
        return True
    if normalized.startswith(("围绕《", "围绕参考文章", "围绕参考", "重建新的具体入口", "更贴近真人表达")):
        return True
    if any(
        token in normalized
        for token in (
            "现场接口",
            "现实接口",
            "回应接口",
            "轻互动接口",
            "承压接口",
            "阶段节点接口",
            "陪伴动作接口",
            "身体提醒接口",
            "日常回温接口",
            "回稳接口",
            "重建新的具体入口",
            "更贴近真人表达",
        )
    ):
        return True
    if re.search(r"^这篇(?:文章|稿子)[^。！？!?\n]{0,120}(?:切入|要讲|抓住|核心答案|发布抓手)", normalized):
        return True
    if re.search(r"^(?:围绕《[^》]+》|围绕参考文章|围绕参考)[^。！？!?\n]{0,180}(?:切入|重建新的具体入口|更贴近真人表达)", normalized):
        return True
    return bool(
        re.search(
            r"^从[^。！？!?\n]{0,140}(?:切入|写起)[，,；;]?(?:再|中段|结尾|最后)?(?:写|讲|拆|说明|交代|点出|也写|写真正|写出)",
            normalized,
        )
    )


def _has_packaging_instruction_leakage(values: list[str]) -> bool:
    return any(_looks_like_packaging_instruction_leakage(value) for value in values if value)


def _looks_like_packaging_meta_text(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip())
    if not normalized:
        return False
    return bool(
        re.search(
            r"(?:文章(?:写的(?:正是|是)?|想写的|想说的|写透|写清楚|讲清楚)|这篇(?:文章|稿子)?(?:写的是|写的|想讲的是|想写的|想说的|要写的|想写透的)|真正想说的|更想说的是|也想认真说一句|文章从[^。！？!?]{0,80}(?:写起|切入)|文章借[^。！？!?]{0,90}(?:写|讲)|读到最后(?:你会发现)?|本文(?:主要|就是)|作者(?:想说|认为)|稿子(?:写的|要写的|想写的|想说的)|^把[^。！？!?]{0,36}(?:说得多|写得太|写成)[^。！？!?]{0,16}而是|(?:也)?(?:写透|写清楚|讲清楚)[:：]|(?:写|讲)[^。！？!?]{0,40}(?:如何|怎样)|这篇写[^。！？!?]{0,80}|文章真正要(?:落到|说到|写到))",
            normalized,
        )
    )


def _has_packaging_meta_text(values: list[str]) -> bool:
    return any(_looks_like_packaging_meta_text(value) for value in values if value)


def _strip_packaging_editorial_meta_clauses(text: str) -> str:
    original = str(text or "").strip()
    cleaned = original
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"(?:这篇|这篇文章|这篇稿子|文章|稿子)(?:想写的|想说的|要写的)\s*[，,:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:这篇|这篇文章|这篇稿子|文章|稿子)(?:写的|写得)(?:是)?\s*[，,:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"^写的不是[^。！？!?\n]{0,80}?而是\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(^|[；;，,、]\s*)不是一句[“\"']?[^”\"'。！？!?]{0,24}[”\"']?[，,]?\s*而是\s*",
        r"\1",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:这篇|这篇文章|文章)(?:写的|写得)不是[^。！？!?\n]{0,80}?而是\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:真正想说的|更想说的是)\s*[，,:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:这篇|这篇文章|文章)?(?:想)?(?:写透|写清楚|讲清楚)(?:的|的是)?\s*[，,:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:也)?(?:写透|写清楚|讲清楚)\s*[:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:也)?想认真说一句\s*[:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"文章从[^。！？!?\n]{0,90}?(?:写起|切入)[，,]?(?:落到|最后写到|也写到|再落到)[^。！？!?\n]{0,40}[—\-]{1,2}\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"写到最后[，,]?(?:会)?(?:落回|落到|其实会落到)?[^。！？!?\n]{0,40}[—\-]{1,2}\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"讲[^。！？!?\n]{0,90}?(?:如何|为什么|的是|在于|就是)[^。！？!?\n]{0,90}[：:]\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"文章真正要(?:落到|说到|写到)的[，,:：]?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"写中年人[^。！？!?\n]{0,120}?(?:真正意义|真正分量|真正的分量|为什么|怎样)[：:]\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"这篇写[^。！？!?\n]{0,120}?(?:也写|也讲|也会写)?[^。！？!?\n]{0,80}[：:]\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"文章从[^。！？!?\n]{0,90}?(?:写起|切入)[，,]?",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^(?:是|不是|不只是|而是)\s*", "", cleaned)
    cleaned = re.sub(r"^[，,；;：:、\s]+", "", cleaned)
    cleaned = re.sub(r"([。！？!?])\s*([，,；;：:])", r"\1", cleaned)
    cleaned = re.sub(r"([。！？!?])\s{2,}", r"\1 ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if cleaned != original:
        compact = re.sub(r"\s+", "", cleaned)
        concrete_markers = (
            "电话",
            "手机",
            "日历",
            "工位",
            "医院",
            "复查",
            "父母",
            "孩子",
            "账单",
            "晚饭",
            "餐桌",
            "地铁",
            "会议室",
            "回复",
            "评论",
            "晚霞",
            "家里",
            "顺序",
        )
        if compact and len(compact) <= 28 and not any(marker in compact for marker in concrete_markers):
            return ""
    return cleaned.strip()


def _dedupe_safe_packaging_body_options(values: list[str], *, fallback: str = "") -> list[str]:
    safe: list[str] = []
    for value in _dedupe_nonempty_text_options(values):
        if (
            _starts_with_generic_packaging_openers(value)
            or _looks_like_packaging_instruction_leakage(value)
            or _looks_like_packaging_meta_text(value)
        ):
            continue
        safe.append(value)
    normalized_fallback = str(fallback or "").strip()
    if normalized_fallback and normalized_fallback not in safe:
        safe.insert(0, normalized_fallback)
    return safe


def _sanitize_assets_packaging_result(ai_result: Mapping[str, object]) -> dict[str, object]:
    sanitized = dict(ai_result)
    if "cover_copy" in sanitized:
        sanitized["cover_copy"] = re.sub(r"\s+", " ", str(sanitized.get("cover_copy") or "").strip()).strip()
    social_teaser = _strip_packaging_editorial_meta_clauses(str(sanitized.get("social_teaser") or "").strip())
    social_teaser_options_value = sanitized.get("social_teaser_options")
    social_teaser_options = (
        [
            _strip_packaging_editorial_meta_clauses(str(item).strip())
            for item in social_teaser_options_value
            if str(item).strip()
        ]
        if isinstance(social_teaser_options_value, list)
        else []
    )
    safe_teasers = _dedupe_safe_packaging_body_options([social_teaser, *social_teaser_options])
    if not safe_teasers:
        safe_teasers = _dedupe_safe_packaging_body_options([str(sanitized.get("cover_copy") or "").strip()])
    if safe_teasers:
        sanitized["social_teaser"] = safe_teasers[0]
        sanitized["social_teaser_options"] = safe_teasers[:3]
    else:
        sanitized["social_teaser_options"] = []
    return sanitized


def _sanitize_publish_packaging_result(
    ai_result: Mapping[str, object],
    *,
    draft_body_markdown: str,
    assets: AssetItem,
    fallback_title: str,
) -> dict[str, object]:
    sanitized = dict(ai_result)
    publish_lead = _strip_packaging_editorial_meta_clauses(str(sanitized.get("publish_lead") or "").strip())
    intro_options_value = sanitized.get("intro_options")
    intro_options = (
        [
            _strip_packaging_editorial_meta_clauses(str(item).strip())
            for item in intro_options_value
            if str(item).strip()
        ]
        if isinstance(intro_options_value, list)
        else []
    )
    safe_intro_options = _dedupe_safe_packaging_body_options(
        [publish_lead, *intro_options, *assets.social_teaser_options],
        fallback=assets.social_teaser,
    )
    if safe_intro_options:
        sanitized["publish_lead"] = publish_lead if publish_lead in safe_intro_options else safe_intro_options[0]
        sanitized["intro_options"] = safe_intro_options[:4]
    else:
        sanitized["intro_options"] = []

    original_abstract = str(sanitized.get("abstract") or "").strip()
    abstract = _strip_packaging_editorial_meta_clauses(original_abstract)
    if (
        _starts_with_generic_packaging_openers(abstract)
        or _looks_like_packaging_instruction_leakage(abstract)
        or _looks_like_packaging_meta_text(abstract)
    ):
        sanitized["abstract"] = _build_local_publish_abstract(
            body_markdown=draft_body_markdown,
            social_teaser=str(sanitized.get("publish_lead") or assets.social_teaser),
            fallback_title=fallback_title,
        )
    else:
        sanitized["abstract"] = abstract
    return sanitized


def _soften_generic_packaging_opener_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or not _starts_with_generic_packaging_openers(cleaned):
        return str(text or "")
    replacements: tuple[tuple[str, str], ...] = (
        (r"^很多人的(?P<kind>不容易|累|辛苦)", r"这份\g<kind>"),
        (r"^很多成年人", "人到中年"),
        (r"^很多人会", "有时候，心里会"),
        (r"^很多人都", "这些认真"),
        (r"^很多人", "有时候"),
        (r"^有些人", "这样的人"),
        (r"^总有人", "也会有人"),
        (r"^不少人", "有时候"),
        (r"^大多数人", "有时候"),
        (r"^人这一生", "这一生"),
        (r"^人总会", "有时候，人会"),
        (r"^人总是", "有时候，人会"),
    )
    softened = cleaned
    for pattern, replacement in replacements:
        softened = re.sub(pattern, replacement, softened, count=1)
        if softened != cleaned:
            break
    return softened

def _packaging_hits_strategy_focus(
    *,
    structure_mode: str,
    values: list[str],
) -> bool:
    markers = _packaging_focus_markers(structure_mode)
    if not markers:
        return True
    combined = "\n".join(value for value in values if value)
    if not combined:
        return False
    return any(marker in combined for marker in markers)


def _packaging_title_focus_markers(structure_mode: str) -> tuple[str, ...]:
    mapping: dict[str, tuple[str, ...]] = {
        "everyday_warmth_return": ("大事", "小事", "家人", "家里", "日子", "饭桌", "回家", "电话", "安稳"),
        "responsibility_shelter": ("责任", "来电", "电话", "日历", "安排", "顺序", "家里", "托住"),
        "inner_settlement": (
            "心安",
            "放平",
            "从容",
            "归处",
            "安顿",
            "和解",
            "半年",
            "年初",
            "计划",
            "清单",
            "阶段",
            "重新出发",
        ),
        "self_reliance_inward_support": ("向内", "靠自己", "自救", "自渡", "托住", "稳住", "今天"),
        "self_worth_rebuild": ("养贵", "边界", "门槛", "标准", "体面", "尊重自己", "将就"),
        "response_priority": ("时间", "优先", "回应", "在乎", "读懂", "理解", "被看见"),
        "supportive_appreciation": ("心软", "柔软", "珍惜", "牵紧", "包容"),
        "relationship_aftercare": ("吵架", "冷暴力", "修复", "回来", "沟通", "继续走下去"),
        "resilience_reconstruction": ("韧性", "重建", "训练", "命运", "不被定义", "向前"),
    }
    return mapping.get(structure_mode, ())


def _has_strategy_title_focus(*, structure_mode: str, title_options: list[str], recommended_title: str) -> bool:
    markers = _packaging_title_focus_markers(structure_mode)
    if not markers:
        return True
    titles = [*title_options, recommended_title]
    return any(any(marker in title for marker in markers) for title in titles if title)


def _should_retry_assets_for_packaging(
    *,
    strategy_bundle_payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> bool:
    structure_mode, _, positive_direction, _, packaging_focus = _get_strategy_resonance_targets(strategy_bundle_payload)
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    packaging_hook = str(contract_targets["packaging_hook"] or "")
    if not any((structure_mode, positive_direction, packaging_focus, packaging_hook)):
        return False

    title_options = [str(item).strip() for item in ai_result.get("title_options", []) if str(item).strip()]
    recommended_title = str(ai_result.get("recommended_title") or "").strip()
    social_teaser = str(ai_result.get("social_teaser") or "").strip()
    social_teaser_options = [str(item).strip() for item in ai_result.get("social_teaser_options", []) if str(item).strip()]
    cover_copy = str(ai_result.get("cover_copy") or "").strip()
    values = title_options + [recommended_title, social_teaser, *social_teaser_options, cover_copy]
    generic_packaging = _has_generic_packaging_openers(values)
    instruction_leakage = _has_packaging_instruction_leakage(values)
    meta_packaging = _has_packaging_meta_text(values)
    responsibility_floor = _has_responsibility_shelter_packaging_floor(values)
    missing_title_focus = not _has_strategy_title_focus(
        structure_mode=structure_mode,
        title_options=title_options,
        recommended_title=recommended_title,
    )
    missing_focus = not _packaging_hits_strategy_focus(structure_mode=structure_mode, values=values)
    missing_hook = bool(packaging_hook) and not _has_strategy_packaging_hook(values, packaging_hook)
    if (
        responsibility_floor
        and not any((instruction_leakage, meta_packaging, generic_packaging, missing_title_focus, missing_focus))
    ):
        missing_hook = False
    if (
        structure_mode != "responsibility_shelter"
        and responsibility_floor
        and not any((instruction_leakage, meta_packaging, generic_packaging))
    ):
        return False
    return instruction_leakage or meta_packaging or generic_packaging or missing_title_focus or missing_focus or missing_hook


def _should_retry_publish_package_for_packaging(
    *,
    strategy_bundle_payload: Mapping[str, object],
    ai_result: Mapping[str, object],
) -> bool:
    structure_mode, _, positive_direction, _, packaging_focus = _get_strategy_resonance_targets(strategy_bundle_payload)
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    packaging_hook = str(contract_targets["packaging_hook"] or "")
    if not any((structure_mode, positive_direction, packaging_focus, packaging_hook)):
        return False

    publish_title = str(ai_result.get("publish_title") or "").strip()
    publish_lead = str(ai_result.get("publish_lead") or "").strip()
    abstract = str(ai_result.get("abstract") or "").strip()
    intro_options = [str(item).strip() for item in ai_result.get("intro_options", []) if str(item).strip()]
    values = [publish_title, publish_lead, abstract, *intro_options]
    generic_packaging = _has_generic_packaging_openers(values)
    instruction_leakage = _has_packaging_instruction_leakage(values)
    meta_packaging = _has_packaging_meta_text(values)
    missing_focus = not _packaging_hits_strategy_focus(structure_mode=structure_mode, values=values)
    missing_hook = bool(packaging_hook) and not _has_strategy_packaging_hook(values, packaging_hook)
    return instruction_leakage or meta_packaging or generic_packaging or missing_focus or missing_hook


def _merge_retry_review_comment(review_comment: str | None, extra_instruction: str) -> str:
    review_parts = [str(review_comment).strip()] if review_comment and str(review_comment).strip() else []
    review_parts.append(extra_instruction.strip())
    return " ".join(part for part in review_parts if part)


def _build_assets_packaging_retry_instruction(
    strategy_bundle_payload: Mapping[str, object],
) -> str:
    _, _, positive_direction, _, packaging_focus = _get_strategy_resonance_targets(strategy_bundle_payload)
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    notes: list[str] = []
    if packaging_focus:
        notes.append(f"标题、封面文案和主导语必须明显贴住这个包装入口：{packaging_focus}")
    if contract_targets["packaging_hook"]:
        notes.append(f"这次包装主钩子要更明确地落在这里：{contract_targets['packaging_hook']}")
    if positive_direction:
        notes.append(f"主导语最后要带回这个正向落点：{positive_direction}")
    notes.append("标题候选必须独立抓住当前主题的现实入口，不要靠封面文案或导语替标题补题；不同主题使用不同入口，不要套同一个标题骨架。")
    notes.append("不要只概述正文；标题、封面文案、主导语和候选导语都不要用“很多人”“有些人”“总有人”这类泛主语起手。")
    return " ".join(notes)


def _build_publish_packaging_retry_instruction(
    strategy_bundle_payload: Mapping[str, object],
) -> str:
    _, _, positive_direction, _, packaging_focus = _get_strategy_resonance_targets(strategy_bundle_payload)
    contract_targets = _get_strategy_contract_targets(strategy_bundle_payload)
    notes: list[str] = []
    if packaging_focus:
        notes.append(f"发布标题和导语必须明显贴住这个包装入口：{packaging_focus}")
    if contract_targets["packaging_hook"]:
        notes.append(f"发布包装主钩子要更明确地落在这里：{contract_targets['packaging_hook']}")
    if positive_direction:
        notes.append(f"发布导语最后要带回这个正向落点：{positive_direction}")
    notes.append("不要写成编辑说明或泛概括句；发布标题、发布导语、摘要和导语候选都不要用“很多人”“有些人”“总有人”这类泛主语起手，先给入口，再给回收。")
    return " ".join(notes)


def _extract_non_heading_paragraphs(markdown: str) -> list[str]:
    paragraphs: list[str] = []
    for part in re.split(r"\n\s*\n", markdown):
        normalized = part.strip()
        if not normalized or normalized.startswith("#"):
            continue
        paragraphs.append(normalized)
    return paragraphs


def _split_block_sentences(block: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", block).strip()
    if not normalized:
        return []
    raw_sentences = [item.strip() for item in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", normalized) if item.strip()]
    if not raw_sentences:
        return []

    trailing_quote_prefix = re.compile(r'^[”"\'’）】》」』〕〗]+', re.UNICODE)
    sentences: list[str] = []
    for raw_sentence in raw_sentences:
        current = raw_sentence
        if sentences:
            quote_prefix = trailing_quote_prefix.match(current)
            if quote_prefix:
                sentences[-1] += quote_prefix.group(0)
                current = current[quote_prefix.end() :].strip()
        if not current:
            continue
        sentences.append(current)
    return sentences


def _build_local_publish_abstract(*, body_markdown: str, social_teaser: str, fallback_title: str) -> str:
    def _trim_complete_summary(text: str, *, max_length: int = 110) -> str:
        normalized = str(text or "").strip()
        if len(normalized) <= max_length:
            return normalized
        sentences = _split_block_sentences(normalized)
        selected: list[str] = []
        for sentence in sentences:
            candidate = "".join([*selected, sentence]).strip()
            if selected and len(candidate) > max_length:
                break
            if len(sentence) > max_length and not selected:
                return sentence[: max_length - 1].rstrip("，,；;、 ") + "。"
            selected.append(sentence)
        summary = "".join(selected).strip()
        if summary:
            return summary
        return normalized[: max_length - 1].rstrip("，,；;、 ") + "。"

    teaser = social_teaser.strip()
    if teaser:
        return _trim_complete_summary(teaser)

    fragments: list[str] = []
    for paragraph in _extract_non_heading_paragraphs(body_markdown):
        for sentence in _split_block_sentences(paragraph):
            normalized = sentence.strip()
            if (
                not normalized
                or normalized in fragments
                or _starts_with_generic_packaging_openers(normalized)
                or _looks_like_packaging_instruction_leakage(normalized)
            ):
                continue
            fragments.append(normalized)
            if len("".join(fragments)) >= 96:
                break
        if len("".join(fragments)) >= 96:
            break

    summary = "".join(fragments).strip()
    if not summary:
        return fallback_title.strip()
    return _trim_complete_summary(summary)


def _build_local_publish_tags(
    *,
    title: str,
    body_markdown: str,
    publish_lead: str,
    cover_copy: str,
) -> list[str]:
    corpus = re.sub(r"\s+", "", f"{title}\n{publish_lead}\n{cover_copy}\n{body_markdown}")
    if _should_use_local_responsibility_shelter_fallback(
        {
            "source_type": "tracked_article",
            "topic_title": title,
            "body_markdown": corpus,
        }
    ):
        return ["家庭责任", "家里踏实", "中年责任"]
    everyday_hits = sum(
        1
        for token in (
            "晚饭",
            "灯还亮着",
            "热饭",
            "饭能趁热吃",
            "知己",
            "家人平安",
            "有家可回",
            "有人可爱",
            "有人惦记",
            "平凡日子",
            "烟火",
        )
        if token in corpus
    )
    if everyday_hits >= 2:
        return ["生活温度", "家人相伴", "平凡幸福"]
    mode = _resolve_local_generic_fallback_mode(
        {
            "source_type": "tracked_article",
            "topic_title": title,
            "body_markdown": body_markdown,
            "cover_copy": cover_copy,
            "social_teaser": publish_lead,
        }
    )
    stage_payload = {
        "source_type": "tracked_article",
        "topic_title": title,
        "body_markdown": body_markdown,
        "cover_copy": cover_copy,
        "social_teaser": publish_lead,
    }
    if mode == "inner_settlement" and _uses_local_inner_settlement_stage_restart_variant(stage_payload):
        return ["阶段回望", "重新出发", "珍惜当下"]
    if mode == "emotional_engine_direct" and _uses_local_emotional_regret_forward_variant(stage_payload):
        return ["遗憾安放", "继续往前", "放下过去"]
    mode_tag_map: dict[str, list[str]] = {
        "response_priority": ["时间与在意", "认真回应", "关系回应"],
        "trust_boundary": ["信任与坦诚", "关系信任", "说到做到"],
        "self_worth_rebuild": ["自我价值", "关系边界", "好好爱自己"],
        "supportive_appreciation": ["心软的人", "被珍惜", "关系温柔"],
        "relationship_aftercare": ["关系修复", "争吵之后", "好好沟通"],
        "inner_settlement": ["内心安顿", "心安日常", "生活节奏"],
        "self_reliance_inward_support": ["自我安顿", "求助与自救", "成年人成长"],
        "resilience_reconstruction": ["韧性成长", "重新出发", "不被定义"],
        "emotional_engine_direct": ["旧关系安放", "情感成长", "重新生活"],
        "pressure_interface_direct": ["自我照料", "生活顺序", "身体提醒"],
    }
    if mode in mode_tag_map:
        return mode_tag_map[mode]
    scene_specific_rules: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (("会议室", "投影幕布", "散会", "老方案", "工位", "水杯"), ("职场表达", "开口时机")),
        (("地铁口", "摆渡车", "接驳车", "围巾", "白气", "出站口"), ("关系沟通", "没说出口")),
        (("药盒", "检查单", "水壶", "餐桌", "孩子已经睡了", "家里的心事"), ("家庭沟通", "家里心事")),
    )
    tag_rules: tuple[tuple[tuple[str, ...], str], ...] = (
        (("父母", "孩子", "家里", "一家人", "账单", "家"), "家庭责任"),
        (("中年", "成年人", "扛住", "硬撑", "没事", "有我"), "成年人压力"),
        (("晚饭", "散步", "灯", "热汤", "夕阳", "烟火"), "生活温度"),
        (("情绪", "委屈", "难过", "疲惫", "崩住", "发紧"), "情绪共鸣"),
        (("放下", "释怀", "重新", "往前", "后来", "回神"), "重新出发"),
        (("信任", "坦诚", "隐瞒", "谎言", "辜负", "说到做到"), "信任与坦诚"),
        (("拥抱", "接住", "温柔", "珍惜", "陪伴"), "被爱与陪伴"),
    )
    tags: list[str] = []
    for keywords, labels in scene_specific_rules:
        if any(keyword in corpus for keyword in keywords):
            for label in labels:
                if label not in tags:
                    tags.append(label)
                if len(tags) >= 3:
                    return tags
    if _payload_has_scene_first_relation_progression_cues(
        {
            "source_type": "tracked_article",
            "topic_title": title,
            "body_markdown": corpus,
        }
    ):
        scene_first_tags = ["关系沟通", "开口时机", "没说出口"]
        if any(token in corpus for token in ("会议", "早会", "方案", "翻页笔", "工位")):
            scene_first_tags.insert(0, "职场表达")
        elif any(token in corpus for token in ("餐桌", "药盒", "检查单", "水壶", "家里的心事")):
            scene_first_tags.insert(0, "家庭沟通")
        for label in scene_first_tags:
            if label not in tags:
                tags.append(label)
            if len(tags) >= 3:
                return tags
    for keywords, label in tag_rules:
        if any(keyword in corpus for keyword in keywords) and label not in tags:
            tags.append(label)
        if len(tags) >= 3:
            break
    if tags:
        return tags
    return ["情感成长", "生活感悟"]


def _dedupe_nonempty_text_options(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _resolve_mode_shaped_local_packaging_title(
    payload: Mapping[str, object],
    *,
    fallback_title: str,
) -> str:
    mode = _resolve_local_fallback_mode(payload)
    fallback_corpus = _extract_local_fallback_corpus(payload)
    mode_titles = {
        "everyday_warmth_return": "有家人惦记，有知己可说，日子就很值得",
        "inner_settlement": "把心放回今天，日子才会慢慢安稳",
        "self_reliance_inward_support": _pick_local_self_reliance_title(payload, "external"),
        "self_worth_rebuild": "别让那句“都可以”，替你让掉自己的位置",
        "response_priority": "真正在意你的人，会把话接下去",
        "trust_boundary": "那句没说清的话，后来要认真补回来",
        "responsibility_shelter": "肩上有责任的人，心里也要留一盏灯",
        "supportive_appreciation": "心软的人，值得被认真珍惜",
        "relationship_aftercare": "吵完还愿意回来，才是关系里的温柔",
        "resilience_reconstruction": (
            "每50米多划11下，她把命运划成了自己的赛道"
            if _has_local_resilience_pool_profile(payload)
            else "熬过那段路，你会重新长出力量"
        ),
        "emotional_engine_direct": "把那段路安放好，今天才能重新朝前走",
        "scene_first_progression": "那句没说出口的话，后来都成了距离",
        "pressure_interface_direct": "把被挪走的生活顺序，一点点调回来",
    }
    if mode == "inner_settlement" and _uses_local_inner_settlement_stage_restart_variant(payload):
        return "这半年没按你想的那样来，也不代表你白走了一程"
    if mode == "responsibility_shelter":
        if _uses_local_responsibility_endurance_variant(payload):
            return _resolve_local_responsibility_endurance_packaging_title(payload)
        cleaned_responsibility_title = str(fallback_title or "").strip()
        if cleaned_responsibility_title and _looks_like_explanatory_responsibility_shelter_title(cleaned_responsibility_title):
            return _resolve_local_responsibility_packaging_title(payload)
    if not mode and any(
        token in fallback_corpus
        for token in ("韧性", "重新长出力量", "最难走的路", "筋骨", "被生活按回去", "重新起身")
    ):
        mode = "resilience_reconstruction"
    cleaned = str(fallback_title or "").strip()
    if cleaned and not _starts_with_generic_packaging_openers(cleaned) and not _looks_like_packaging_title_judgment_template(cleaned):
        if mode in {
            "everyday_warmth_return",
            "response_priority",
            "relationship_aftercare",
            "emotional_engine_direct",
            "inner_settlement",
            "self_reliance_inward_support",
            "supportive_appreciation",
            "self_worth_rebuild",
            "resilience_reconstruction",
            "pressure_interface_direct",
        } and _looks_like_explanatory_packaging_title(cleaned):
            mode_title = str(mode_titles.get(mode) or "").strip()
            if mode_title:
                return mode_title
        return cleaned
    if mode == "scene_first_progression":
        scene_corpus = _extract_local_reference_corpus(payload) or _extract_local_fallback_corpus(payload)
        if _has_local_scene_first_office_markers(scene_corpus):
            return "散会后才开口，位置就会慢慢往后退"
        if _has_local_scene_first_transit_markers(scene_corpus):
            return "没问出口的那句话，最容易把关系拖远"
        if _has_local_scene_first_household_markers(scene_corpus):
            return "家里的心事，最怕总被顺到明天"
    if mode == "response_priority" and _uses_local_response_priority_followup_variant(payload):
        return "你轻轻带过的话，值得有人认真接下去"
    if mode == "response_priority" and _uses_local_response_priority_time_priority_variant(payload):
        return "愿意把时间留给你的人，才是真的把你放在心上"
    if mode == "self_worth_rebuild" and _has_local_self_worth_luxury_profile(payload):
        return "把自己看重一点，关系里的分寸才会回来"
    if mode == "supportive_appreciation" and _has_local_supportive_warmth_profile(payload):
        return "总会先顾别人感受的人，也该被认真护住"
    if mode == "emotional_engine_direct" and _uses_local_emotional_regret_forward_variant(payload):
        return "旧事可以收起来，脚下的路还要往前走"
    if mode == "emotional_engine_direct" and _uses_local_emotional_forgiveness_release_variant(payload):
        return "放过别人，也是把自己从旧事里放出来"
    if mode == "emotional_engine_direct" and _uses_local_emotional_memory_presence_variant(payload):
        return "有些人走远了，还是会在一个背影里轻轻回来"
    if mode == "emotional_engine_direct" and _uses_local_emotional_memory_reflux_variant(payload):
        return "那段旧关系没收好，往事就会在某个普通时刻回潮"
    if mode == "emotional_engine_direct" and _uses_local_emotional_endings_acceptance_variant(payload):
        return "有些关系停在半路，也会成全后来的你"
    mode_title = str(mode_titles.get(mode) or "").strip()
    if mode_title:
        return mode_title
    return "把眼前这件事重新说清"


def _normalize_self_reliance_local_title(payload: Mapping[str, object], title: str) -> str:
    cleaned = str(title or "").strip()
    if _resolve_local_fallback_mode(payload) != "self_reliance_inward_support":
        return cleaned
    if not cleaned:
        return _pick_local_self_reliance_title(payload, "external")
    stale_markers = (
        "没人能立刻搭把手",
        "没有人能随时赶来",
        "外面的帮扶",
        "等不到外面的手",
        "等外面的安慰",
        "外求未必",
        "即使没有帮助",
        "孤立无援",
        "相信你也有过这样的时刻",
        "想找人倾诉",
        "每个人都在各自扛事",
        "主心骨",
        "日子会慢慢变亮",
        "日子才会一点点变亮",
        "自己的光",
    )
    if any(marker in cleaned for marker in stale_markers) or _looks_like_explanatory_packaging_title(cleaned):
        return _pick_local_self_reliance_title(payload, "external")
    return cleaned


def _normalize_relationship_aftercare_local_title(title: str) -> str:
    cleaned = str(title or "").strip()
    if not cleaned:
        return "吵完还愿意回来，才是关系里的温柔"
    stale_markers = (
        "好的关系，不是",
        "好的关系不是",
        "真正爱你的人",
        "一个人到底爱不爱你",
        "吵一架就知道",
        "不是永远不吵架",
    )
    if any(marker in cleaned for marker in stale_markers) or _looks_like_packaging_title_judgment_template(cleaned):
        return "吵完还愿意回来，才是关系里的温柔"
    return cleaned


def _dedupe_safe_packaging_text_options(
    values: list[str],
    *,
    fallback_title: str,
    payload: Mapping[str, object],
) -> list[str]:
    deduped = _dedupe_nonempty_text_options(values)
    safe = [
        value
        for value in deduped
        if not _starts_with_generic_packaging_openers(value)
        and not _looks_like_packaging_title_judgment_template(value)
    ]
    fallback = _resolve_mode_shaped_local_packaging_title(payload, fallback_title=fallback_title)
    fallback = _normalize_self_reliance_local_title(payload, fallback)
    safe = [_normalize_self_reliance_local_title(payload, value) for value in safe]
    safe = _dedupe_nonempty_text_options(safe)
    if fallback and fallback not in safe:
        safe.insert(0, fallback)
    return safe or [fallback]


def _is_safe_direct_publish_title_for_responsibility(payload: Mapping[str, object], title: str) -> bool:
    cleaned = str(title or "").strip()
    if not cleaned:
        return False
    unsafe_tokens = (
        "没事，有我",
        "没事有我",
        "我没事",
        "这个月的绩效",
        "缴费窗口",
        "一个家的",
        "咽",
        "压着",
        "发紧",
        "撑住",
        "硬撑",
    )
    return (
        not _starts_with_generic_packaging_openers(cleaned)
        and not _looks_like_packaging_title_judgment_template(cleaned)
        and not _looks_like_packaging_instruction_leakage(cleaned)
        and not _looks_like_explanatory_responsibility_shelter_title(cleaned)
        and not any(token in cleaned for token in unsafe_tokens)
    )

def _resolve_local_assets_cover_copy(
    *,
    payload: Mapping[str, object],
    first_sentence: str,
    topic_angle: str,
    recommended_title: str,
) -> str:
    cleaned_first = first_sentence.strip()
    mode = _resolve_local_fallback_mode(payload)
    scene_corpus = f"{cleaned_first} {topic_angle} {_extract_local_reference_corpus(payload)}"
    self_reliance_cover_copy = _pick_local_seeded_text_variant(
        payload,
        (
            "先把今晚过稳，再把难处说给愿意分担的人听。",
            "能自己站稳，也敢开口求助，才是真正的底气。",
            "一时没人接住，也别忘了先把自己扶稳。",
        ),
    )
    short_map = {
        "everyday_warmth_return": "家里人平安，知己还在，平淡日子也很值得。",
        "inner_settlement": "心慢慢落回今天，日子就会重新有安稳感。",
        "self_reliance_inward_support": self_reliance_cover_copy,
        "self_worth_rebuild": "你的感受，也该在关系里占一个位置。",
        "response_priority": "一句补问落下来，心里悬着的地方会先松一下。",
        "trust_boundary": "信任很贵，别让赤诚输给含糊。",
        "responsibility_shelter": "肩上有责任，心里也要留一盏灯。",
        "supportive_appreciation": "会先顾别人感受的人，也该被认真接住。",
        "relationship_aftercare": "愿意回来把话说完的人，才是真的想和你走下去。",
        "resilience_reconstruction": (
            "命运少给的，她用一次次划水练了回来。"
            if _has_local_resilience_pool_profile(payload)
            else "熬过最难的那段路，你会重新长出自己的力量。"
        ),
        "emotional_engine_direct": "把那段路安放好，今天的日子才会重新朝前走。",
        "scene_first_progression": "很多距离，都是从一句话没说出口开始的。",
        "pressure_interface_direct": "把该照顾自己的那一步，放回今天。",
    }
    if mode == "scene_first_progression":
        if _has_local_scene_first_transit_markers(scene_corpus):
            _, cover_copy, _ = _resolve_local_scene_first_packaging_copy("transit")
            return cover_copy or "把那句真话早点说出口，很多关系就不会绕那么远。"
        if _has_local_scene_first_office_markers(scene_corpus):
            _, cover_copy, _ = _resolve_local_scene_first_packaging_copy("office")
            return cover_copy or "该在会上说的话，别总留到散会以后。"
        if _has_local_scene_first_household_markers(scene_corpus):
            _, cover_copy, _ = _resolve_local_scene_first_packaging_copy("household")
            return cover_copy or "家里的心事，还是要在来得及的时候慢慢说开。"
    if mode == "response_priority" and _uses_local_response_priority_followup_variant(payload):
        response_priority_scene_corpus = _build_local_response_priority_followup_corpus(payload)
        if "点赞" in response_priority_scene_corpus and "评论" in response_priority_scene_corpus and any(
            token in response_priority_scene_corpus for token in ("晚霞", "夕阳", "落日", "朋友圈", "照片")
        ):
            return "你轻轻带过的话，有人真的听进去了。"
        return "有人肯再问一句，心里会先松一下。"
    if mode == "response_priority" and _uses_local_response_priority_time_priority_variant(payload):
        return "忙完以后还记得回来找你的人，心里一直给你留着位置。"
    if mode == "everyday_warmth_return" and _uses_local_everyday_warmth_small_things_priority(payload):
        return "那些不起眼的小事，才最能把日子照亮。"
    if mode == "everyday_warmth_return" and _uses_local_everyday_warmth_simple_happiness_variant(payload):
        return "家里人平安，知己还在，平淡日子也很值得。"
    if mode == "supportive_appreciation":
        if _has_local_supportive_misread_profile(payload):
            return "别把他的体谅，当成你可以反复透支的东西。"
        if _has_local_supportive_discernment_profile(payload):
            return "心软的人，往往看得很清，也把情分看得很重。"
        if _has_local_supportive_apology_profile(payload):
            return "那个受了委屈还把语气放轻的人，更该被珍惜。"
        if _has_local_supportive_warmth_profile(payload):
            return "你给出去的温柔，也值得有人认真还回来。"
        return "会先顾别人感受的人，也该被认真接住。"
    if mode == "self_reliance_inward_support" and _uses_local_self_reliance_shared_burden_variant(payload):
        return self_reliance_cover_copy
    if mode == "inner_settlement" and _uses_local_inner_settlement_stage_restart_variant(payload):
        return "这半年没有白走，后面的日子还可以重新开始。"
    if mode == "inner_settlement" and _uses_local_inner_settlement_homecoming_variant(payload):
        return "心里有了归处，日子就不会一直飘着。"
    if mode == "inner_settlement" and _uses_local_inner_settlement_bedtime_variant(payload):
        return "别急着把所有事想通，今晚先把心放平一点。"
    if mode == "relationship_aftercare" and any(
        token in cleaned_first for token in ("到底有没有人回来", "有没有人回来", "回来接住")
    ):
        mode_copy = short_map.get(mode, "").strip()
        if mode_copy:
            return mode_copy
    if mode == "self_worth_rebuild":
        mode_copy = "把门槛留给敷衍，把真心留给值得的人。" if _has_local_self_worth_luxury_profile(payload) else short_map.get(mode, "").strip()
        if mode_copy:
            return mode_copy
    if mode in {
        "inner_settlement",
        "everyday_warmth_return",
        "self_reliance_inward_support",
        "pressure_interface_direct",
        "trust_boundary",
        "relationship_aftercare",
        "resilience_reconstruction",
    }:
        mode_copy = short_map.get(mode, "").strip()
        if mode_copy:
            return mode_copy
    if mode == "emotional_engine_direct":
        if _uses_local_emotional_regret_forward_variant(payload):
            return "把旧事轻轻收好，前面的风也会慢慢吹来。"
        if _uses_local_emotional_forgiveness_release_variant(payload):
            return "把心里的旧刺拔掉，日子才有地方重新照进光。"
        if _uses_local_emotional_memory_presence_variant(payload):
            return "有些人明明走远了，还是会在一个背影里轻轻回来。"
        if _uses_local_emotional_memory_reflux_variant(payload):
            return "那个突然想起的瞬间，是心里那段旧关系在轻轻回潮。"
        if _uses_local_emotional_endings_acceptance_variant(payload):
            return "有些关系停在半路，也会成全后来的你。"
        mode_copy = short_map.get(mode, "").strip()
        if mode_copy:
            return mode_copy
    if cleaned_first and len(cleaned_first) <= 30 and not extract_generic_reflective_openers(cleaned_first):
        return cleaned_first
    mode_copy = short_map.get(mode, "").strip()
    if mode_copy:
        return mode_copy
    fallback = (topic_angle or recommended_title or cleaned_first).strip()
    if len(fallback) > 30:
        fallback = fallback[:29].rstrip("，,；;。.!?？、 ") + "。"
    return fallback


def _resolve_local_assets_social_teaser(
    *,
    payload: Mapping[str, object],
    draft_body_markdown: str,
    first_sentence: str,
    cover_copy: str,
    topic_angle: str,
    recommended_title: str,
) -> str:
    mode = _resolve_local_fallback_mode(payload)
    first = first_sentence.strip()
    scene_corpus = f"{first} {topic_angle} {_extract_local_reference_corpus(payload)}"
    tail_map = {
        "everyday_warmth_return": "有人惦记，话有人听，平淡日子也能把人稳稳托住。",
        "inner_settlement": "先把今天过回今天，心就慢慢有地方落下来。",
        "self_reliance_inward_support": "先把自己扶稳，才有力气接住明天。",
        "self_worth_rebuild": "别让那句“都可以”，替你让掉自己的位置。",
        "response_priority": "那句顺着情绪接下去的话，往往比热闹互动更让人踏实。",
        "trust_boundary": "坦诚的分量，是把话说透，也把答应过的事做到。",
        "responsibility_shelter": "人可以担起责任，也要记得给自己留一盏灯。",
        "supportive_appreciation": "有人看见退让背后的在乎，温柔才不会被白白消耗。",
        "relationship_aftercare": "肯不肯回来把那阵冷气化开，最能看出对方有没有把这段关系放在心上。",
        "resilience_reconstruction": "熬过最难的那段路，你会重新长出自己的力量。",
        "emotional_engine_direct": "回头看过、想明白过，然后把今天重新过好。",
        "scene_first_progression": "很多距离，就是从这一句没说出来开始的。",
        "pressure_interface_direct": "那次复查被你往后挪时，生活其实已经在提醒你：该把自己排回今天了。",
    }
    if mode == "scene_first_progression":
        if _has_local_scene_first_transit_markers(scene_corpus):
            teaser, _, _ = _resolve_local_scene_first_packaging_copy("transit")
            if teaser:
                return teaser
            lead = first if first and len(first) <= 34 else "雨刚停，出站口外的摆渡车还没来。"
            return _compose_local_followup(lead, "你明明听出她还有话，最后还是先把那句追问按了回去。")
        if _has_local_scene_first_office_markers(scene_corpus):
            teaser, _, _ = _resolve_local_scene_first_packaging_copy("office")
            if teaser:
                return teaser
            lead = first if first and len(first) <= 34 else "人都起身了，你还坐在原位，在心里补刚才那句没说出口的话。"
            return _compose_local_followup(lead, "你以为只是又忍了一次，其实是把那句最该说的话又留到了最后。")
        if _has_local_scene_first_household_markers(scene_corpus):
            teaser, _, _ = _resolve_local_scene_first_packaging_copy("household")
            if teaser:
                return teaser
            lead = first if first and len(first) <= 34 else "夜里回到家，餐桌已经收得差不多了，药盒和检查单还放在手边。"
            return _compose_local_followup(lead, "你明明有话想问，最后还是先替这个晚上留了安静。")
    tail = str(tail_map.get(mode) or "").strip()
    first_is_safe = (
        first
        and not extract_generic_reflective_openers(first)
        and not _starts_with_generic_packaging_openers(first)
        and not _looks_like_packaging_instruction_leakage(first)
    )
    mode_specific_teasers = {
        "relationship_aftercare": (
            "门关上后，他没有把沉默留到第二天，而是端了杯水回来，先问了一句：“刚才是不是让你难受了？”"
            "好的关系不是从不争吵，是争吵以后仍有人愿意修复。"
        ),
        "resilience_reconstruction": (
            "没有右臂维持平衡，没有右腿蹬水发力，她每50米要比别人多划11下。"
            "后来，泳池里那些无人看见的重复，成了她站上领奖台时最有力的回答。"
            if _has_local_resilience_pool_profile(payload)
            else ""
        ),
    }
    mode_specific_teaser = str(mode_specific_teasers.get(mode) or "").strip()
    if mode_specific_teaser:
        return mode_specific_teaser
    if mode == "response_priority" and _uses_local_response_priority_followup_variant(payload):
        corpus = _build_local_response_priority_followup_corpus(payload)
        if "点赞" in corpus and "评论" in corpus:
            if any(token in corpus for token in ("晚霞", "夕阳", "落日", "朋友圈", "照片")):
                return "那张晚霞发出去以后，最暖的是那句看懂你疲惫的追问。"
            return "一排点赞里，最暖的往往是那句认真追问。"
        return "被认真听懂一次，心里悬着的地方会先松一下。"
    if mode == "response_priority" and _uses_local_response_priority_time_priority_variant(payload):
        lead = first if first_is_safe else "他说自己很忙那一刻，你把手机放下，心里那点期待也跟着安静了一下。"
        return _compose_local_followup(lead, "忙完以后还记得回来找你，这份交代最让人安心。")
    if mode == "supportive_appreciation":
        if _has_local_supportive_misread_profile(payload):
            lead = first if first_is_safe else "太好说话久了，别人很容易忘了，她也会疼。"
            return _compose_local_followup(lead, "体谅不是天生该让，能被珍惜，温柔才会一直留得住。")
        if _has_local_supportive_discernment_profile(payload):
            lead = first if first_is_safe else "饭桌上那句话刚落下，他夹菜的手停了一下，又很快把话题接了过去。"
            subject = "他" if "他" in lead and "她" not in lead else "她"
            return _compose_local_followup(lead, f"{subject}看得清，也愿意把情分放在前面。")
        if _has_local_supportive_apology_profile(payload):
            lead = first if first_is_safe else "明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。"
            return _compose_local_followup(lead, "愿意留余地的人，更需要被认真回应。")
        if _has_local_supportive_warmth_profile(payload):
            lead = first if first_is_safe else "别人递来一点暖意，他常常会想办法再多还回去一点。"
            return _compose_local_followup(lead, "难得的是，他把收到的暖意又慢慢还了回来。")
        lead = first if first_is_safe else "会先顾别人感受的人，也该有人反过来护住。"
        return _compose_local_followup(lead, "有人看见退让背后的在乎，温柔才不会被白白消耗。")
    if mode == "self_worth_rebuild" and _has_local_self_worth_luxury_profile(payload):
        lead = first if first_is_safe else "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。"
        return _compose_local_followup(lead, "把自己看重一点，关系里的分寸才会慢慢回来。")
    if mode == "self_reliance_inward_support" and _uses_local_self_reliance_shared_burden_variant(payload):
        lead = first if first_is_safe else "那句“我有点累”，在喉咙口绕了一圈，又被你慢慢咽了回去。"
        return _compose_local_followup(lead, "先把今晚稳住，再把难处说给愿意分担的人听。")
    if mode == "pressure_interface_direct":
        lead = first if first_is_safe else "复查提醒弹出来的时候，先别急着划掉。"
        return _compose_local_followup(lead, "把该照顾自己的那一步放回今天，日子才会一点点回到顺序里。")
    if mode == "trust_boundary":
        return "你愿意相信一个人的时候，已经把很重要的心安交了出去。坦诚的分量，是把话说透，也把答应过的事做到。"
    if mode == "inner_settlement" and _uses_local_inner_settlement_stage_restart_variant(payload):
        lead = first if first_is_safe else "翻回年初那页计划时，先别急着给这半年判输。"
        return _compose_local_followup(lead, "没完成的清单之外，你也已经认真走过一程。")
    if mode == "inner_settlement" and _uses_local_inner_settlement_homecoming_variant(payload):
        lead = first if first_is_safe else "心总往外悬着的时候，走到哪里都像没落稳。先回到自己心里，脚下的日子才会稳起来。"
        return _compose_local_followup(lead, "心里有了归处，外面的风再大，脚下也会有路。")
    if mode == "inner_settlement" and _uses_local_inner_settlement_bedtime_variant(payload):
        lead = first if first_is_safe else "心一直悬着的时候，普通一天也像差一点没落地。"
        return _compose_local_followup(lead, "答案可以明天再来，今晚先把心放回今天。")
    if mode == "emotional_engine_direct" and _uses_local_emotional_memory_presence_variant(payload):
        lead = first if first_is_safe else "很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。"
        return _compose_local_followup(lead, "有些人走远了，却还是会在你的日常缝隙里轻轻回来一下。")
    if mode == "emotional_engine_direct" and _uses_local_emotional_regret_forward_variant(payload):
        lead = first if first_is_safe else "有些旧东西一翻出来，人就忍不住替过去重新想一遍。"
        return _compose_local_followup(lead, "放下不是遗忘，是把旧事收好以后，仍然愿意去过新的日子。")
    if mode == "emotional_engine_direct" and _uses_local_emotional_forgiveness_release_variant(payload):
        lead = first if first_is_safe else "有些人和事一直放在心里，最先被困住的往往不是别人，是你自己。"
        return _compose_local_followup(lead, "原谅不是替谁开脱，是把自己的心从旧怨里慢慢放出来。")
    if mode == "emotional_engine_direct" and _uses_local_emotional_memory_reflux_variant(payload):
        lead = first if first_is_safe else "你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。"
        return _compose_local_followup(lead, "反复回来的，常常是那段没说完的话和没被接住的自己。")
    if mode == "emotional_engine_direct" and _uses_local_emotional_endings_acceptance_variant(payload):
        return "路过熟悉的地方，你还是会慢一下。那段关系没走完，却把眼界、分寸和勇气留在了你身上。"
    if first_is_safe:
        if tail:
            combined = _compose_local_followup(first, tail)
            if len(combined) <= 86:
                return combined
        if len(first) <= 72:
            return first

    fragments: list[str] = []
    for paragraph in _extract_non_heading_paragraphs(draft_body_markdown):
        for sentence in _split_block_sentences(paragraph):
            normalized = sentence.strip()
            if (
                not normalized
                or _starts_with_generic_packaging_openers(normalized)
                or _looks_like_packaging_instruction_leakage(normalized)
            ):
                continue
            fragments.append(normalized)
            if len("".join(fragments)) >= 72:
                break
        if len("".join(fragments)) >= 72:
            break
    fallback = "".join(fragments).strip() or cover_copy or topic_angle or recommended_title
    if tail and tail not in fallback and len(fallback) <= 40:
        combined = _compose_local_followup(fallback, tail)
        if len(combined) <= 86:
            return combined
    if len(fallback) <= 86:
        return fallback
    return fallback[:84].rstrip("，,；; ") + "。"


def _resolve_local_mode_cover_prompt(
    *,
    payload: Mapping[str, object],
    mode: str,
    recommended_title: str,
    cover_copy: str,
) -> str:
    resilience_scene = (
        "清晨室内泳池，一位年轻的残奥游泳运动员正在泳道中完成有力划水，水花、泳道线和池边计时牌形成真实训练现场"
        if _has_local_resilience_pool_profile(payload)
        else "清晨训练馆或康复场地，一个人完成当天最后一组重复训练，动作疲惫但稳定，现场有真实器械和汗水细节"
    )
    scene_map = {
        "self_reliance_inward_support": (
            "清晨餐桌或书桌，一个人喝过温水后把当天最要紧的三件事重新排好，窗外天色正在变亮，神情从慌乱回到笃定"
        ),
        "self_worth_rebuild": (
            "明亮的餐桌或工作台，一位女性平静地把不属于自己的额外任务推回桌面中央，另一只手按住自己的日程本，姿态从容有边界"
        ),
        "trust_boundary": (
            "傍晚家中餐桌或客厅，两个人面对面坐下认真解释和倾听，桌边有钥匙与一部普通单屏手机，手机屏幕背向镜头，气氛从紧张慢慢回到坦诚"
        ),
        "supportive_appreciation": (
            "明亮的厨房或门厅，一个人替刚回家的人递上温水、接过外套，对方也自然回身扶住她的肩，温柔得到回应，生活抓拍感"
        ),
        "relationship_aftercare": (
            "争吵后的家中厨房或客厅，一个人端着温水重新走回来，两个人隔着半张桌子坐下，身体姿态逐渐放松，暖灯把关系重新照亮"
        ),
        "response_priority": (
            "傍晚车内或路口红灯前，一个人把水杯放回杯架，手机屏幕朝下放在副驾或桌边，手指停在一条未读提醒旁，画面只表现等待和被想起的瞬间"
        ),
        "resilience_reconstruction": resilience_scene,
    }
    scene = str(scene_map.get(mode) or "").strip()
    if not scene:
        return ""
    return (
        f"16:9横版公众号封面，真实摄影感，{scene}，画面明亮克制，有具体动作和生活细节，"
        f"保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
        "不要聊天界面，不要消息气泡，不要可读手机屏幕，不要把整张图做成纯文字海报。"
    )


def _build_local_assets_fallback(
    *,
    project_title: str,
    topic_title: str,
    topic_angle: str,
    draft_title: str,
    draft_body_markdown: str,
) -> dict[str, object]:
    focus_payload = {
        "source_type": "tracked_article",
        "topic_title": topic_title,
        "topic_angle": topic_angle,
        "body_markdown": draft_body_markdown,
    }
    first_sentence = ""
    for paragraph in _extract_non_heading_paragraphs(draft_body_markdown):
        sentences = _split_block_sentences(paragraph)
        if sentences:
            first_sentence = sentences[0].strip()
            break

    if _should_use_local_responsibility_shelter_fallback(focus_payload):
        teaser = _resolve_local_responsibility_teaser(focus_payload)
        specific_title = _resolve_local_responsibility_packaging_title(focus_payload)
        corpus = _extract_local_reference_corpus(focus_payload) or _extract_local_fallback_corpus(focus_payload)
        safe_draft_title = draft_title
        if any(token in safe_draft_title for token in ("没事，有我", "这个月的绩效", "缴费窗口")):
            safe_draft_title = "肩上有责任的人，心里也要留一盏灯"
        if "请假" in corpus and "绩效" in corpus:
            specific_title = _resolve_local_responsibility_packaging_title(focus_payload)
        endurance_variant = _uses_local_responsibility_endurance_variant(focus_payload)
        midlife_variant = _uses_local_responsibility_midlife_variant(focus_payload)
        if endurance_variant:
            specific_title = _resolve_local_responsibility_endurance_packaging_title(focus_payload)
        title_seed_options = [
            specific_title,
            safe_draft_title,
            "把家里日子托稳的人，也该被好好心疼",
            "有些辛苦不张扬，却一直把日子往前托",
        ]
        title_options = _dedupe_safe_packaging_text_options(
            title_seed_options,
            fallback_title=specific_title or safe_draft_title or topic_title or project_title,
            payload=focus_payload,
        )
        recommended_title = title_options[0]
        cover_copy = (
            "你扛住的那些日常，后来都在替家里换安稳。"
            if midlife_variant
            else (
                "你替一家人扛住风雨，也别忘了给自己留一盏灯。"
                if endurance_variant
                else "肩上有责任，心里也要留一盏灯。"
            )
        )
        social_teaser = teaser
        social_teaser_options = _dedupe_nonempty_text_options(
            [
                social_teaser,
                "很多中年人的一天，都是从把自己往后放半步开始的。" if midlife_variant else "",
                "把家撑住的人，也别忘了照顾那个总说“我没事”的自己。" if endurance_variant else "",
                "你把很多事安排妥了，家里的灯才会这样稳稳亮着。",
                "辛苦不必说得很响，家里那点踏实会记得。",
                "把日子往前托的人，也该被生活轻轻托一下。",
            ]
        )
        cover_prompt = (
            f"16:9 横版公众号封面，傍晚家中暖灯，桌边有水杯、账单和一碗热饭，"
            f"有人推门回家，画面温暖克制，主题是《{recommended_title}》，"
            f"副文案是“{cover_copy}”。不要手机聊天界面，不要消息气泡，不要可读屏幕。"
        )
    else:
        title_options = _dedupe_safe_packaging_text_options(
            [draft_title, topic_title, project_title],
            fallback_title=draft_title or topic_title or project_title,
            payload=focus_payload,
        )
        recommended_title = title_options[0]
        mode = _resolve_local_generic_fallback_mode(focus_payload)
        cover_copy = _resolve_local_assets_cover_copy(
            payload=focus_payload,
            first_sentence=first_sentence,
            topic_angle=topic_angle,
            recommended_title=recommended_title,
        )
        social_teaser = _resolve_local_assets_social_teaser(
            payload=focus_payload,
            draft_body_markdown=draft_body_markdown,
            first_sentence=first_sentence,
            cover_copy=cover_copy,
            topic_angle=topic_angle,
            recommended_title=recommended_title,
        )
        social_teaser_options = [
            item
            for item in _dedupe_nonempty_text_options([social_teaser, cover_copy, topic_angle])
            if item.strip() and not _looks_like_packaging_instruction_leakage(item)
        ]
        response_priority_scene_corpus = _build_local_response_priority_followup_corpus(focus_payload)
        if (
            mode == "response_priority"
            and _uses_local_response_priority_followup_variant(focus_payload)
            and "点赞" in response_priority_scene_corpus
            and "评论" in response_priority_scene_corpus
            and any(token in response_priority_scene_corpus for token in ("晚霞", "夕阳", "落日", "朋友圈", "照片"))
        ):
            cover_prompt = (
                f"16:9横版公众号封面，黄昏窗边或安静室内，晚霞余晖落进屋里，桌上放着一部手机，屏幕暗掉或虚化，"
                f"人物刚下班，神情放松却有一点被理解后的回温感，真实克制，保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "不要聊天界面，不要消息气泡，不要把整张图做成纯文字海报。"
            )
            return {
                "title_options": title_options,
                "recommended_title": recommended_title,
                "cover_prompt": cover_prompt,
                "cover_copy": cover_copy,
                "social_teaser": social_teaser,
                "social_teaser_options": social_teaser_options[:3],
            }
        if mode == "pressure_interface_direct":
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，清晨或傍晚的餐桌与日历现场，桌上有体检预约单、复查提醒便签、一碗热饭和一杯温水，"
                f"人物把日历上的提醒重新圈出来，画面克制明亮，保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "不要聊天界面，不要消息气泡，不要可读手机屏幕，不要把整张图做成纯文字海报。"
            )
            return {
                "title_options": title_options,
                "recommended_title": recommended_title,
                "cover_prompt": cover_prompt,
                "cover_copy": cover_copy,
                "social_teaser": social_teaser,
                "social_teaser_options": social_teaser_options[:3],
            }
        mode_cover_prompt = _resolve_local_mode_cover_prompt(
            payload=focus_payload,
            mode=mode,
            recommended_title=recommended_title,
            cover_copy=cover_copy,
        )
        scene_variant = _resolve_local_cover_scene_variant(
            topic_title,
            topic_angle,
            draft_body_markdown,
            cover_copy,
        )
        if mode_cover_prompt:
            cover_prompt = mode_cover_prompt
        elif mode == "inner_settlement" and _uses_local_inner_settlement_stage_restart_variant(focus_payload):
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，年中傍晚的书桌或窗边，摊开的计划清单、日历页、笔和一杯水，"
                f"人物把没完成的几项轻轻划过又重新写下一行新计划，画面温暖明亮，保留左下标题安全区，"
                f"主题是《{recommended_title}》，副文案是“{cover_copy}”。不要聊天界面，不要可读手机屏幕，不要纯文字海报。"
            )
        elif mode == "emotional_engine_direct" and _uses_local_emotional_endings_acceptance_variant(focus_payload):
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，傍晚旧街口或曾经常去的小店门前，一个人从门口经过时脚步微微放慢，"
                f"橱窗暖光、街边树影和手里折好的旧票据或纸袋形成“相遇曾经来过”的生活现场，画面明亮克制，保留左下标题安全区，"
                f"主题是《{recommended_title}》，副文案是“{cover_copy}”。不要手机，不要聊天界面，不要消息气泡，不要可读屏幕，不要纯文字海报。"
            )
        elif mode == "emotional_engine_direct" and _uses_local_emotional_regret_forward_variant(focus_payload):
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，傍晚小区或家中衣柜旁，一件洗得发白的碎花旧裙被轻轻叠好，"
                f"旁边放着一条浅紫色新裙子，远处窗外有公园小路和柔和晚霞，画面温暖明亮，保留左下标题安全区，"
                f"主题是《{recommended_title}》，副文案是“{cover_copy}”。不要手机，不要聊天界面，不要消息气泡，不要可读屏幕，不要纯文字海报。"
            )
        elif mode == "everyday_warmth_return":
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，傍晚家中餐桌或客厅一角，暖灯、一碗热饭、家人围坐或留灯等生活细节，"
                f"画面温暖明亮，保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "画面聚焦日常餐桌、灯光和人物互动，清爽留白，生活抓拍感。"
            )
        elif scene_variant == "transit":
            cover_prompt = (
                f"16:9横版公众号封面，雨后傍晚的出站口和摆渡车现场，湿路反光，站牌、车灯、薄雾和人物侧影形成真实生活感，"
                f"人物只是站在现场，左侧留标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "不要可读手机屏幕，不要聊天界面，不要做纯色底大字卡，不要把整张图做成居中深色文字海报。"
            )
        elif scene_variant == "office":
            cover_prompt = (
                f"16:9横版公众号封面，清晨会议室或工位现场，投影幕布、会议桌、冷白窗光和停住的水杯形成职场压迫感，"
                f"真实克制，保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "不要纯文字海报，不要整块深色卡片盖住画面。"
            )
        elif scene_variant == "household":
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，夜里家中餐桌或窗边现场，暖灯、药盒、检查单、水壶等物件带出家庭沉默感，"
                f"真实克制，保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "不要纯文字海报，不要整块深色卡片盖住画面。"
            )
        else:
            anchor = _extract_first_sentence_fragment(first_sentence or topic_angle or recommended_title, max_length=34)
            scene_detail = (
                f"以“{anchor}”对应的真实生活瞬间为核心"
                if anchor
                else "以一处真实的日常生活现场为核心"
            )
            cover_prompt = (
                f"16:9横版公众号封面，真实摄影感，{scene_detail}，安排人物动作、桌面物件、窗光或街边环境来承接主题，"
                f"画面明亮克制，保留左下标题安全区，主题是《{recommended_title}》，副文案是“{cover_copy}”。"
                "不要聊天界面，不要消息气泡，不要可读手机屏幕，不要把整张图做成纯文字海报。"
            )
    return {
        "title_options": title_options,
        "recommended_title": recommended_title,
        "cover_prompt": cover_prompt,
        "cover_copy": cover_copy,
        "social_teaser": social_teaser,
        "social_teaser_options": social_teaser_options[:3],
    }


def _merge_safe_prior_asset_titles(
    *,
    local_result: Mapping[str, object],
    prior_result: Mapping[str, object],
) -> dict[str, object]:
    merged = dict(local_result)
    candidates: list[str] = []
    recommended_title = str(prior_result.get("recommended_title") or "").strip()
    if recommended_title:
        candidates.append(recommended_title)
    title_options = prior_result.get("title_options")
    if isinstance(title_options, list):
        candidates.extend(str(item or "").strip() for item in title_options)

    unsafe_tokens = ("没事，有我", "没事有我", "我没事", "这个月的绩效", "缴费窗口", "一个家的", "咽", "压着", "发紧", "撑住", "硬撑")
    safe_candidates = [
        candidate
        for candidate in _dedupe_nonempty_text_options(candidates)
        if candidate
        and not _starts_with_generic_packaging_openers(candidate)
        and not _looks_like_packaging_instruction_leakage(candidate)
        and not any(token in candidate for token in unsafe_tokens)
    ]
    if not safe_candidates:
        return merged

    existing_options = merged.get("title_options")
    existing = [str(item or "").strip() for item in existing_options] if isinstance(existing_options, list) else []
    old_title = str(merged.get("recommended_title") or "").strip()
    new_title = safe_candidates[0]
    merged["recommended_title"] = new_title
    merged["title_options"] = _dedupe_nonempty_text_options([*safe_candidates, *existing])
    cover_prompt = str(merged.get("cover_prompt") or "")
    if old_title and cover_prompt:
        cover_prompt = cover_prompt.replace(f"《{old_title}》", f"《{new_title}》")
        cover_prompt = cover_prompt.replace(old_title, new_title, 1)
        merged["cover_prompt"] = cover_prompt
    return merged


def _build_local_publish_package_fallback(
    *,
    draft_title: str,
    draft_body_markdown: str,
    assets: AssetItem,
) -> dict[str, object]:
    def _rebuild_distinct_body_line(*excluded: str) -> str:
        excluded_values = {item.strip() for item in excluded if item and item.strip()}
        picked: list[str] = []
        for paragraph in _extract_non_heading_paragraphs(draft_body_markdown):
            for sentence in _split_block_sentences(paragraph):
                normalized = sentence.strip()
                if (
                    not normalized
                    or normalized in excluded_values
                    or _looks_like_packaging_instruction_leakage(normalized)
                ):
                    continue
                picked.append(normalized)
                if len("".join(picked)) >= 72:
                    break
            if picked:
                break
        return "".join(picked).strip()

    focus_payload = {
        "source_type": "tracked_article",
        "topic_title": draft_title,
        "body_markdown": draft_body_markdown,
        "cover_copy": assets.cover_copy,
        "social_teaser": assets.social_teaser,
        "social_teaser_options": list(assets.social_teaser_options),
        "title_options": list(assets.title_options),
        "recommended_title": assets.recommended_title,
    }
    title_options = _dedupe_safe_packaging_text_options(
        [assets.recommended_title, *assets.title_options, draft_title],
        fallback_title=draft_title,
        payload=focus_payload,
    )
    publish_title = title_options[0]
    responsibility_focus = _should_use_local_responsibility_shelter_fallback(focus_payload)
    if responsibility_focus and _is_safe_direct_publish_title_for_responsibility(focus_payload, assets.recommended_title):
        publish_title = assets.recommended_title.strip()
        title_options = _dedupe_nonempty_text_options([publish_title, *title_options])
    if responsibility_focus:
        publish_lead = _resolve_local_responsibility_publish_lead(focus_payload)
    else:
        publish_lead = assets.social_teaser.strip() or assets.cover_copy.strip()
    if _starts_with_generic_packaging_openers(publish_lead):
        safe_cover_copy = assets.cover_copy.strip()
        if safe_cover_copy and not _starts_with_generic_packaging_openers(safe_cover_copy):
            publish_lead = safe_cover_copy
        else:
            first_sentence = ""
            for paragraph in _extract_non_heading_paragraphs(draft_body_markdown):
                sentences = _split_block_sentences(paragraph)
                if sentences:
                    first_sentence = sentences[0].strip()
                    break
            publish_lead = _resolve_local_assets_social_teaser(
                payload=focus_payload,
                draft_body_markdown=draft_body_markdown,
                first_sentence=first_sentence,
                cover_copy=safe_cover_copy,
                topic_angle="",
                recommended_title=publish_title,
            )
    if responsibility_focus:
        abstract = _resolve_local_responsibility_publish_abstract(focus_payload)
        intro_options = _resolve_local_responsibility_intro_options(focus_payload, publish_lead)
    else:
        mode = _resolve_local_generic_fallback_mode(focus_payload)
        response_priority_scene_corpus = _build_local_response_priority_followup_corpus(focus_payload)
        scene_variant = _resolve_local_cover_scene_variant(draft_title, draft_body_markdown, assets.cover_copy)

        def _resolve_trust_boundary_publish_copy() -> tuple[str, str]:
            trust_corpus = re.sub(
                r"\s+",
                "",
                f"{draft_title}\n{draft_body_markdown}\n{assets.cover_copy}\n{assets.social_teaser}\n{' '.join(assets.social_teaser_options)}",
            )
            broken_scene = any(
                token in trust_corpus
                for token in (
                    "信任碎了",
                    "裂过一次",
                    "裂了一道缝",
                    "不是不爱了，是怕了",
                    "信任不是一下碎掉",
                )
            )
            if broken_scene:
                return (
                    "一句谎话落下来，当下也许还能把饭吃完，可心里那一下停顿，很久都过不去。",
                    "过日子最踏实的时刻，是你说一句“今晚加班”，对方不用猜，也不用查。有人肯这样相信你，是把心里最柔软的地方交给了你。这份放心，比多少情话都难得，值得用同样的坦荡认真守住。",
                )
            return (
                "临时变了安排，主动说一声；答应过的事，能做到就做到。愿意放心信你的人，值得被你用这些小事好好守住。",
                "信任最怕含糊。明明可以坦诚，却拿绕开的说法去碰别人的真心，那份放心就会一点点变薄。能留住心安的，是把话说透，也把答应过的事做到。说到做到，比多少解释都有分量。",
            )

        if mode == "scene_first_progression":
            publish_lead = _resolve_local_scene_first_publish_lead(scene_variant)
            if scene_variant == "transit":
                _, _, abstract = _resolve_local_scene_first_packaging_copy("transit")
            elif scene_variant == "office":
                _, _, abstract = _resolve_local_scene_first_packaging_copy("office")
            elif scene_variant == "household":
                _, _, abstract = _resolve_local_scene_first_packaging_copy("household")
            else:
                abstract = "有些话总被拖到转身以后，关系也会在沉默里一点点变远。把该说的留在当场，很多距离就不会越走越长。"
        else:
            abstract = _build_local_publish_abstract(
                body_markdown=draft_body_markdown,
                social_teaser=publish_lead,
                fallback_title=publish_title,
            )
        if mode == "response_priority":
            if _uses_local_response_priority_time_priority_variant(focus_payload):
                publish_lead = "大家都忙，这件事你明白。可把你放在心上的人，不会让一句话一直悬着。哪怕当下顾不上，他也会在忙完以后回来找你，把回应补上。"
                abstract = "忙完还记得回来接一句，心里那点悬着就会慢慢落地。时间不一定要很多，但愿意补上的人，会让你知道自己一直被放在心上。"
            else:
                if any(token in response_priority_scene_corpus for token in ("晚霞", "夕阳", "落日", "朋友圈", "照片")) and any(
                    token in response_priority_scene_corpus
                    for token in ("点赞", "评论", "追问", "补问", "项目又出岔子了", "打电话", "我没事", "我有点累")
                ):
                    publish_lead = "那条朋友圈发出去以后，别人看见了晚霞，在意你的人，也看见了你那句轻描淡写后面的疲惫。他不会只留个赞就走，还会顺着那点情绪，多问一句。"
                    abstract = "一条朋友圈下面热闹不难，难的是有人看懂你那句轻描淡写，追着问一句“是不是又把累藏起来了”。被这样惦记一次，人心里那根绷着的弦会先松一点。"
                else:
                    publish_lead = "那天你把手机扣在桌上，顺手说了句“没事”。他没有急着追问，只是把手边的水推过来，等你愿意开口。这样的在意，不会催你马上说明白。"
                    abstract = "点赞可以很快，认真听完却需要耐心。有人愿意记住你语气里的变化，等你把话说完整，那份在意就不止是互动，而是把你当成一个具体的人在珍惜。"
        elif mode == "everyday_warmth_return":
            if _uses_local_everyday_warmth_small_things_priority(focus_payload):
                publish_lead = "周末陪父母在小区慢慢走一圈，陪孩子把积木铺满地，再和爱人拎着菜回家。一天没有发生什么大事，可晚上躺下时，心里是满的。"
                abstract = "属于你的生活，很少写在履历上。它藏在一次没有催促的散步、一个肯好好陪伴的下午里。把这些小事捡回来，日子就有了温度。"
            elif _uses_local_everyday_warmth_simple_happiness_variant(focus_payload):
                publish_lead = "推开家门有饭香，电话那头有人惦记，想说话时还有老朋友愿意听。这样的日子不惊艳，却很踏实。"
                abstract = "家人安康、知己二三、四季平安，听起来都是小愿望，却最能托住一个人的后半程。能把这些平淡守好，就是很具体的福气。"
            else:
                publish_lead = "回家时那盏灯还亮着，饭也还热着。忙了一天的人，常常就是被这些细碎又实在的小事轻轻接住。"
                abstract = "家里人平安，想说的话有人听，再普通的一天也会让人心里发暖。一顿热饭、一句惦记，就够人踏实很久。"
        elif mode == "inner_settlement":
            if _uses_local_inner_settlement_stage_restart_variant(focus_payload):
                publish_lead = "翻到年初那页计划时，先别急着给这半年判输。有些目标还空着，但你认真扛过的日子、遇见的温暖和重新调整的勇气，都不该被轻轻抹掉。"
                abstract = "这半年没有完全照着计划走，也不代表你白走了一程。没完成的清单可以慢慢补，错过的人和事可以慢慢安放。把眼前事做好，把身边人珍惜好，后面的日子还会有新的答案。"
            elif _uses_local_inner_settlement_homecoming_variant(focus_payload):
                publish_lead = "忙完一天回到家，先把鞋摆好，给自己倒杯水，窗外再吵也由它去。眼前这个普通的日子稳下来，心也会慢慢跟着落地。"
                abstract = "心安会落在很小的动作里：把一顿饭吃热，把一句话说慢，把今天过清楚。外面的风停不停由不得你，屋里的灯，却可以由你亲手打开。"
            elif any(token in draft_body_markdown for token in ("已经过去的事", "还没发生的事", "提前在心里演很多遍", "很多答案不会今晚就来")):
                publish_lead = "不用把所有事都在今晚想通，有些情绪也不必立刻处理干净。先把今天过完，人就会慢慢松下来。"
                abstract = "已经过去的先放一放，还没发生的也先别追着跑。把饭吃好，把灯关好，心就会一点点回到眼前。"
            else:
                publish_lead = "夜里屋里已经安静下来，心里那点事还在来回翻。先把水杯放好，把灯关掉，明早再看，也许就没有这么重。"
                abstract = "把水烧开，把灯关好，把明天要穿的衣服放在手边。等心先落回今天，那些想不通的事，往往也就没那么吵了。"
        elif mode == "self_reliance_inward_support":
            if _uses_local_self_reliance_shared_burden_variant(focus_payload):
                publish_lead, abstract = _pick_local_seeded_pair_variant(
                    focus_payload,
                    (
                        (
                            "电话暂时没人接时，先把眼前那件事放到桌面上。能写下来的写下来，能处理的先处理，心会先有一点顺序。",
                            "人会慢慢走稳，是因为需要时敢开口，没人立刻回应时也不放弃行动。求助不丢人，自救也不丢人。",
                        ),
                        (
                            "身边的人也在各自忙乱时，先别把希望全压在等待上。把饭吃完，把事情列清，再把该说的话说给能分担的人听。",
                            "先照顾好自己，再去找能分担的人。手里还有行动，心里也还相信事情能往前走，人就会慢慢有底气。",
                        ),
                        (
                            "心里乱成一团的时候，别急着把人生想明白。洗把脸，喝口水，把眼前那件事先处理掉。",
                            "很多难关不会忽然变轻。你开始行动以后，心才慢慢不被难处拖着走。能处理的先处理，该求助的就求助。",
                        ),
                    ),
                )
            else:
                publish_lead, abstract = _pick_local_seeded_pair_variant(
                    focus_payload,
                    (
                        (
                            "事情一挤上来，心里最先乱掉。你不知道该先抓住哪一头，就先把眼前最要紧的事摆清楚。",
                            "乱的时候还肯行动，人就不会一直被难处推着走。把手里的事理顺一点，心也会跟着稳一点。",
                        ),
                        (
                            "越是乱的时候，越要先把自己扶稳。答案可以晚一点来，今天能做的那一部分，先替自己做好。",
                            "把生活重新握住，常常从一个真实动作开始：能处理的先处理，该求助的去求助，该休息的也别再硬拖。",
                        ),
                        (
                            "有些日子不用立刻想通全部答案。先把呼吸放慢，把眼前事理清，人就会稳很多。",
                            "日子真正往前时，难处未必马上变少。你开始行动，也开始更清楚地开口，这已经是在往外走。",
                        ),
                    ),
                )
        elif mode == "pressure_interface_direct":
            publish_lead = "复查提醒弹出来的时候，先别急着划掉。把那顿饭按时吃完，把该约的检查约回日历，就是把自己重新排回今天。"
            abstract = "生活的顺序，常常是从一个很小的动作开始回来的。体检照约、饭按时吃、该停的时候停一停，人先回稳，后面的责任和日子才会更有力量。"
        elif mode == "supportive_appreciation":
            if _has_local_supportive_misread_profile(focus_payload):
                publish_lead = "太好说话的人，也会疼。她愿意翻篇，是因为把情分看得更重。这份体谅被认真珍惜，温柔才会留得久。"
                abstract = "她愿意再把话接起来，已经是在给这段关系一次机会。下一次记得先听完她的话，也把答应过的改变做到。心软的人最看重的，是你真的没有让同一件事再发生。"
            elif _has_local_supportive_discernment_profile(focus_payload):
                publish_lead = "饭桌上那句话刚落下，他夹菜的手停了一下，又很快把话题接了过去。看得清，还愿意把场面接住，这份心软更该被珍惜。"
                abstract = "心软有分寸，退让也有判断。他愿意给关系留一点暖意，心里装着的是情分，也是分寸。若你身边有这样的人，请记得好好接住他的温柔。"
            elif any(token in draft_body_markdown for token in ("歉意", "道歉", "原谅", "真心道了歉", "把歉意说出口")):
                publish_lead = "那句“对不起”说完，她沉默了一会儿，还是把水杯往你这边推了推。刚才的话确实伤到了她，可这段关系在她心里，比当下那口气更重要，所以她愿意再把话接起来。"
                abstract = "道歉最有分量的部分，往往发生在下一次：你记得她为什么难过，也真的把那件事做得不一样。温柔被认真接住，才会一直是温柔。"
            elif _has_local_supportive_warmth_profile(focus_payload):
                publish_lead = "心软的人最动人的地方，是收到一点好，就想认真还回去。这样的人未必会把爱说得很响，却会把你给过的暖，一点点落回日子里。"
                abstract = "把温柔一遍遍落进小事里的人，很稀缺。别等他把失望咽多了，才想起他的体谅有多珍贵。"
            else:
                publish_lead = "饭桌上的气氛刚有点僵，她先夹了一筷子菜，问了句：“还吃吗？”她也会难受，只是舍不得让在乎的人一直隔着一口气。"
                abstract = "肯先把话接回来的人，已经把关系放在了输赢前面。别让这份主动总是一个人的习惯；你也往前走一步，很多误会就能停在今晚。"
        elif mode == "trust_boundary":
            publish_lead, abstract = _resolve_trust_boundary_publish_copy()
        elif mode == "self_worth_rebuild":
            if _has_local_self_worth_luxury_profile(focus_payload):
                publish_lead = "你越轻易把自己放低，别人越容易把你的体面当成可商量。后来你才懂，把自己看重，是把委屈从关系里慢慢撤出来。"
                abstract = "别总怕自己一开口就显得难相处。你把什么能答应、什么不能退说清以后，愿意珍惜你的人，不会嫌你麻烦，反而会更认真地对待你。"
            else:
                publish_lead = "有一天你终于把那句“这次不行”说出口，关系没有天塌，生活也没有乱。你才发现，认真对待自己，并不会把爱你的人推远。"
                abstract = "能长久留在身边的人，不只喜欢你的好说话，也会尊重你的不愿意。把想法讲清，把边界守好，你会过得更舒展，别人也更知道该怎样珍惜你。"
        elif mode == "trust_boundary" or _has_local_trust_boundary_focus(focus_payload):
            publish_lead, abstract = _resolve_trust_boundary_publish_copy()
        elif mode == "relationship_aftercare":
            publish_lead = "门关上以后，谁都没再说话。过了一会儿，他把热水放到你手边，低声问：“刚才是不是让你难受了？”"
            abstract = "争吵不会因为一句话马上消失，关系却可以从这句追问重新开始。把该道的歉道清楚，把下次要改的地方记在心里，两个人都肯往前一步，伤口就不会只剩下伤口。"
        elif mode == "resilience_reconstruction":
            if _has_local_resilience_pool_profile(focus_payload):
                publish_lead = "她重新下水的那一天，命运给过的缺口还在，疼也还在。可每多划一下，身体就多记住一点力量，人生也被她一点点练回自己手里。"
                abstract = "失去右臂和右腿，没有替她写完人生。手术台、泳池、每50米多出来的11下，都在把她重新托起来。真正的韧性，是疼过以后还肯继续生长。"
            else:
                publish_lead = "昨天没做成的那件事，今天你又把鞋带系紧，站回了起点。韧性有时很安静，摔过以后还愿意再试一次，疼过以后还肯把身体一点点练回来。"
                abstract = "生活给过你缺口，你没有把余生交给那个缺口。一次训练、一次复盘、一次重新出发，这些看起来不起眼的坚持，会慢慢长成你自己的力量。"
        elif mode == "emotional_engine_direct":
            if _uses_local_emotional_regret_forward_variant(focus_payload):
                publish_lead = "阿婆把那条旧裙子叠起来时，像是把当年那句“如果去了会不会不一样”也轻轻收好。人真正往前走，不是忘了遗憾，而是不再让遗憾替今天做主。"
                abstract = "旧事可以记得，遗憾也可以承认。只是路还在往前，风也还会吹来。把回不去的部分安放好，你才能腾出心，去穿新的裙子，去看新的晚霞，去过新的日子。"
            elif _uses_local_emotional_forgiveness_release_variant(focus_payload):
                publish_lead = "有些事反复计较到最后，最累的往往是自己。原谅不是替谁开脱，而是终于肯把心从旧怨里慢慢放出来。"
                abstract = "一直把怨气留在心里，日子也会跟着变窄。看清无常以后，能放下的就轻轻放下，把心房打扫干净，留给阳光、花和后面真正值得的人。"
            elif _uses_local_emotional_memory_presence_variant(focus_payload):
                publish_lead = "灯火阑珊的街头，你只是多看了那个背影一眼，心里就忽然空了一下。原来有些人走远以后，也还是会在这样的时刻轻轻回来。"
                abstract = "你会反复想起，不一定是想回头，只是那段认真来过的相遇，还在日常里留了个位置。不必催自己马上释怀，想起时就想一会儿，随后照常去赴约、去上班、去吃晚饭。人会在这些普通日子里，慢慢走出那段旧路。"
            elif _uses_local_emotional_memory_reflux_variant(focus_payload):
                publish_lead = "你以为自己早就放下了，直到街头一个像他的背影、深夜一页旧聊天记录，还是会让心里轻轻一沉。反复回来的，常常是那段没说完的话、没被接住的自己。"
                abstract = "你挂在心上的，常常是那几次本来能好好说完、最后却停在半路的话。等你肯承认那段路确实走完了，再想起时，心里那一下就不会总那么重。"
            elif _uses_local_emotional_endings_acceptance_variant(focus_payload):
                publish_lead = "路过以前常去的那家店时，你还是会下意识慢一点。那段关系没走到最后，却把眼界、分寸和勇气留在了你身上。"
                abstract = "一段相遇停在这里，并不代表它只剩遗憾。你从里面带走的温暖、判断和被照亮过的那一下，会继续留在后来的生活里。"
            else:
                publish_lead = "有些人离开很久了，你还是会在某个普通时刻想起。真正难过的，不只是失去，而是舍不得承认，那段认真过的相遇已经走完。"
                abstract = "后来你会慢慢承认，有些人没能陪你走到最后，可那段相遇也不是白来。你从里面带走的认真、勇气和被照亮过的那一下，会继续留在你身上，陪你去过后面的日子。"
        intro_options = [
            item.strip()
            for item in assets.social_teaser_options
            if item.strip()
            and not _starts_with_generic_packaging_openers(item)
            and not _looks_like_packaging_instruction_leakage(item)
        ]
        if mode == "everyday_warmth_return":
            if _uses_local_everyday_warmth_small_things_priority(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "陪父母走慢一点，陪孩子玩久一点，日子会把这些时间还成温暖。",
                        "履历写不下的陪伴，往往才是后来最舍不得丢的生活。",
                        *intro_options,
                    ]
                )
            elif _uses_local_everyday_warmth_simple_happiness_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "能守住一日三餐和几句真心话，就是很具体的幸福。",
                        "家里人平安，老朋友还在，平凡日子也会发光。",
                        *intro_options,
                    ]
                )
        elif mode == "inner_settlement":
            if _uses_local_inner_settlement_stage_restart_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "没完成的清单之外，你也已经认真走过一程。",
                        "下半年，不必追平所有遗憾，先把眼前事和身边人好好珍惜。",
                        *intro_options,
                    ]
                )
            elif _uses_local_inner_settlement_homecoming_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "把鞋摆好，给自己倒杯水，普通的一天也能重新落稳。",
                        "外面的风停不停由不得你，屋里的灯可以由你亲手打开。",
                        *intro_options,
                    ]
                )
            else:
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "先把今天过回今天，心才会慢慢有地方落下来。",
                        "放不下的事，不必都在今晚想明白。",
                        *intro_options,
                    ]
                )
        elif mode == "self_reliance_inward_support" and _uses_local_self_reliance_shared_burden_variant(focus_payload):
            self_reliance_intro = _pick_local_seeded_text_variant(
                focus_payload,
                (
                    "那句“我有点累”，可以先留给愿意认真听的人。",
                    "求助不丢人，自救也不丢人。",
                    "先把今晚稳住，再把难处说清。",
                ),
            )
            self_reliance_second_intro = _pick_local_seeded_text_variant(
                {**focus_payload, "topic_title": str(focus_payload.get("topic_title") or "") + "#second"},
                (
                    "向内求，是先把慌乱放低，把眼前事处理好。",
                    "稳住自己以后，再开口、再分担，都会更清楚。",
                    "人慢慢成熟以后，会懂得自救和求助都不丢人。",
                ),
            )
            intro_options = _dedupe_nonempty_text_options(
                [
                    publish_lead,
                    self_reliance_intro,
                    self_reliance_second_intro,
                    *intro_options,
                ]
            )
        elif mode == "self_reliance_inward_support":
            self_reliance_intro = _pick_local_seeded_text_variant(
                focus_payload,
                (
                    "先把今晚稳住，再把难处说清。",
                    "求助不丢人，自救也不丢人。",
                    "先照顾好自己，再去找能分担的人。",
                ),
            )
            intro_options = _dedupe_nonempty_text_options(
                [
                    publish_lead,
                    "别急着要求自己一下子把所有事都扛好，先把眼前这一件处理掉。",
                    self_reliance_intro,
                    *intro_options,
                ]
            )
        elif mode == "pressure_interface_direct":
            intro_options = _dedupe_nonempty_text_options(
                [
                    publish_lead,
                    "把复查约回日历，把那顿饭认真吃完，就是生活重新回稳的开始。",
                    "照顾自己不是暂停责任，而是让后面的路走得更长。",
                    *intro_options,
                ]
            )
        elif mode == "supportive_appreciation":
            if _has_local_supportive_misread_profile(focus_payload):
                supportive_intro_options = [
                    "愿意翻篇，是在给关系一次机会，不是在允许同一件事重来。",
                    "道歉说完以后，真正重要的是把答应过的改变做到。",
                ]
            elif _has_local_supportive_discernment_profile(focus_payload):
                supportive_intro_options = [
                    "看得清，还愿意把场面接住的人，最该被认真珍惜。",
                    "心软不是迟钝，是明白以后还愿意留一点暖意。",
                ]
            elif any(token in draft_body_markdown for token in ("歉意", "道歉", "原谅", "真心道了歉", "把歉意说出口")):
                supportive_intro_options = [
                    "道歉最有分量的部分，发生在下一次真的做得不一样。",
                    "温柔被认真接住，才会一直是温柔。",
                ]
            elif _has_local_supportive_warmth_profile(focus_payload):
                supportive_intro_options = [
                    "心软的人，一生难遇，也值得被人好好珍惜。",
                    "收到一点暖意，还愿意再慢慢还回来的人并不多。",
                ]
            else:
                supportive_intro_options = [
                    "肯先把话接回来的人，已经把关系放在了输赢前面。",
                    "你也往前走一步，很多误会就能停在今晚。",
                ]
            intro_options = _dedupe_nonempty_text_options([publish_lead, *supportive_intro_options, *intro_options])
        elif mode == "self_worth_rebuild":
            self_worth_intro_options = (
                [
                    "把什么能答应、什么不能退说清，关系反而会更认真。",
                    "真正珍惜你的人，不会嫌你的边界麻烦。",
                ]
                if _has_local_self_worth_luxury_profile(focus_payload)
                else [
                    "说出“这次不行”以后，你会发现，尊重自己并不会失去爱。",
                    "能留下来的人，也会尊重你的不愿意。",
                ]
            )
            intro_options = _dedupe_nonempty_text_options([publish_lead, *self_worth_intro_options, *intro_options])
        elif mode == "emotional_engine_direct":
            if _uses_local_emotional_regret_forward_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "放下不是遗忘，是把旧事收好以后，仍然愿意去过新的日子。",
                        "别再用一个回不去的当年，困住正在往前的自己。",
                        *intro_options,
                    ]
                )
            elif _uses_local_emotional_forgiveness_release_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "原谅不是替谁开脱，是把自己的心从旧怨里慢慢放出来。",
                        "心里少养一点怨气，日子才会多照进一点光。",
                        *intro_options,
                    ]
                )
            elif _uses_local_emotional_endings_acceptance_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "有些关系停在半路，也会留下后来用得上的分寸。",
                        "没走完的那段路，也可能悄悄托起后来的你。",
                        *intro_options,
                    ]
                )
            elif _uses_local_emotional_memory_presence_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "有些人明明走远了，还是会在你的日常缝隙里轻轻出现。",
                        "想起时不用急着否定自己，那段认真来过的相遇还留着余温。",
                        *intro_options,
                    ]
                )
            elif _uses_local_emotional_memory_reflux_variant(focus_payload):
                intro_options = _dedupe_nonempty_text_options(
                    [
                        publish_lead,
                        "有些往事会反复回来，只是因为一直没有被好好安放。",
                        "那个总会突然想起的人，背后多半有一段没收好的旧关系。",
                        *intro_options,
                    ]
                )
        elif mode == "trust_boundary":
            intro_options = _dedupe_nonempty_text_options(
                [
                    publish_lead,
                    "一句话有人放心地信，胜过很多遍反复解释。",
                    "信任最怕的，不是争吵，是心里那一下忽然不敢再全信了。",
                    "把答应过的事做到，把该说清的话说清，信任就会在日常里越长越稳。",
                    *intro_options,
                ]
            )
        elif mode == "relationship_aftercare":
            intro_options = _dedupe_nonempty_text_options(
                [
                    publish_lead,
                    "热水放到手边的那一刻，关系已经开始往回走。",
                    "肯把刚才哪句话让人难受说清楚，争吵才不会变成隔夜的冷。",
                    *intro_options,
                ]
            )
        elif mode == "resilience_reconstruction":
            resilience_intro_options = (
                [
                    "泳池里多划出的那11下，会慢慢把命运没给的部分练回来。",
                    "她不是没有疼过，只是疼过以后，还是一次次回到水里。",
                ]
                if _has_local_resilience_pool_profile(focus_payload)
                else [
                    "今天还能把鞋带系紧、站回起点，本身就是一种力量。",
                    "生活留下的缺口，不会替你决定余生。",
                ]
            )
            intro_options = _dedupe_nonempty_text_options([publish_lead, *resilience_intro_options, *intro_options])
        if publish_lead and publish_lead not in intro_options:
            intro_options = [publish_lead, *intro_options]
        if not intro_options and publish_lead:
            intro_options = [publish_lead]

    lead_text = publish_lead.strip()
    title_text = publish_title.strip()
    if lead_text and lead_text in {title_text, draft_title.strip()}:
        rebuilt_lead = _rebuild_distinct_body_line(lead_text, title_text, draft_title.strip())
        if rebuilt_lead and rebuilt_lead not in {lead_text, title_text}:
            publish_lead = rebuilt_lead
            lead_text = rebuilt_lead
            if intro_options:
                intro_options = [publish_lead, *[item for item in intro_options if item != publish_lead]]

    abstract_text = str(abstract).strip()
    if abstract_text and abstract_text in {publish_lead.strip(), title_text, draft_title.strip()}:
        rebuilt_abstract = _rebuild_distinct_body_line(abstract_text, publish_lead.strip(), title_text, draft_title.strip())
        if rebuilt_abstract and rebuilt_abstract not in {abstract_text, publish_lead.strip(), title_text}:
            abstract = rebuilt_abstract

    if responsibility_focus:
        editor_note = "主线落在责任、家人安稳和自我照顾上，发布前只需顺一下首段停顿。"
    else:
        mode = _resolve_local_generic_fallback_mode(focus_payload)
        scene_variant = _resolve_local_cover_scene_variant(draft_title, draft_body_markdown, assets.cover_copy)
        if mode == "scene_first_progression" and scene_variant == "office":
            editor_note = "这版现场感已经够了，发布时别把导语写太满，留一点会后回味就行。"
        elif mode == "scene_first_progression" and scene_variant == "transit":
            editor_note = "这版重点就在那句没问出口的话，发布时别补太多解释，留一点空白更有劲。"
        elif mode == "scene_first_progression" and scene_variant == "household":
            editor_note = "这版已经有夜里的那口气了，发布时别往大道理上拔，让这个家的沉默自己说话。"
        elif mode == "inner_settlement":
            editor_note = "这版的力道就在那些日常小动作里，发布时别再往大道理上拔，让心慢慢落地的过程自己发生。"
        elif mode == "supportive_appreciation":
            editor_note = "这版重点是看见温柔背后的分寸，发布时少一点训诫，多保留那份被珍惜的暖意。"
        elif mode == "emotional_engine_direct" and _uses_local_emotional_regret_forward_variant(focus_payload):
            editor_note = "这版主线落在旧物触发遗憾、再把日子过回现在，发布时保留阿婆旧裙子的生活入口。"
        else:
            editor_note = "这版主线已经清楚了，发布时别再补太多解释，顺一下首段节奏就够。"

    return {
        "abstract": abstract,
        "tags": _build_local_publish_tags(
            title=publish_title,
            body_markdown=draft_body_markdown,
            publish_lead=publish_lead,
            cover_copy=assets.cover_copy,
        ),
        "editor_note": editor_note,
        "publish_title": publish_title,
        "publish_lead": publish_lead,
        "intro_options": intro_options,
    }


def _is_resilience_reconstruction_cleanup_candidate(*, title: str, body_markdown: str) -> bool:
    payload = {
        "source_type": "tracked_article",
        "article_title": title,
        "body_markdown": body_markdown,
        "reference_article_title": title,
        "reference_article_body_markdown": body_markdown,
    }
    if _has_resilience_reconstruction_focus(payload):
        return True

    paragraphs = _extract_non_heading_paragraphs(body_markdown)
    long_dense_paragraph_signal = any(
        len(_split_block_sentences(paragraph)) >= 5 and _count_resilience_dense_categories(paragraph) >= 2
        for paragraph in paragraphs
    )
    if not long_dense_paragraph_signal:
        return False

    compact = re.sub(r"\s+", "", f"{title}\n{body_markdown}")
    training_or_adversity_hits = sum(
        1
        for keyword in (
            "训练",
            "泳池",
            "划水",
            "蹬水",
            "转身",
            "万米",
            "11下",
            "手术",
            "车祸",
            "伤病",
            "拆线",
        )
        if keyword in compact
    )
    identity_or_rebuild_hits = sum(
        1
        for keyword in (
            "不被定义",
            "定义",
            "命运",
            "重建",
            "低谷",
            "边界",
            "可能性",
            "补回来",
            "托住",
            "主动权",
            "解释权",
            "交给",
        )
        if keyword in compact
    )
    return training_or_adversity_hits >= 2 and identity_or_rebuild_hits >= 1


def _count_resilience_dense_categories(text: str) -> int:
    compact = re.sub(r"\s+", "", text)
    category_keywords = (
        ("手术", "车祸", "伤口", "残肢", "骨头", "刺穿", "伤病", "炎症", "拆线", "剧痛"),
        ("训练", "泳池", "划水", "转身", "蹬水", "万米", "发力", "动作", "上岸", "补回来", "游"),
        ("肩伤", "肩背", "肩", "背痛", "背", "发紧", "发沉", "酸", "疼", "痛", "呛水", "窒息", "重心", "疲惫", "身体反应"),
        ("不被定义", "定义", "命运", "韧性", "低谷", "重建", "残缺", "边界", "拒绝", "可能性"),
    )
    return sum(1 for keywords in category_keywords if any(keyword in compact for keyword in keywords))


def _build_resilience_sentence_chunk_sizes(sentence_count: int) -> list[int]:
    if sentence_count <= 3:
        return [sentence_count]
    if sentence_count == 4:
        return [2, 2]
    if sentence_count == 5:
        return [2, 3]
    if sentence_count == 6:
        return [2, 2, 2]
    if sentence_count == 7:
        return [2, 2, 3]

    chunk_sizes = [2]
    chunk_sizes.extend(_build_resilience_sentence_chunk_sizes(sentence_count - 2))
    return chunk_sizes


def _repair_resilience_dangling_semicolon_chunks(blocks: list[str]) -> list[str]:
    if len(blocks) < 2:
        return blocks

    repaired_blocks = [block.strip() for block in blocks if block.strip()]
    index = 0
    while index < len(repaired_blocks) - 1:
        current = repaired_blocks[index]
        next_block = repaired_blocks[index + 1]
        if current.endswith(("；", ";")):
            current_sentences = _split_block_sentences(current)
            next_sentences = _split_block_sentences(next_block)
            moved = False
            while current.endswith(("；", ";")) and len(current_sentences) < 4 and next_sentences:
                current_sentences.append(next_sentences.pop(0))
                current = "".join(current_sentences).strip()
                moved = True
            if moved:
                repaired_blocks[index] = current
                if next_sentences:
                    repaired_blocks[index + 1] = "".join(next_sentences).strip()
                else:
                    del repaired_blocks[index + 1]
                    continue
        index += 1

    return repaired_blocks


def _is_tracked_article_dense_explainer_cleanup_candidate(*, title: str, body_markdown: str) -> bool:
    if _is_resilience_reconstruction_cleanup_candidate(title=title, body_markdown=body_markdown):
        return False

    paragraphs = _extract_non_heading_paragraphs(body_markdown)
    return any(
        len(_split_block_sentences(paragraph)) >= 5 and len(re.sub(r"\s+", "", paragraph)) >= 80
        for paragraph in paragraphs
    )


def _build_tracked_article_dense_sentence_chunk_sizes(sentence_count: int) -> list[int]:
    if sentence_count <= 3:
        return [sentence_count]
    if sentence_count == 4:
        return [2, 2]
    if sentence_count == 5:
        return [3, 2]
    if sentence_count == 6:
        return [3, 3]

    chunk_sizes = [3]
    chunk_sizes.extend(_build_tracked_article_dense_sentence_chunk_sizes(sentence_count - 3))
    return chunk_sizes


def _split_tracked_article_dense_explainer_residue(*, title: str, body_markdown: str) -> str:
    if not _is_tracked_article_dense_explainer_cleanup_candidate(title=title, body_markdown=body_markdown):
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

    changed = False
    rebuilt_body_blocks: list[str] = []
    original_sentence_counts: list[int] = []
    rebuilt_sentence_counts: list[int] = []

    split_markers = (
        "关系不是突然",
        "关系不是忽然",
        "这个反应",
        "更难的是",
        "收尾的用处",
        "这一步很伤",
        "拖到后面",
        "这也是为什么",
        "这些动作看着普通",
        "认出停住的位置",
        "也别急着",
        "可这条路",
        "轮到自己",
    )

    for block in body_blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if _looks_like_structure_heading(normalized):
            rebuilt_body_blocks.append(normalized)
            continue

        sentences = _split_block_sentences(normalized)
        sentence_count = len(sentences)
        if sentence_count:
            original_sentence_counts.append(sentence_count)

        compact_len = len(re.sub(r"\s+", "", normalized))
        should_split = (
            sentence_count >= 5
            and compact_len >= 80
            and any(marker in normalized for marker in split_markers)
        )
        if not should_split:
            rebuilt_body_blocks.append(normalized)
            if sentence_count:
                rebuilt_sentence_counts.append(sentence_count)
            continue

        chunk_sizes = _build_tracked_article_dense_sentence_chunk_sizes(sentence_count)
        split_blocks: list[str] = []
        cursor = 0
        for chunk_size in chunk_sizes:
            chunk = "".join(sentences[cursor : cursor + chunk_size]).strip()
            cursor += chunk_size
            if chunk:
                split_blocks.append(chunk)
        if len(split_blocks) <= 1:
            rebuilt_body_blocks.append(normalized)
            rebuilt_sentence_counts.append(sentence_count)
            continue

        changed = True
        rebuilt_body_blocks.extend(split_blocks)
        rebuilt_sentence_counts.extend(len(_split_block_sentences(chunk)) for chunk in split_blocks)

    if not changed:
        return body_markdown

    rebuilt_body_blocks = _repair_resilience_dangling_semicolon_chunks(rebuilt_body_blocks)
    rebuilt_sentence_counts = [
        len(sentences)
        for block in rebuilt_body_blocks
        for sentences in [_split_block_sentences(block)]
        if sentences
    ]

    original_long_paragraphs = sum(1 for count in original_sentence_counts if count > 4)
    rebuilt_long_paragraphs = sum(1 for count in rebuilt_sentence_counts if count > 4)
    if rebuilt_long_paragraphs >= original_long_paragraphs:
        return body_markdown

    if rebuilt_sentence_counts and original_sentence_counts:
        if max(rebuilt_sentence_counts) >= max(original_sentence_counts):
            return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + rebuilt_body_blocks
    cleaned_markdown = "\n\n".join(rebuilt_blocks)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    return cleaned_markdown


def _split_tracked_article_long_paragraph_residue(*, title: str, body_markdown: str) -> str:
    blocks = _split_markdown_blocks(body_markdown)
    if not blocks:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    changed = False
    rebuilt_body_blocks: list[str] = []
    original_sentence_counts: list[int] = []
    rebuilt_sentence_counts: list[int] = []

    for block in body_blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if _looks_like_structure_heading(normalized):
            rebuilt_body_blocks.append(normalized)
            continue

        sentences = _split_block_sentences(normalized)
        sentence_count = len(sentences)
        if sentence_count:
            original_sentence_counts.append(sentence_count)

        compact_len = len(re.sub(r"\s+", "", normalized))
        should_split = (
            sentence_count >= 6 and compact_len >= 80
        ) or (
            sentence_count == 5 and compact_len >= 110
        )
        if not should_split:
            rebuilt_body_blocks.append(normalized)
            if sentence_count:
                rebuilt_sentence_counts.append(sentence_count)
            continue

        chunk_sizes = _build_tracked_article_dense_sentence_chunk_sizes(sentence_count)
        split_blocks: list[str] = []
        cursor = 0
        for chunk_size in chunk_sizes:
            chunk = "".join(sentences[cursor : cursor + chunk_size]).strip()
            cursor += chunk_size
            if chunk:
                split_blocks.append(chunk)
        if len(split_blocks) <= 1:
            rebuilt_body_blocks.append(normalized)
            rebuilt_sentence_counts.append(sentence_count)
            continue

        changed = True
        rebuilt_body_blocks.extend(split_blocks)
        rebuilt_sentence_counts.extend(len(_split_block_sentences(chunk)) for chunk in split_blocks)

    if not changed:
        return body_markdown

    rebuilt_sentence_counts = [
        len(sentences)
        for block in rebuilt_body_blocks
        for sentences in [_split_block_sentences(block)]
        if sentences
    ]

    original_long_paragraphs = sum(1 for count in original_sentence_counts if count > 4)
    rebuilt_long_paragraphs = sum(1 for count in rebuilt_sentence_counts if count > 4)
    if rebuilt_long_paragraphs >= original_long_paragraphs:
        return body_markdown

    cleaned_markdown = "\n\n".join(([heading_block] if heading_block else []) + rebuilt_body_blocks)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    return cleaned_markdown


def _split_tracked_article_scene_anchor_residue(*, title: str, body_markdown: str) -> str:
    if _is_resilience_reconstruction_cleanup_candidate(title=title, body_markdown=body_markdown):
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

    changed = False
    rebuilt_body_blocks: list[str] = []
    explainer_lead_pattern = re.compile(
        r"^(?:可|但|只是|很多|这件事|这一步|时间久了|到后面|不少人|你会发现|别人看到的是|求助不是|前面那些|如果最近已经有一个接口开始出代价了|关系里)",
        re.UNICODE,
    )
    abstract_starter_pattern = re.compile(
        r"^(?:关系里|很多人|不少人|时间久了|你会发现|求助不是|前面那些|这件事|这一步|到后面)",
        re.UNICODE,
    )

    def _compact_len(value: str) -> int:
        return len(re.sub(r"\s+", "", value.strip().rstrip("。！？!?；;")))

    for block in body_blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if _looks_like_structure_heading(normalized):
            rebuilt_body_blocks.append(normalized)
            continue

        sentences = _split_block_sentences(normalized)
        if len(sentences) != 3:
            rebuilt_body_blocks.append(normalized)
            continue

        compact_len = len(re.sub(r"\s+", "", normalized))
        first_sentence = sentences[0].strip()
        second_sentence = sentences[1].strip()
        third_sentence = sentences[2].strip()
        first_core = first_sentence.rstrip("。！？!?；;")
        punctuation_count = sum(first_core.count(token) for token in ("，", "、", "："))
        should_split = (
            75 <= compact_len <= 220
            and 16 <= _compact_len(first_sentence) <= 56
            and not first_core.startswith(("“", '"', "‘", "'"))
            and abstract_starter_pattern.match(first_sentence) is None
            and punctuation_count >= 2
            and _compact_len(second_sentence) >= 22
            and (
                explainer_lead_pattern.match(second_sentence) is not None
                or "：" in second_sentence
                or _compact_len(third_sentence) <= 22
            )
        )
        if not should_split:
            rebuilt_body_blocks.append(normalized)
            continue

        changed = True
        rebuilt_body_blocks.append(first_sentence)
        rebuilt_body_blocks.append(second_sentence + third_sentence)

    if not changed:
        return body_markdown

    cleaned_markdown = "\n\n".join(([heading_block] if heading_block else []) + rebuilt_body_blocks)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    return cleaned_markdown


def _split_resilience_dense_paragraph_residue(*, title: str, body_markdown: str) -> str:
    if not _is_resilience_reconstruction_cleanup_candidate(title=title, body_markdown=body_markdown):
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

    changed = False
    rebuilt_body_blocks: list[str] = []
    original_sentence_counts: list[int] = []
    rebuilt_sentence_counts: list[int] = []

    for block in body_blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if _looks_like_structure_heading(normalized):
            rebuilt_body_blocks.append(normalized)
            continue

        sentences = _split_block_sentences(normalized)
        sentence_count = len(sentences)
        if sentence_count:
            original_sentence_counts.append(sentence_count)

        compact_len = len(re.sub(r"\s+", "", normalized))
        category_count = _count_resilience_dense_categories(normalized)
        min_compact_len = 110 if sentence_count >= 6 else 85
        should_split = (
            sentence_count >= 5
            and compact_len >= min_compact_len
            and category_count >= 2
            and (
                sentence_count >= 6
                or category_count >= 3
                or (
                    sentence_count == 5
                    and compact_len >= 85
                    and any(
                        keyword in normalized
                        for keyword in ("训练", "下水", "肩背", "动作", "发力", "转身", "训练表", "解释权", "命运")
                    )
                )
            )
        )
        if not should_split:
            rebuilt_body_blocks.append(normalized)
            if sentence_count:
                rebuilt_sentence_counts.append(sentence_count)
            continue

        chunk_sizes = _build_resilience_sentence_chunk_sizes(sentence_count)
        split_blocks: list[str] = []
        cursor = 0
        for chunk_size in chunk_sizes:
            chunk = "".join(sentences[cursor : cursor + chunk_size]).strip()
            cursor += chunk_size
            if chunk:
                split_blocks.append(chunk)
        if len(split_blocks) <= 1:
            rebuilt_body_blocks.append(normalized)
            rebuilt_sentence_counts.append(sentence_count)
            continue

        changed = True
        rebuilt_body_blocks.extend(split_blocks)
        rebuilt_sentence_counts.extend(len(_split_block_sentences(chunk)) for chunk in split_blocks)

    if not changed:
        return body_markdown

    rebuilt_body_blocks = _repair_resilience_dangling_semicolon_chunks(rebuilt_body_blocks)
    rebuilt_sentence_counts = [
        len(sentences)
        for block in rebuilt_body_blocks
        for sentences in [_split_block_sentences(block)]
        if sentences
    ]

    original_long_paragraphs = sum(1 for count in original_sentence_counts if count > 4)
    rebuilt_long_paragraphs = sum(1 for count in rebuilt_sentence_counts if count > 4)
    if rebuilt_long_paragraphs >= original_long_paragraphs:
        return body_markdown

    if rebuilt_sentence_counts and original_sentence_counts:
        if max(rebuilt_sentence_counts) >= max(original_sentence_counts):
            return body_markdown

    rebuilt_blocks = ([heading_block] if heading_block else []) + rebuilt_body_blocks
    cleaned_markdown = "\n\n".join(rebuilt_blocks)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    return cleaned_markdown


def _is_resilience_process_anchor_cleanup_candidate(*, title: str, body_markdown: str) -> bool:
    compact = re.sub(r"\s+", "", f"{title}\n{body_markdown}")
    keyword_groups = (
        ("手术", "伤口", "伤病", "车祸"),
        ("训练", "训练表", "下水", "发力", "动作", "泳池", "复健"),
        ("肩背", "肩膀", "背部", "发紧", "发沉", "疼", "痛"),
        ("主动权", "解释权", "低谷", "命运", "重建", "定义"),
    )
    return sum(1 for keywords in keyword_groups if any(keyword in compact for keyword in keywords)) >= 2


def _split_resilience_process_anchor_residue(*, title: str, body_markdown: str) -> str:
    if not _is_resilience_process_anchor_cleanup_candidate(title=title, body_markdown=body_markdown):
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

    changed = False
    rebuilt_body_blocks: list[str] = []

    for block in body_blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if _looks_like_structure_heading(normalized):
            rebuilt_body_blocks.append(normalized)
            continue

        sentence_count = len(_split_block_sentences(normalized))
        marker_index = normalized.find("做得差，流程还在；")
        should_split = (
            sentence_count >= 5
            and marker_index > 0
            and "流程还在" in normalized
            and "下一组" in normalized
            and any(keyword in normalized for keyword in ("泳池边", "复健室", "计划表", "把人往回拽", "不讲情面的东西"))
        )
        if not should_split:
            rebuilt_body_blocks.append(normalized)
            continue

        left = normalized[:marker_index].rstrip()
        right = normalized[marker_index:].lstrip()
        if not left or not right:
            rebuilt_body_blocks.append(normalized)
            continue

        rebuilt_body_blocks.extend((left, right))
        changed = True

    if not changed:
        return body_markdown

    cleaned_markdown = "\n\n".join(([heading_block] if heading_block else []) + rebuilt_body_blocks)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown

    original_counts = [len(_split_block_sentences(block)) for block in _extract_non_heading_paragraphs(body_markdown)]
    rebuilt_counts = [len(_split_block_sentences(block)) for block in _extract_non_heading_paragraphs(cleaned_markdown)]
    if rebuilt_counts and original_counts and max(rebuilt_counts) >= max(original_counts):
        return body_markdown

    return cleaned_markdown


def _replace_duplicate_exact_phrase(
    text: str,
    *,
    phrase: str,
    replacement: str,
    keep_count: int,
) -> str:
    if keep_count < 0:
        keep_count = 0

    result_parts: list[str] = []
    cursor = 0
    seen = 0
    while True:
        index = text.find(phrase, cursor)
        if index < 0:
            result_parts.append(text[cursor:])
            break
        result_parts.append(text[cursor:index])
        if seen < keep_count:
            result_parts.append(phrase)
        else:
            result_parts.append(replacement)
        seen += 1
        cursor = index + len(phrase)
    return "".join(result_parts)


def _is_resilience_hook_echo_cleanup_candidate(*, title: str, body_markdown: str) -> bool:
    keep_count = 0 if "多划11下" in title else 1
    if body_markdown.count("多划11下") <= keep_count:
        return False

    compact = re.sub(r"\s+", "", f"{title}\n{body_markdown}")
    keyword_groups = (
        ("手术", "车祸", "伤病", "伤口", "拆线"),
        ("训练", "泳池", "划水", "蹬水", "转身", "万米", "发力", "动作", "复健", "补回来"),
        ("肩伤", "肩背", "肩膀", "背部", "酸胀", "发紧", "发沉", "疼", "痛", "身体受限"),
        ("低谷", "解释权", "主动权", "重建", "托住", "命运", "定义", "不被定义"),
    )
    return sum(1 for keywords in keyword_groups if any(keyword in compact for keyword in keywords)) >= 2


def _soften_resilience_hook_echo_residue(*, title: str, body_markdown: str) -> str:
    if not _is_resilience_hook_echo_cleanup_candidate(title=title, body_markdown=body_markdown):
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

    keep_count = 0 if "多划11下" in title else 1
    cleaned_body = _replace_duplicate_exact_phrase(
        "\n\n".join(body_blocks),
        phrase="多划11下",
        replacement="那11下",
        keep_count=keep_count,
    )
    cleaned = "\n\n".join(([heading_block] if heading_block else []) + ([cleaned_body] if cleaned_body else []))
    cleaned = cleaned.replace("它也还是自己的。", "它也还在自己手里。")

    return cleaned


def _is_resilience_local_reference_cleanup_candidate(*, title: str, body_markdown: str) -> bool:
    if body_markdown.count("那11下") < 2:
        return False

    compact = re.sub(r"\s+", "", f"{title}\n{body_markdown}")
    keyword_groups = (
        ("手术", "车祸", "伤病", "伤口", "拆线"),
        ("训练", "泳池", "划水", "蹬水", "转身", "万米", "发力", "动作", "复健", "补回来"),
        ("肩伤", "肩背", "肩膀", "背部", "酸胀", "发紧", "发沉", "疼", "痛", "身体受限"),
        ("低谷", "解释权", "主动权", "重建", "托住", "命运", "定义", "不被定义"),
    )
    return sum(1 for keywords in keyword_groups if any(keyword in compact for keyword in keywords)) >= 2


def _soften_resilience_local_reference_echo_residue(*, title: str, body_markdown: str) -> str:
    if not _is_resilience_local_reference_cleanup_candidate(title=title, body_markdown=body_markdown):
        return body_markdown

    cleaned = body_markdown
    cleaned = cleaned.replace("那11下后面，可能是", "后面拖着的，往往是")
    cleaned = cleaned.replace("哪怕只是补齐那11下", "哪怕只是把那组动作补齐")
    cleaned = cleaned.replace("那11下，表面上是训练量", "那组补回来的动作，表面上是训练量")
    cleaned = cleaned.replace("只要还能补齐那11下", "只要还能把这一组补齐")
    cleaned = cleaned.replace("把那11下划完", "把这一组划完")
    cleaned = cleaned.replace("那组补回来的动作", "补回来的这一组动作")
    return cleaned


def _repair_repeated_phrase_typo_residue(*, title: str, body_markdown: str) -> str:
    replacements = {
        "对方方不方便": "对方不方便",
        "是是不是": "是不是",
        "自己你": "自己",
    }
    cleaned = body_markdown
    for typo, replacement in replacements.items():
        cleaned = cleaned.replace(typo, replacement)
    cleaned = re.sub(
        r"((?:心里|心底|眼前|这些年|生活里|关系里|那个瞬间|那一刻)?的?)(不容易|辛苦|疲惫|委屈)和\2",
        r"\1\2",
        cleaned,
    )
    return cleaned


def _repair_tracked_article_dangling_semicolon_chunks(*, title: str, body_markdown: str) -> str:
    blocks = _split_markdown_blocks(body_markdown)
    if len(blocks) < 2:
        return body_markdown

    heading_block: str | None = None
    if blocks[0].lstrip().startswith("#"):
        heading_block = blocks[0]
        body_blocks = blocks[1:]
    else:
        body_blocks = blocks[:]

    repaired_body_blocks = _repair_resilience_dangling_semicolon_chunks(body_blocks)
    if repaired_body_blocks == body_blocks:
        return body_markdown

    rebuilt_markdown = "\n\n".join(([heading_block] if heading_block else []) + repaired_body_blocks)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    repaired_summary = evaluate_ai_flavor_risk(title=title, body_markdown=rebuilt_markdown)
    if repaired_summary.score > original_summary.score:
        return body_markdown
    return rebuilt_markdown


def _should_preserve_response_priority_followup_mobile_cadence(*, title: str, body_markdown: str) -> bool:
    corpus = f"{title} {body_markdown}"
    followup_hits = sum(
        1 for keyword in ("点赞", "评论", "追问", "读懂", "没说完", "停下来", "我没事", "路过") if keyword in corpus
    )
    classic_hits = sum(
        1 for keyword in ("没时间", "优先", "顺序", "红灯", "24小时在线", "时间在哪儿") if keyword in corpus
    )
    interaction_hits = sum(
        1 for keyword in ("评论", "追问", "读懂", "没说完", "停下来", "我没事", "注意力", "点赞") if keyword in corpus
    )
    care_hits = sum(1 for keyword in ("在意", "在乎", "关心", "珍惜", "踏实") if keyword in corpus)
    relationship_hits = sum(
        1 for keyword in ("吵架", "冷战", "和好", "修复", "冷暴力", "复合") if keyword in corpus
    )
    return (
        followup_hits >= 4
        and interaction_hits >= 5
        and care_hits >= 1
        and followup_hits >= classic_hits + 2
        and relationship_hits <= 2
    )
def _should_preserve_supportive_appreciation_mobile_cadence(*, title: str, body_markdown: str) -> bool:
    return _resolve_tracked_article_candidate_mode(title=title, markdown=body_markdown) == "supportive_appreciation"


def _collapse_short_judgment_residue(*, title: str, body_markdown: str) -> str:
    if _should_preserve_supportive_appreciation_mobile_cadence(title=title, body_markdown=body_markdown) or _should_preserve_response_priority_followup_mobile_cadence(title=title, body_markdown=body_markdown):
        return body_markdown

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
        if _should_attach_to_next(normalized):
            return extract_short_judgment_paragraphs(normalized) == [normalized]
        if _looks_like_structure_heading(normalized):
            return False
        return extract_short_judgment_paragraphs(normalized) == [normalized]

    def _should_attach_to_next(block: str) -> bool:
        normalized = block.strip().rstrip("。！？!?；;")
        return any(
            normalized.startswith(prefix)
            for prefix in (
                "先别",
                "把明天",
                "把今天",
                "别急着",
                "别把",
            )
        )

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
    if _resolve_tracked_article_candidate_mode(title=title, markdown=body_markdown) in {"self_worth_rebuild", "everyday_warmth_return"}:
        return body_markdown

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

    if _resolve_tracked_article_candidate_mode(title=title, markdown=body_markdown) in {"self_worth_rebuild", "everyday_warmth_return"}:
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
    if _should_preserve_supportive_appreciation_mobile_cadence(title=title, body_markdown=body_markdown) or _should_preserve_response_priority_followup_mobile_cadence(title=title, body_markdown=body_markdown):
        return body_markdown

    original_pairs = count_short_long_cadence_pairs(body_markdown)

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
        if _should_attach_to_next(normalized):
            return extract_short_judgment_paragraphs(normalized) == [normalized]
        if _looks_like_structure_heading(normalized):
            return False
        return extract_short_judgment_paragraphs(normalized) == [normalized]

    def _should_attach_to_next(block: str) -> bool:
        normalized = block.strip().rstrip("。！？!?；;")
        return any(
            normalized.startswith(prefix)
            for prefix in (
                "先别",
                "把明天",
                "把今天",
                "别急着",
                "别把",
            )
        )

    has_attach_to_next_candidate = any(
        _is_short_judgment_block(body_blocks[index].strip())
        and _should_attach_to_next(body_blocks[index].strip())
        and _compact_len(body_blocks[index + 1].strip()) >= 60
        for index in range(1, len(body_blocks) - 1)
    )
    if original_pairs < 2 and not has_attach_to_next_candidate:
        return body_markdown

    changed = False
    index = 1
    while index < len(body_blocks) - 1:
        current_block = body_blocks[index].strip()
        previous_block = body_blocks[index - 1].strip()
        next_block = body_blocks[index + 1].strip()
        if not _is_short_judgment_block(current_block):
            index += 1
            continue
        attach_to_next = _should_attach_to_next(current_block)
        if _compact_len(next_block) < 60:
            index += 1
            continue
        if not attach_to_next and _compact_len(previous_block) < 60:
            index += 1
            continue
        if attach_to_next:
            body_blocks[index + 1] = current_block + body_blocks[index + 1].lstrip()
            del body_blocks[index]
        else:
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
    if _should_preserve_supportive_appreciation_mobile_cadence(title=title, body_markdown=body_markdown) or _should_preserve_response_priority_followup_mobile_cadence(title=title, body_markdown=body_markdown):
        return body_markdown

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
    if _should_preserve_supportive_appreciation_mobile_cadence(title=title, body_markdown=body_markdown) or _should_preserve_response_priority_followup_mobile_cadence(title=title, body_markdown=body_markdown):
        return body_markdown

    if _resolve_tracked_article_candidate_mode(title=title, markdown=body_markdown) in {"self_worth_rebuild", "everyday_warmth_return"}:
        return body_markdown

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
    if _should_preserve_supportive_appreciation_mobile_cadence(title=title, body_markdown=body_markdown) or _should_preserve_response_priority_followup_mobile_cadence(title=title, body_markdown=body_markdown):
        return body_markdown

    if _resolve_tracked_article_candidate_mode(title=title, markdown=body_markdown) in {"self_worth_rebuild", "everyday_warmth_return"}:
        return body_markdown

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

    short_paragraph_merge_cap = (
        95
        if len(current_blocks) >= 12 and max(_compact_len(block) for block in current_blocks) <= 80
        else None
    )

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
                combined_len = current_len + neighbor_len
                if neighbor_len < 35 or combined_len > 320:
                    continue
                if short_paragraph_merge_cap is not None and combined_len > short_paragraph_merge_cap:
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
                value += max(0, 18 - abs(combined_len - 150) // 10)
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
                if short_paragraph_merge_cap is not None and combined_len > short_paragraph_merge_cap:
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
                if short_paragraph_merge_cap is not None and combined_len > short_paragraph_merge_cap:
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
    if not original_not_ab or len(original_not_ab) > 5:
        return body_markdown

    use_light_rewrite = (
        len(original_not_ab) >= 4
        or "并不是" in body_markdown
        or "也不是" in body_markdown
        or any(skeleton.count("不是") >= 2 for skeleton in original_not_ab)
    )

    heavy_pattern = re.compile(
        r"不是([^。！？!?；;\n]{1,24}?)[，,、]?\s*(?:而?是)([^。！？!?；;\n]{1,80})",
        re.UNICODE,
    )
    light_pattern = re.compile(
        r"(?:并)?不是([^。！？!?；;\n]{1,24}?)(?:[，,、]\s*(她|他|你|我))?\s*(?:(而是|只是|就是|(?<!不)是))([^。！？!?；;\n]{1,80})",
        re.UNICODE,
    )
    pattern = light_pattern if use_light_rewrite else heavy_pattern
    if not pattern.search(body_markdown):
        return body_markdown

    def _find_sentence_start(content: str, match_start: int) -> int:
        separators = "。！？!?；;\n"
        start = 0
        for index in range(match_start - 1, -1, -1):
            if content[index] in separators:
                start = index + 1
                break
        return start

    def _strip_right_leading_subject(text: str) -> str:
        return re.sub(
            r"^(?:我|你|他|她)(?=(?:先|就|会|得|想|要|能|把|开始|已经|也|还|再|总|正在|不|没))",
            "",
            text.strip(),
        ).strip()

    def _normalize_not_ab_left_fragment(text: str) -> str:
        normalized = text.strip()
        normalized = re.sub(r"^(因为|只是|就只是|并不是因为)", "", normalized).strip()
        normalized = re.sub(r"而$", "", normalized).strip()
        normalized = re.sub(r"^(她|他|你|我)(?=真的|没|不|总|还|先)", "", normalized).strip()
        return normalized

    def _is_scored_not_ab_match(match: re.Match[str]) -> bool:
        if len(original_not_ab) > 2:
            return True
        matched_text = match.group(0).strip()
        return any(matched_text.startswith(skeleton) for skeleton in original_not_ab)

    def _build_not_ab_tail(left: str) -> str:
        normalized = _normalize_not_ab_left_fragment(left)
        if not normalized:
            return ""
        if normalized.startswith(("突然一下到了重症那一步", "最近没休息好", "病名本身", "不爱自己", "没感觉", "没有感觉")):
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

    def _rewrite_not_ab_light(match: re.Match[str]) -> str:
        if not _is_scored_not_ab_match(match):
            return match.group(0)
        left = match.group(1).strip()
        subject = (match.group(2) or "").strip()
        transition = match.group(3).strip()
        right = match.group(4).strip()
        sentence_start = _find_sentence_start(match.string, match.start())
        prefix = match.string[sentence_start:match.start()]
        prefix_compact = prefix.strip().rstrip("，,、：:")

        if re.search(r"(?:最|真正)?难的$", prefix_compact):
            return match.group(0)

        right = re.sub(r"开始的(?=[:：，,]|$)", "开始", right)
        core_right = _strip_right_leading_subject(right)

        if subject:
            if prefix_compact.endswith(subject):
                return core_right
            return right if right.startswith(subject) else f"{subject}{core_right}"

        if any(token in left for token in ("没对象发", "没有对象发", "没人可发")) and prefix_compact.endswith("很多次都"):
            return "有人可发，可一发出去就得解释"

        if transition in ("只是", "就是"):
            return right

        if "不是" in left and "消失" in prefix_compact:
            left_segments = [segment.strip(" ，,、") for segment in left.split("，") if segment.strip(" ，,、")]
            first_segment = left_segments[0] if left_segments else ""
            nested_segment = left.rsplit("不是", 1)[-1].strip(" ，,、")
            disclaimers: list[str] = []
            if first_segment:
                disclaimers.append(f"不一定是{first_segment}")
            if nested_segment and nested_segment != first_segment:
                disclaimers.append(f"也不一定是{nested_segment}")
                if disclaimers:
                    return f"往往是{core_right}，{'，'.join(disclaimers)}"

        if prefix_compact.endswith("失联") and core_right.startswith("从"):
            return core_right

        if prefix_compact == "这" and core_right == "校准":
            return "更像一次校准"

        if prefix_compact.endswith("很多关系") and core_right.startswith("输在"):
            return f"到最后{core_right}"

        if prefix_compact == "这":
            return f"是{core_right}"

        if core_right.startswith("从"):
            return f"是{core_right}"

        if core_right.startswith(("输在", "耗在", "落在", "卡在", "长在")):
            return f"是{core_right}"

        if prefix_compact.endswith(
            (
                "通常",
                "往往",
                "难的",
                "最难的",
                "第一反应",
                "第一反应通常",
                "最先变钝的",
                "最先变钝的通常",
                "这种迟钝",
                "最先消失的",
                "关系里最先消失的",
            )
        ):
            return f"是{core_right}"

        return f"是{core_right}"

    def _rewrite_not_ab(match: re.Match[str]) -> str:
        if not _is_scored_not_ab_match(match):
            return match.group(0)
        left = match.group(1).strip()
        right = match.group(2).strip()
        sentence_start = _find_sentence_start(match.string, match.start())
        prefix = match.string[sentence_start:match.start()]
        prefix_compact = prefix.strip().rstrip("，,、：:")
        if re.search(r"(?:最|真正)?难的$", prefix_compact):
            return match.group(0)
        tail = _build_not_ab_tail(left)
        if right.startswith("因为"):
            return f"{right}。{tail}" if tail else right
        return f"{right}。{tail}" if tail else right

    softened_markdown = pattern.sub(_rewrite_not_ab_light if use_light_rewrite else _rewrite_not_ab, body_markdown)
    if softened_markdown == body_markdown:
        return body_markdown

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    softened_summary = evaluate_ai_flavor_risk(title=title, body_markdown=softened_markdown)
    if softened_summary.score > original_summary.score:
        remaining_not_ab = extract_not_ab_skeletons(softened_markdown)
        removable_followup_residue = all(
            ("断裂回钩尾句" in hit or "截断残句" in hit)
            for hit in softened_summary.hits
        )
        if not (len(remaining_not_ab) < len(original_not_ab) and removable_followup_residue):
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


def _repair_tracked_article_fragment_residue(*, title: str, body_markdown: str) -> str:
    cleaned = body_markdown
    cleaned = cleaned.replace("**。", "**")
    cleaned = re.sub(
        r"真要把它(?:算成|当成)[^。！？!?；;\n]{0,24}(?:的)?。?\s*(?:它常常就|这|要)。?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"这在装作自己没事。?\s*真要把它(?:算成|当成)[^。！？!?；;\n]{0,24}。?\s*[^。！？!?；;\n]{1,8}的人，通常。?",
        "",
        cleaned,
    )
    cleaned = cleaned.replace("你没说出口的，往往信息。", "你没说出口的，往往就是那些关键信息。")
    cleaned = cleaned.replace("它们给团队添堵。它们只是把本来就存在的成本，放回它该被看见的位置。", "它们不是在给团队添堵。它们只是把本来就存在的成本，放回它该被看见的位置。")
    cleaned = cleaned.replace("这逼自己感恩。", "这不是逼自己感恩。")
    cleaned = re.sub(
        r"这些认识，从一段没走到最后的关系里长出来的。真要把它算成天上掉下来的。很多时候，它们就。",
        "这些认识，本来就是从一段没走到最后的关系里长出来的。很多时候，我们只是忘了把它们算回自己的成长。",
        cleaned,
    )
    cleaned = re.sub(
        r"然后把它放回过去。替自己惋惜。只是分清，这段关系有没有留下来，和它有没有意义，从来在往前走了。真要把它算成一回事。能这样想起，已经。",
        "然后把它放回过去，替自己惋惜，也替那段认真找个去处。你只要分清：这段关系有没有留下来，和它有没有意义，本来就不是一回事。能这样想起，已经是在往前走了。",
        cleaned,
    )
    cleaned = re.sub(r"([。！？!?])\s*([。！？!?])+", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned if cleaned != body_markdown else body_markdown


_RESPONSIBILITY_SHELTER_OUTPUT_REPLACEMENTS = (
    ("身体还能不能撑一下", "自己还能不能缓一下"),
    ("可身体会记账。", "也该给自己留一点余地。"),
    ("身体会记账", "也该给自己留一点余地"),
    (
        "睡眠变浅、心里的不容易不说、情绪硬吞、身体先报警，这些都是一个人先顶着留下来的痕迹。",
        "话少了、安排更满了、心里的不容易先放到后面，这些都在提醒你，也该给自己留一点余地。",
    ),
    ("情绪硬吞", "心里的不容易先放到后面"),
    ("身体先报警", "身体也在提醒你慢一点"),
    ("一个人先顶着留下来的痕迹", "一路认真安排后的提醒"),
    ("这些都是一个人先顶着", "这些都在提醒你"),    ("撑不撑得住", "怎样把顺序理清"),
    ("能不能撑住", "能不能稳住"),
    ("继续撑住", "继续认真往前走"),
    ("撑住了一家人的基本秩序", "托住了一家人的基本秩序"),
    ("撑住一家人的基本秩序", "托住一家人的基本秩序"),
    ("你为家多想的每一步，", "那些为家多想的每一步，"),
    ("你先把能协调的时间圈出来，", "能协调的时间先圈出来，"),
    ("你在纸上把事情一项项写下来，", "纸上把事情一项项写下来，"),
    ("你可以把话说得更慢一点，", "有些话可以说得更慢一点，"),
    ("你替一家人多想一步，", "替一家人多想一步的时候，"),
    ("长期扛压", "长期把家里的事放在心上"),
    ("扛住压力", "先把事情接住"),
    ("一路忍着、扛着", "一步步安排、一件件接住"),
    ("忍着、扛着", "安排着、接住着"),
    ("成年人扛着的那些压力", "成年人放在心上的那些责任"),
    ("真正扛着压力往前走", "把责任放在心上认真往前走"),
    ("很多人以为，责任重的人一定很有力量。其实不是。责任最重的地方，往往只是心里一直装着想守护的人。", "责任重的人，也会累。只是心里一直装着想守护的人，所以愿意把眼前的事再理一理。"),
    ("扛着压力", "带着责任"),
    ("白天扛事晚上崩一下", "白天把事情理顺、晚上才松一口气"),
    ("长期在家庭里当支柱", "长期把家里的事放在心上"),
    ("天生坚强", "没有自己的难处"),
    ("崩一下", "松一口气"),
    ("这些辛苦没有白扛", "这些认真没有白费"),
    ("辛苦没有白扛", "认真没有白费"),
    ("辛苦未必值得歌颂，但也没有白扛", "这些认真不必夸大，也没有白费"),
    ("辛苦未必值得歌颂", "这些认真不必夸大"),
    ("苦情赞歌", "吃苦叙事"),
    ("没有白扛", "没有白忙"),
    ("没白扛", "没有白忙"),
    ("白扛", "白忙"),
    ("暂时不能倒", "还要先把事情理顺"),
    ("不能倒下", "还要把顺序理清"),
    ("不能倒", "还要把顺序理清"),
    ("排位靠后的自觉", "先顾家里的习惯"),
    ("这么苦还要撑", "这么不容易还要把家里理顺"),
    ("病痛和担心都忍着", "病痛和担心都先往后放"),
    ("忍着", "先往后放"),
    ("吞下去的辛苦", "一路走来的认真"),
    ("把慌乱咽下去", "把顺序理清楚"),
    ("身体报警", "身体提醒"),
    ("身体告警", "身体提醒"),
    ("代价也不是没有。", "不容易也是真的。"),
    ("真正重的地方，他心里一直装着想守护的人。", "真正重的地方，藏在那些一直想守护的人身上。"),
    ("生活里的稳，边走边收拾出来的。", "生活里的稳，要边走边慢慢收拾出来。"),
    ("很多人知道自己一松，家里的地面就会晃。", "很多人也会累。只是想到家里的事还在那儿，就又把手头的顺序理了一遍。"),
    ("“责任把日子过得更稳。”", "“责任到最后，是把日子过得更稳，也把自己照顾得更柔软。”"),
    ("“心里留一盏灯，为了你知道，自己还走得下去。”", "“心里留一盏灯，是为了提醒自己：哪怕今天不容易，明天也还能往前走。”"),
    ("电话的那头，是父母、孩子和现实开销。电话这头，是一个人把不容易咽回去，把答案先准备好。", "家里一有事，父母、孩子和这个月的安排就会先排到心里。"),
    ("电话那头是父母、孩子和现实开销，电话这头是沉默、认真和继续往前的人。", "家里的事一冒出来，人就会先把眼前的顺序理清。"),
    ("不是因为自己天生更能把事情接住，而是因为一旦肩上有了责任，心里就会自动多想一步", "一旦肩上有了责任，心里就会自动多想一步"),
    ("不是因为自己天生更能把事情接住，而是因为心里清楚，", "只是心里清楚，"),
    ("真正重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。", "真正重的地方，藏在那些一直想守护的人身上。"),
    ("不只是为了把工作做完，也是在把明天的麻烦往前挪一挪。", "也想把明天的麻烦往前挪一挪。"),
    ("生活里的稳，不是等风停了才有，而是边走边收拾出来的。", "生活里的稳，要边走边慢慢收拾出来。"),
    ("很多人不是不累，只是知道自己一松，家里的地面就会晃。", "很多人也会累。只是想到家里的事还在那儿，就又把手头的顺序理了一遍。"),
    ("责任不是把自己磨得更硬，而是把日子过得更稳。", "责任到最后，是把日子过得更稳，也把自己照顾得更柔软。"),
    ("心里留一盏灯，不是为了照给别人看，是为了你知道，自己还走得下去。", "心里留一盏灯，是为了提醒自己：哪怕今天不容易，明天也还能往前走。"),
    ("金句：责任不是把自己活成钢铁，而是明知道不容易，仍愿意把灯留在家里。", "有些责任不必说得轰烈，它只是让人明知道不容易，还是愿意把灯留在家里。"),
    ("金句：人不是靠硬扛证明价值的，很多时候，是靠把日子稳稳接住，才真正站住了。", "人不必靠硬撑证明自己。把日子一件件接稳，也是在认真站住。"),
    ("不是因为自己天生更能把事情接住，而是因为心里有一条很清楚的线：先把该稳住的稳住。", "他们心里有一条很清楚的线：先把该稳住的稳住。"),
    ("不是在说“我要变强”的那个瞬间，而是在默默把日子一项一项排好。", "常常发生在默默把日子一项一项排好的时候。"),
    ("不是工作本身，而是心里一直装着想守护的人。", "常常藏在那些想守护的人身上。"),
    ("不是一口气完成什么大事，而是今天把明天的麻烦往后推一推", "不必一口气完成什么大事，先把明天的麻烦往后推一推"),
    ("家庭支持变薄、养育成本变高、照护责任前移，让很多人从“能把事情接住”变成“必须扛”，把结构性压力写透。", "父母的事要惦记，孩子的事要跟上，工作那头也不能松。"),
    ("睡眠、情绪、关系、判断力与身体都在透支，表面是稳住家里，背后是自己越来越像一盏快没油的灯。", "父母少一点担心，孩子多一点底气，家里多一点踏实，这些都在告诉你，自己没有白忙。"),
    ("被透支的是睡眠、耐心、身体和自我感受", "最先被挪走的，常常是睡眠、耐心和属于自己的那点空隙"),
    ("被透支的是睡眠", "最先被挪走的是睡眠"),
    ("自己的情绪、不容易、心里的不容易", "自己的情绪和心里的不容易"),
    ("压力慢慢堆在肩上", "事情一件件压到眼前"),
    ("退路一点点变窄", "留给自己的空隙一点点变少"),
    ("深夜才敢喘", "晚上才慢慢缓一口气"),
    ("家里的秩序就可能乱一截", "家里就会跟着乱一点"),
    ("所谓安稳，从来不是凭空掉下来的。", "家里的踏实，往往是一件件小事垫起来的。"),
    ("那一刻，辛苦才终于有了落点。", "到这个时候，辛苦才终于有了落点。"),
    ("那一刻才懂", "后来才慢慢懂"),
    ("那一刻，", "那个瞬间，"),
    ("。那一刻，", "。那个瞬间，"),
    ("所爱之人的生活", "家里人的生活"),
    ("所爱之人", "家里人"),
    ("很多成年人真正累的", "很多成年人真正不容易的"),
    ("真正累的", "真正不容易的"),
    ("不只是为了把难关熬过去", "不只是为了把眼前这段路走过去"),
    ("把难关熬过去", "把眼前这段路走过去"),
    ("一路撑着", "一路认真走着"),
    ("撑着", "认真走着"),
    ("撑不住", "想歇一歇"),
    ("责任会逼着人", "责任会让人"),
    ("很多人会发现，", "很多时候，"),
    ("很多成年人就是这样", "很多人就是这样"),
    ("很多撑住生活的瞬间", "很多认真生活的瞬间"),
    ("不能松手的习惯", "放在心上的牵挂"),
    ("为家人撑起安稳的人", "为家人托起安稳的人"),
    ("肩上扛着责任的人", "肩上有责任的人"),
    ("真正让人撑下去的，常常不是成就感，而是家里那份可感的安稳。", "真正让人继续往前走的，常常是家里那份可感的安稳。"),
    ("不是为了证明自己，而是为了让家人过得更稳一点", "最后都落在让家人过得更稳一点这件事上"),
    ("撑起安稳", "托起安稳"),
    ("扛着责任", "有责任"),
    ("撑稳", "托稳"),
    ("真正的撑住", "真正的稳住"),
    ("长期硬撑", "长时间不容易"),
    ("夜里硬撑", "夜里不容易"),
    ("硬撑", "先把事情接住"),
    ("多能扛", "多厉害"),
    ("不是天生能把事情接住，而是很多责任都赶在同一段日子里压了上来", "很多责任常常赶在同一段日子里压上来，你就习惯先把顺序理清"),
    ("不是天生能扛，而是很多责任都赶在同一段日子里压了上来", "很多责任常常赶在同一段日子里压上来，你就习惯先把顺序理清"),
    ("不是天生能把事情接住", "很多责任常常赶在同一段日子里压上来"),
    ("不是天生能扛", "很多责任常常赶在同一段日子里压上来"),
    ("能扛", "能把事情接住"),
    ("不是不能把事情接住，而是总在来不及整理自己时就被生活推着往前", "很多事常常赶在一起，需要先把顺序理清"),
    ("不能把事情接住", "需要先把顺序理清"),
    ("咽下去的那口气", "压住的那口气"),
    ("咽下去", "压住"),
    ("咽下", "压住"),
    ("或倒下", "或停下"),
    ("倒下", "停下"),
    ("苦当然是真的。", "不容易当然是真的。"),
    ("苦不值得夸", "这些不容易不必夸大"),
    ("苦难不值得歌颂", "难处不必被歌颂"),
    ("苦难", "难处"),
    ("苦水", "不容易"),
    ("悲愁", "低落"),
    ("风浪", "忙乱"),
    ("委屈、疲惫、害怕", "心里的不容易和慌乱"),
    ("疲惫", "不容易"),
    ("咬牙", "撑着"),
    ("不是不想轻松一点，是知道日子不能只凭情绪往前走。", "也想轻松一点，只是知道日子不能只凭情绪往前走。"),
    ("很多坚持不是为了证明什么，而是为了把一家人的日子慢慢收拢起来。", "很多坚持，是为了把一家人的日子慢慢收拢起来。"),
    ("真正的责任，不是把自己耗尽，而是在不容易里仍然留住照亮别人的那一点心气。", "真正的责任，是在不容易里仍然留住一点照亮日子的心气。"),
    ("最难得的不是逞强，是不乱。", "最难得的，是遇事不乱。"),
    ("走到今天，你已经不是在一个人先顶着了，你是在把生活往更稳的地方推。", "走到今天，你是在把生活往更稳的地方推。"),
    ("不是事情多。", "不只是事情多。"),
)


def _strip_responsibility_shelter_instruction_leakage(value: str) -> str:
    blocks = _split_markdown_blocks(value)
    if not blocks:
        return value

    rebuilt_blocks: list[str] = []
    changed = False
    for block in blocks:
        normalized = block.strip()
        if not normalized:
            continue
        instruction_like_heading = bool(
            re.match(r"^(?:先|再|最后)?写出[^：:\n]{0,80}[:：]", normalized)
            or re.match(r"^把[“\"']?[^”\"'。！？!?；;\n]{0,80}[”\"']?写清楚[。！？!?]?$", normalized)
        )
        if (_looks_like_structure_heading(normalized) or normalized.lstrip().startswith("#")) and not instruction_like_heading:
            rebuilt_blocks.append(normalized)
            continue

        sentences = _split_block_sentences(normalized)
        if not sentences:
            cleaned_block = _clean_local_fallback_instruction_phrase(normalized)
            if cleaned_block != normalized:
                changed = True
            if cleaned_block:
                rebuilt_blocks.append(cleaned_block)
            continue

        cleaned_sentences: list[str] = []
        for sentence in sentences:
            cleaned_sentence = sentence.strip()
            without_prefix = re.sub(
                r"^(?:先|再|最后)?写出[^：:\n]{0,80}[:：]\s*",
                "",
                cleaned_sentence,
            ).strip()
            if without_prefix != cleaned_sentence:
                changed = True
                cleaned_sentence = without_prefix
            if re.fullmatch(
                r"把[“\"']?[^”\"'。！？!?；;\n]{0,80}[”\"']?写清楚[。！？!?]?",
                cleaned_sentence,
            ):
                changed = True
                continue
            if re.fullmatch(
                r"(?:先|再|最后)?(?:写清楚|点出|说明|交代|拆开|落回)[^。！？!?；;\n]{0,140}[。！？!?]?",
                cleaned_sentence,
            ):
                changed = True
                continue
            if re.fullmatch(
                r"(?:这份|这种|这些)[^。！？!?；;\n]{0,24}为什么会[^。！？!?；;\n]{0,80}[。！？!?]?",
                cleaned_sentence,
            ):
                changed = True
                continue
            without_instruction = re.sub(
                r"^把[“\"']?[^”\"'。！？!?；;\n]{0,80}[”\"']?写清楚[。！？!?]?\s*",
                "",
                cleaned_sentence,
            ).strip()
            if without_instruction != cleaned_sentence:
                changed = True
                cleaned_sentence = without_instruction
            if cleaned_sentence:
                cleaned_sentences.append(cleaned_sentence)

        if cleaned_sentences:
            rebuilt_blocks.append("".join(cleaned_sentences))
        elif normalized:
            changed = True

    if not changed:
        return value
    return "\n\n".join(rebuilt_blocks)


def _soften_responsibility_shelter_not_ab_residue(value: str) -> str:
    cleaned = str(value or "")
    exact_replacements = (
        (
            "当一个人的肩上同时扛着父母、孩子和账单，真正耗掉他的，往往不是苦，而是没有停下来整理自己。",
            "当一个人的肩上同时装着父母、孩子和账单，真正耗人的，往往是一直没空停下来整理自己。",
        ),
        (
            "很多成年人不是突然变得能把事情接住了，而是先学会把家里的事一件件理顺",
            "很多人是慢慢学会把家里的事一件件理顺",
        ),
        ("不是没感受，而是明白眼下最要紧的，", "也有感受，只是明白眼下最要紧的，"),
        ("不是把话说满，而是把生活安排稳", "先把生活安排稳"),
        (
            "责任最重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。",
            "责任最重的地方，常常是心里一直装着想守护的人。",
        ),
        ("金句不是用来鼓劲的，是用来提醒自己：", "有句话很朴素："),
        (
            "另一句更简单，真正把家撑起来的，从来不是口气，而是一次次把事情办妥的耐心。",
            "真正把家撑起来的，常常是一次次把事情办妥的耐心。",
        ),        (
            "不是不在乎自己，而是心里总有个顺序：先让一家人安稳，自己晚一点再说",
            "也在乎自己，只是心里总有个顺序：先让一家人安稳，自己晚一点再说",
        ),
        ("不是犹豫，是开始多想一步", "那是开始多想一步"),
        (
            "不是你有多厉害，而是你一直记得，背后还有人等着你把生活接稳",
            "心里会一直记得：父母、孩子和这个家，都还盼着日子稳一点",
        ),
        (
            "不是空喊一句“要坚强”，而是心里清楚：今天这份认真，正在变成家里可感的安稳",
            "心里清楚：今天这份认真，正在变成家里摸得着的安稳",
        ),
        ("不是不辛苦，是知道自己停不下来", "不容易是真的，只是心里知道自己还要把眼前的事理顺"),
        ("可真正成熟的承担，不是把自己彻底烧干。人也需要给自己留一盏灯。", "真正成熟的承担，是把日子往前托，也记得给自己留一点力气。"),
        ("不是把自己彻底烧干", "也记得给自己留一点力气"),
        (
            "责任不是把自己耗空，而是把日子稳稳托住",
            "责任到最后，是把日子稳稳托住，也把自己慢慢照顾回来",
        ),
        ("不是每一步都值得被夸大，但每一步都没有白走", "每一步都不必夸大，但每一步都没有白走"),
        ("不是为了证明自己多厉害，只是提醒自己：", "只是提醒自己："),
        (
            "成年人持续承受压力，意义常常不在“我做成了什么”，而在“我让谁安心了”。",
            "成年人持续承受压力，很多意义会落在一句很轻的安心里。",
        ),
        ("背后还有人等着你把生活接稳", "父母、孩子和这个家，都还盼着日子稳一点"),
        ("知道有人在爱你", "心里还有一处热乎的地方"),
        ("知道有人", "记得有人"),
    )
    for source, replacement in exact_replacements:
        cleaned = cleaned.replace(source, replacement)

    not_ab_pattern = re.compile(
        r"不是([^。！？!?；;\n]{1,24}?)[，,、]?\s*(?:而?是|只是)([^。！？!?；;\n]{1,80})",
        re.UNICODE,
    )

    def _rewrite_not_ab(match: re.Match[str]) -> str:
        left = match.group(1).strip(" ，,、：:")
        right = match.group(2).strip(" ，,、：:")
        if not right:
            return match.group(0)
        if "不在乎自己" in left:
            return f"也在乎自己，只是{right}"
        if "犹豫" in left:
            return f"那是{right}"
        if "把自己耗空" in left:
            return f"是{right}"
        if "证明" in left:
            return f"只是提醒自己：{right}"
        if "空喊" in left or "要坚强" in left:
            return right
        if "不辛苦" in left:
            return f"不容易是真的，只是{right}"
        if "有多厉害" in left and "记得" in right:
            return "心里会一直记得：父母、孩子和这个家，都还盼着日子稳一点"
        if right.startswith(("因为", "心里", "家里", "责任", "把", "让", "开始")):
            return f"是{right}"
        return match.group(0)

    cleaned = not_ab_pattern.sub(_rewrite_not_ab, cleaned)
    cleaned = cleaned.replace("责任最重的时候，往往心里会一直记得", "责任最重的时候，心里会一直记得")
    cleaned = cleaned.replace("责任最重的时候，往往心里一直记得", "责任最重的时候，心里会一直记得")
    cleaned = cleaned.replace("责任最重的时候，往往是心里会一直记得", "责任最重的时候，心里会一直记得")
    cleaned = cleaned.replace("真正让人认真往前走的，是心里清楚", "让人认真往前走的，是心里清楚")
    cleaned = cleaned.replace("“责任是把日子稳稳托住", "“责任到最后，是把日子稳稳托住")
    cleaned = cleaned.replace("“责任到最后，是把日子稳稳托住。”", "“责任到最后，是把日子稳稳托住，也把自己慢慢照顾回来。”")
    cleaned = re.sub(r"([。！？!?])\s*([。！？!?])+", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned

def _looks_like_responsibility_shelter_output(*, title: str, body_markdown: str, reference_source_markdown: str = "") -> bool:
    combined = re.sub(r"\s+", "", f"{title}\n{body_markdown}\n{reference_source_markdown}")
    if any(token in combined for token in ("肩上有责任", "家里排顺序", "把家稳住", "家里的事")) and any(
        token in combined
        for token in ("手机刚震", "手机一响", "身体会记账", "情绪硬吞", "身体先报警", "一个人先顶着")
    ):
        return True
    payload = {
        "source_type": "tracked_article",
        "article_title": title,
        "title": title,
        "body_markdown": body_markdown,
        "reference_article_body_markdown": reference_source_markdown,
        "summary": body_markdown[:500],
        "structure_notes": reference_source_markdown[:500],
        "tags": [],
    }
    return _has_everyday_warmth_responsibility_shelter_focus(payload) or _looks_like_local_responsibility_shelter_payload(payload)


def _sanitize_responsibility_shelter_output_text(value: str) -> str:
    cleaned = str(value or "")
    cleaned = re.sub(
        r"有时候还会心里的不容易",
        "有时候还会觉得心里一紧",
        cleaned,
    )
    cleaned = re.sub(
        r"觉得怎么总是自己在补位",
        "忍不住想：怎么总是自己在补位",
        cleaned,
    )
    cleaned = re.sub(
        r"责任集中落在一个人身上[^。！？!?]{0,140}(?:家庭分工|经济压力|长期习惯)[^。！？!?]{0,140}[。！？!?]",
        "父母的事要惦记，孩子的事要跟上，工作那头也不能松。",
        cleaned,
    )
    cleaned = re.sub(
        r"责任不断加码、家庭支持不足、生活成本上升、时间被工作和照护双向挤压，个人只是在结构缝隙里一个人先顶着[。！？!?]",
        "父母的事要惦记，孩子的事要跟上，工作那头也不能松。",
        cleaned,
    )
    cleaned = re.sub(
        r"把家庭支出、赡养压力、育儿成本、工作不稳定和情绪耗竭连起来看，说明不是某个人不够努力，而是很多责任被挤到同一个人身上[。！？!?]",
        "父母的事要惦记，孩子的事要跟上，工作那头也不能松，很多安排就挤到了一起。",
        cleaned,
    )
    cleaned = re.sub(
        r"责任外包给最能把事情接住的人、情绪不被允许松动、资源永远优先给别人，导致自我被不断后置，不容易变成长期状态[。！？!?]",
        "父母的事要惦记，孩子的事要跟上，工作那头也不能松，很多安排就挤到了一起。",
        cleaned,
    )
    cleaned = re.sub(
        r"成年人被同时拉扯在亲情、养育、收入和体面之间，很多人不是不想轻松，而是根本没有[“\"]停下来[”\"]的余地[。！？!?]",
        "父母的事要惦记，孩子的事要跟上，工作那头也不能松，很多安排就挤到了一起。",
        cleaned,
    )
    cleaned = re.sub(
        r"用[“\"]?[^。！？!?\n]{0,180}?切入，写出[^。！？!?\n]{0,180}(?:[。！？!?]|$)",
        "父母的事要惦记，孩子的事要跟上，工作那头也不能松，很多安排就挤到了一起。",
        cleaned,
    )
    cleaned = re.sub(
        r"当电话(?:的)?那头[^。！？!?\n]{0,180}[。！？!?]",
        "家里一有动静，你还没来得及细想，心里已经开始替家里排顺序。",
        cleaned,
    )
    cleaned = re.sub(
        r"这不是谁天生更能把事情接住，也不是谁比谁更懂事[。！？!?]更多时候，是因为心里有牵挂[。！？!?]",
        "这份多想一步，更多时候是因为心里有牵挂。",
        cleaned,
    )
    cleaned = re.sub(
        r"成年人最常见的成长，不在于变得多强，而在于变得更稳[。！？!?]",
        "人到了一定年纪，常见的成长，是慢慢把日子安排得更稳。",
        cleaned,
    )
    cleaned = re.sub(
        r"努力不一定总是为了证明什么，更常常是为了让身边的人少一点不安[。！？!?]",
        "努力常常会落在让身边的人少一点不安这件事上。",
        cleaned,
    )
    for source, replacement in sorted(
        _RESPONSIBILITY_SHELTER_OUTPUT_REPLACEMENTS,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        cleaned = cleaned.replace(source, replacement)
    cleaned = re.sub(
        r"电话的那头，是父母、孩子和[^。！？!?]{0,36}[。！？!?]电话这头，是[^。！？!?]{0,80}[。！？!?]",
        "家里一有事，父母、孩子、账单和当天的安排，都会先挤到心里。你把声音放稳，说：“我来处理。”",
        cleaned,
    )
    cleaned = re.sub(
        r"电话(?:的)?那头[，,]?\s*是?[^。！？!?\n]{0,120}?[，,]\s*电话(?:的)?这头[，,]?\s*是?[^。！？!?\n]{0,160}(?:[。！？!?]|$)",
        "家里一有事，父母、孩子、账单和当天的安排，都会先挤到心里。你把声音放稳，说：“我来处理。”",
        cleaned,
    )
    cleaned = re.sub(
        r"很多成年人到了某个阶段，想的第一件事不再是自己想要什么，而是家里先缺什么[。！？!?]",
        "很多成年人到了某个阶段，第一反应会先落到家里的安排上。",
        cleaned,
    )
    cleaned = re.sub(
        r"电话(?:的)?那头[，,]?\s*是?[^。！？!?\n]{0,90}[。！？!?]\s*电话(?:的)?这头[，,]?\s*是?[^。！？!?\n]{0,120}(?:[。！？!?]|[”\"]|$)?",
        "家里一有事，父母、孩子、账单和当天的安排，都会先挤到心里。你把声音放稳，说：“我来处理。”",
        cleaned,
    )
    cleaned = re.sub(
        r"不是自己想要什么，而是家里缺什么",
        "先想起家里还缺什么",
        cleaned,
    )
    cleaned = re.sub(
        r"生活就不再只是[“\"]?过得去[”\"]?，而是要把每一件事都放回它该去的位置",
        "生活就开始把每一件事都放回它该去的位置",
        cleaned,
    )
    cleaned = re.sub(
        r"这不是谁天生更能把事情接住，而是责任会把人往前推半步[。！？!?]",
        "责任会把人往前推半步。",
        cleaned,
    )
    cleaned = re.sub(
        r"最明显的变化不是人变得多厉害，而是心里装的人更多了[。！？!?]",
        "最明显的变化，是心里装的人更多了。",
        cleaned,
    )
    cleaned = re.sub(
        r"不是不想要，而是更愿意把有限的力气，先用在能让家里安稳的地方[。！？!?]",
        "也想要，只是更愿意把有限的力气，先用在能让家里安稳的地方。",
        cleaned,
    )
    cleaned = re.sub(
        r"成年人的(?P<kind>不容易|累)，(?:常常|很多时候)不是[^，,。！？!?]{1,40}，而是(?:因为)?一直在替家人(?:把日子稳住|稳住日子)[。！？!?]",
        lambda match: f"成年人的{match.group('kind')}，常常藏在那些替家人稳住日子的细节里。",
        cleaned,
    )
    cleaned = re.sub(
        r"成年人的辛苦，(?:常常|很多时候)不是为了证明自己，而是为了让身边的人更安心[。！？!?]",
        "成年人的辛苦，很多时候都落在让身边的人更安心这件事上。",
        cleaned,
    )
    cleaned = re.sub(
        r"真正拖垮人的不是某一件事，而是长期没有缓冲、没有退路、也没有被看见[。！？!?]",
        "真正让人不容易的，是很多事挤在一起，还要把家里的节奏稳住。",
        cleaned,
    )
    cleaned = re.sub(
        r"金句(?:[一二三四五六七八九十\d]+|有时候很简单|也许很朴素|是)?[:：]",
        "",
        cleaned,
    )
    cleaned = re.sub(r"还有一句更实在[:：]", "", cleaned)
    cleaned = re.sub(r"另一句(?:更实在)?是[:：]", "", cleaned)
    cleaned = re.sub(r"读到最后你会发现[，,]", "读到最后会明白，", cleaned)
    cleaned = re.sub(r"你会发现[，,]", "慢慢也就明白，", cleaned)
    cleaned = cleaned.replace("后来你会看见，", "后来再看，")
    cleaned = cleaned.replace("手机一响，你还没看清是谁，心里已经先把父母、孩子和这个月的安排过了一遍。", "家里一有事，父母、孩子和这个月的安排就会先排到心里。")
    cleaned = cleaned.replace("手机屏幕亮起的一刻，家里的事也跟着排到心里来。", "家里的事一冒出来，人就会先把眼前的顺序理清。")
    cleaned = cleaned.replace("手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。", "家里一有动静，你还没来得及细想，心里已经开始替家里排顺序。")
    cleaned = cleaned.replace("手机一响，很多人会先在心里把家里的事排个顺序。", "家里一有动静，很多人会先在心里把家里的事排个顺序。")
    cleaned = cleaned.replace("手机一响，人会先想到家里是不是又临时有事。", "家里一有动静，人会先想到是不是又要临时调顺序。")
    cleaned = cleaned.replace("手机一响，成年人第一反应不是自己，而是先在心里把家里的事排个顺序。", "家里一有动静，很多人会先在心里把家里的事排个顺序。")
    cleaned = cleaned.replace("它要讲的不是“吃苦有多光荣”，而是一个人长期接住生活压力时，真正支撑他的，往往是对家人的责任感，以及把日子慢慢托稳的能力。", "它把目光放在那些长期接住生活压力的人身上：对家人的责任感，常常会把日子慢慢托稳。")
    cleaned = cleaned.replace("手机一响，先想到的不是自己要不要接，而是家里是不是又临时有事。", "家里一有动静，人会先想到是不是又要临时调顺序。")
    cleaned = re.sub(
        r"手机(?:刚震(?:了一下)?|一响)[^。！？!?\n]{0,90}(?:父母|孩子|账单|家里|安排)[^。！？!?\n]{0,90}[。！？!?]",
        "家里一有事，心里会先把父母、孩子和眼下这段时间的安排过一遍。",
        cleaned,
    )
    cleaned = cleaned.replace("水杯刚端起来，手机又亮了。", "水杯刚端起来，下一件事又摆到眼前。")
    cleaned = re.sub(r"手机又亮了?[。！？!?]?", "下一件事又摆到眼前。", cleaned)
    cleaned = cleaned.replace("成年人最熟悉的不是轻松，而是随时要接住变化。", "日子过到后来，最熟悉的常常是随时接住变化。")
    cleaned = cleaned.replace("成年人为什么", "人到中年，为什么")
    cleaned = re.sub(
        r"(^|[。！？!?\n])成年人的(?P<kind>不容易|累|辛苦)",
        r"\1这份\g<kind>",
        cleaned,
    )
    cleaned = re.sub(r"(^|[。！？!?\n])成年人的", r"\1人到中年，", cleaned)
    cleaned = re.sub(r"([。！？!?])成年人", r"\1人到中年，", cleaned)
    cleaned = cleaned.replace(
        "你把成果藏进了寻常日子里。",
        "你做过的那些安排，都会藏进后来更稳的寻常日子里。",
    )
    cleaned = re.sub(
        r"真正沉重的，是[“\"]我不能让他们因为我而更难[”\"]",
        "心里最重的，是那句“我想让他们轻松一点”。",
        cleaned,
    )
    cleaned = re.sub(
        r"真正撑起一家人的，不是轰轰烈烈的证明，而是日复一日的安排[。！？!?]",
        "真正撑起一家人的，常常就是日复一日的安排。",
        cleaned,
    )
    cleaned = re.sub(
        r"真正让人继续往前走的，也不是外人的认可，而是你知道，自己没有白忙[。！？!?]",
        "真正让人继续往前走的，是你知道自己没有白忙。",
        cleaned,
    )
    cleaned = re.sub(
        r"肩上的责任并不只是在消耗你，它也在悄悄回报你",
        "肩上的责任也会在日子里慢慢回报你",
        cleaned,
    )
    cleaned = re.sub(
        r"不是为了照给谁看，是为了你在忙完一圈之后，还能认得回家的路，也认得自己[。！？!?]",
        "是为了你在忙完一圈之后，还能认得回家的路，也认得自己。",
        cleaned,
    )
    cleaned = cleaned.replace("这很多责任常常", "很多责任常常")
    cleaned = cleaned.replace("先把今天撑住", "先把今天稳住")
    cleaned = cleaned.replace("把今天撑住", "把今天稳住")
    cleaned = cleaned.replace("撑住一家人的人", "把家放在心上的人")
    cleaned = cleaned.replace("电话这头的人，常常不是不累，而是还要把顺序理清。", "电话这头的人也会累，只是还要先把顺序理清。")
    cleaned = cleaned.replace("很多成年人的第一反应，不是先问自己想要什么，而是先想家里缺什么。", "很多成年人的第一反应，是先想家里还缺什么。")
    cleaned = cleaned.replace("很多成年人先想到的，先想起家里还缺什么。", "很多成年人第一反应，是先想起家里还缺什么。")
    cleaned = cleaned.replace("很多成年人先想到的，先想起家里还缺什么", "很多成年人第一反应，是先想起家里还缺什么")
    cleaned = cleaned.replace("不是他们天生更能把事情接住，而是责任一落下来，人就会自然地多想一步，把眼前的日子先理顺。", "责任一落下来，人就会自然地多想一步，把眼前的日子先理顺。")
    cleaned = cleaned.replace("责任真正改变一个人的地方，不是让他变得多强，而是让他变得更稳。", "责任真正改变一个人的地方，是让人慢慢变得更稳。")
    cleaned = cleaned.replace("以前觉得差不多就行的事，后来会提前确认；", "以前觉得差不多就行的事，后来会提前确认。")
    cleaned = cleaned.replace("不是因为心变硬了，是因为知道，", "心并没有变硬，只是知道，")
    cleaned = cleaned.replace("很多时候，努力不是为了证明自己，而是为了让家里少一点悬着的心。", "这份努力慢慢落在让家里少一点悬着的心这件事上。")
    cleaned = cleaned.replace("努力不是为了证明自己，而是为了让家里少一点悬着的心。", "这份努力慢慢落在让家里少一点悬着的心这件事上。")
    cleaned = cleaned.replace("真正认真走着中年人继续往前走的，", "真正让中年人继续往前走的，")
    cleaned = cleaned.replace("认真走着中年人继续往前走的，", "支撑中年人继续往前走的，")
    cleaned = cleaned.replace("认真走着中年人继续往前的，", "支撑中年人继续往前的，")
    cleaned = cleaned.replace("真正认真走着自己的，", "真正支撑中年人的，")
    cleaned = cleaned.replace("真正认真走着自己的", "真正支撑中年人的")
    cleaned = cleaned.replace("你先忙” 这边", "你先忙”，这边")
    cleaned = cleaned.replace("电话一响 手先去翻日历", "电话一响，手先去翻日历")
    cleaned = cleaned.replace("家里安稳了 累留在了你身上", "家里安稳了，累留在了你身上")
    cleaned = cleaned.replace("不是矫情，也不只是忍耐", "那一下说不上矫情，只是肩上有人要顾")
    cleaned = cleaned.replace("可不只是辛苦从哪来，更是为什么", "更让人撑住的，是为什么")
    cleaned = cleaned.replace("奔波不一定值得被歌颂", "奔波不必被夸大")
    cleaned = cleaned.replace("辛苦未必需要被歌颂", "辛苦不必被夸大")
    cleaned = cleaned.replace("最怕的不是忙，而是心里只剩下忙。", "最怕的，是心里只剩下忙。")
    cleaned = cleaned.replace("我不是在白撑，我是在把一家人的生活慢慢稳住。", "我没有白忙，我正在把一家人的生活慢慢稳住。")
    cleaned = cleaned.replace("真正托住一家人的，不是豪言壮语，是那些一次次没有缺席的回应。", "真正托住一家人的，是那些一次次没有缺席的回应。")
    cleaned = cleaned.replace("真正的责任，是让家人在你的稳里，慢慢过上稳的日子。", "真正的责任，是让家人在你的安排里，慢慢过上更踏实的日子。")
    cleaned = cleaned.replace("家人少受的一点惊", "家人少一点慌张")
    cleaned = cleaned.replace("我没有白撑", "我没有白忙")
    cleaned = cleaned.replace("没有白撑", "没有白忙")
    cleaned = cleaned.replace("这篇想写的，就是", "真正落在日子里的，是")
    cleaned = cleaned.replace("这篇想写的，不只是", "真正落在日子里的，不只是")
    cleaned = cleaned.replace("这篇想写的，是", "")
    cleaned = cleaned.replace("这篇文章想写的，是", "")
    cleaned = cleaned.replace("真正想说的，是", "")
    cleaned = cleaned.replace("更想说的是", "")
    cleaned = cleaned.replace("也想认真说一句：", "")
    cleaned = cleaned.replace("也想认真说一句:", "")
    cleaned = cleaned.replace("这篇文章要写清楚的，是", "更要紧的，是")
    cleaned = re.sub(r"这篇写给[^。！？!?]{0,40}[。！？!?]?", "", cleaned)
    cleaned = cleaned.replace(
        "路还长，但你不是白走。你是在用自己的方式，把日子往能住下去的方向，慢慢推过去。",
        "路还长，但这一路不是白走。你正用自己的方式，把日子往能住下去的方向慢慢推过去。",
    )
    cleaned = _strip_responsibility_shelter_instruction_leakage(cleaned)
    cleaned = _soften_responsibility_shelter_not_ab_residue(cleaned)
    cleaned = re.sub(r"(^|\n)\s*金句[:：]\s*", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"([。！？!?])\s*([。！？!?])+", r"\1", cleaned)
    return cleaned.strip() if str(value or "").strip() == str(value or "") else cleaned


def _should_prefer_short_responsibility_scene_title(candidate: str, short_title: str) -> bool:
    normalized_candidate = _strip_responsibility_title_label(candidate)
    normalized_short = _strip_responsibility_title_label(short_title)
    if not normalized_candidate or not normalized_short or normalized_candidate == normalized_short:
        return False
    generic_tail = normalized_candidate.endswith(("的人", "那个人", "这个人", "那一下", "这一刻"))
    if not generic_tail and len(normalized_candidate) <= len(normalized_short) + 2:
        return False
    if _looks_like_explanatory_responsibility_shelter_title(normalized_short):
        return False
    marker_groups: tuple[tuple[str, ...], ...] = (
        ("电话", "日历"),
        ("手机", "日历"),
        ("电话", "顺序"),
        ("电话", "安排"),
        ("电话", "重排"),
        ("家里", "顺序"),
        ("复查", "日历"),
        ("医院", "日历"),
        ("先翻日历",),
    )
    if any(all(token in normalized_candidate and token in normalized_short for token in group) for group in marker_groups):
        return True
    shared_markers = [
        token
        for token in ("电话", "手机", "日历", "顺序", "安排", "家里", "复查", "医院", "请假")
        if token in normalized_candidate and token in normalized_short
    ]
    return len(shared_markers) >= 2 and len(normalized_short) <= 12


def _normalize_responsibility_shelter_draft_title(
    *,
    title: str,
    body_markdown: str,
    topic_title: str = "",
    project_title: str = "",
    reference_source_markdown: str = "",
) -> str:
    cleaned = _strip_responsibility_title_label(title)
    if not _looks_like_responsibility_shelter_output(
        title=cleaned or topic_title or project_title,
        body_markdown=body_markdown,
        reference_source_markdown=reference_source_markdown,
    ):
        return cleaned
    if not cleaned:
        normalized_topic_title = _strip_responsibility_title_label(topic_title)
        if normalized_topic_title:
            return normalized_topic_title
        normalized_project_title = _strip_responsibility_title_label(project_title)
        if normalized_project_title:
            return normalized_project_title
        probe = _build_local_responsibility_probe(
            title=normalized_topic_title or normalized_project_title or cleaned,
            body_markdown=body_markdown,
            reference_source_markdown=reference_source_markdown,
        )
        return _resolve_local_responsibility_packaging_title(probe)
    normalized_topic_title = _strip_responsibility_title_label(topic_title)
    if _should_prefer_short_responsibility_scene_title(cleaned, normalized_topic_title):
        return normalized_topic_title
    normalized_project_title = _strip_responsibility_title_label(project_title)
    if _should_prefer_short_responsibility_scene_title(cleaned, normalized_project_title):
        return normalized_project_title
    if not _looks_like_explanatory_responsibility_shelter_title(cleaned):
        return cleaned
    if normalized_topic_title and not _looks_like_explanatory_responsibility_shelter_title(normalized_topic_title):
        if any(token in cleaned for token in ("谁去医院", "谁接孩子", "晚饭怎么办", "先想的是谁去医院", "先想的是谁接孩子")):
            return normalized_topic_title
        return normalized_topic_title
    if normalized_project_title and not _looks_like_explanatory_responsibility_shelter_title(normalized_project_title):
        if any(token in cleaned for token in ("谁去医院", "谁接孩子", "晚饭怎么办", "先想的是谁去医院", "先想的是谁接孩子")):
            return normalized_project_title
        return normalized_project_title
    probe = _build_local_responsibility_probe(
        title=normalized_topic_title or normalized_project_title or cleaned,
        body_markdown=body_markdown,
        reference_source_markdown=reference_source_markdown,
    )
    return _resolve_local_responsibility_packaging_title(probe)


def _split_responsibility_shelter_output_paragraphs(markdown: str) -> str:
    blocks = _split_markdown_blocks(markdown)
    if not blocks:
        return markdown

    rebuilt_blocks: list[str] = []
    changed = False
    for block in blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if _looks_like_structure_heading(normalized) or normalized.lstrip().startswith("#"):
            rebuilt_blocks.append(normalized)
            continue

        sentences = _split_block_sentences(normalized)
        compact_len = len(re.sub(r"\s+", "", normalized))
        should_split = (len(sentences) >= 4 and compact_len >= 90) or (
            len(sentences) >= 3 and compact_len >= 160
        )
        if not should_split:
            rebuilt_blocks.append(normalized)
            continue

        chunks: list[str] = []
        cursor = 0
        while cursor < len(sentences):
            chunk = "".join(sentences[cursor : cursor + 2]).strip()
            if chunk:
                chunks.append(chunk)
            cursor += 2
        if len(chunks) <= 1:
            rebuilt_blocks.append(normalized)
            continue
        changed = True
        rebuilt_blocks.extend(chunks)

    if not changed:
        return markdown
    return "\n\n".join(rebuilt_blocks)


def _sanitize_responsibility_shelter_result_fields(
    *,
    ai_result: Mapping[str, object],
    title: str,
    body_markdown: str,
    reference_source_markdown: str = "",
    text_fields: tuple[str, ...] = (),
    list_fields: tuple[str, ...] = (),
) -> dict[str, object]:
    if not _looks_like_responsibility_shelter_output(
        title=title,
        body_markdown=body_markdown,
        reference_source_markdown=reference_source_markdown,
    ):
        return dict(ai_result)
    cleaned = dict(ai_result)
    probe = _build_local_responsibility_probe(
        title=title,
        body_markdown=body_markdown,
        reference_source_markdown=reference_source_markdown,
    )
    normalized_reference_title = _strip_responsibility_title_label(title)

    def _normalize_responsibility_title_candidate(value: str) -> str:
        candidate = _strip_responsibility_title_label(
            _soften_generic_packaging_opener_text(
                _sanitize_responsibility_shelter_output_text(value)
            )
        )
        candidate = candidate.replace("电话一响，我先翻日历", "电话一响，你先翻日历")
        candidate = candidate.replace("电话一响，他先翻日历", "电话一响，你先翻日历")
        candidate = candidate.replace("电话一响，她先翻日历", "电话一响，你先翻日历")
        candidate = candidate.replace("电话一响，先翻日历", "电话一响，你先翻日历")
        candidate = candidate.replace("我先翻日历", "你先翻日历")
        if not candidate:
            return candidate
        if _should_prefer_short_responsibility_scene_title(candidate, normalized_reference_title):
            return normalized_reference_title
        if any(
            token in candidate
            for token in (
                "家里一有事，总是你先把顺序理出来",
                "家里一有事，你总会先把家稳住",
                "家里一有事，你总先把顺序理出来",
                "别再先把事情接住",
                "先把事情接住",
                "定心骨",
                "定盘星",
            )
        ) or _looks_like_explanatory_responsibility_shelter_title(candidate):
            return _resolve_local_responsibility_scene_title(probe)
        return candidate

    for field in text_fields:
        if field in cleaned:
            field_value = str(cleaned.get(field) or "")
            if "title" in field:
                cleaned[field] = _normalize_responsibility_title_candidate(field_value)
            else:
                cleaned[field] = _soften_generic_packaging_opener_text(
                    _sanitize_responsibility_shelter_output_text(field_value)
                )
    for field in list_fields:
        value = cleaned.get(field)
        if isinstance(value, list):
            if "title" in field:
                cleaned[field] = [
                    _normalize_responsibility_title_candidate(str(item or ""))
                    for item in value
                ]
            else:
                cleaned[field] = [
                    _soften_generic_packaging_opener_text(_sanitize_responsibility_shelter_output_text(str(item or "")))
                    for item in value
                ]
    return cleaned


def _apply_final_tracked_article_guard(
    *,
    title: str,
    body_markdown: str,
    source_type: str,
    reference_source_markdown: str = "",
) -> str:
    if source_type != "tracked_article":
        return body_markdown

    current_body, _ = _apply_initial_draft_candidate_cleanups(
        title=title,
        body_markdown=body_markdown,
        source_type=source_type,
        reference_source_markdown=reference_source_markdown,
    )
    current_body = _repair_tracked_article_fragment_residue(title=title, body_markdown=current_body)
    return current_body


def _repair_self_reliance_expression_sink_residue(*, title: str, body_markdown: str) -> str:
    if _resolve_tracked_article_candidate_mode(title=title, markdown=body_markdown) != "self_reliance_inward_support":
        return body_markdown

    cleaned = body_markdown
    replacements = (
        ("连借一只手都要排队", "先把能做的一步摆到眼前"),
        ("谁都没法分神来接你一下", "眼前能做的事先摆到面前"),
        ("身边的人也都在赶自己的事", "你先把眼前最急的一件事摆好"),
        ("身边的人也都在赶自己的生活", "你先把眼前最急的一件事摆好"),
        ("事情一乱，先把顺序理出来", "先别慌，先把自己站稳"),
        ("电话打出去一圈，没人能马上分神的时候，最先冒出来的往往慌", "事情一下撞到眼前、顺序还没排出来的时候，最先冒出来的往往是慌"),
        ("消息还在往前推", "手头的事还在往前推"),
        ("“我快撑不住了”咽回去", "“我得先缓一下”先压住"),
        ("说出口也未必有人接得住", "事情还是要先一件件落回手上"),
        ("话被压回去以后", "那阵慌乱先被按住以后"),
        ("回你的速度慢一点，语气也短一点", "眼前可用的余力也少一点"),
        ("等别人来接", "把顺序理清"),
        ("等回音", "把顺序理清"),
        ("等消息", "把顺序理清"),
        ("等一个刚好有空的人", "把顺序理清"),
        ("什么时候轮到我", "什么时候眼前这阵乱能先过去"),
        ("该回的消息记在纸上，明天再回", "要紧的事先记下来，明天按顺序处理"),
        ("实在撑不住，就先睡一觉", "实在乱得不行，就先睡一觉"),
        ("那只手，多半赶不上", "眼前这一步，可以先接住"),
        ("等外面那只手终于腾出空", "把顺序理清终于慢下来"),
        ("第一步往往很小", "先把眼前这一小截接住"),
        ("方法也不复杂", "先别把自己逼得太满"),
        ("你能做的，是", "人能先做的，常常只是"),
        (
            "这随叫随到的。先说成逞强，倒更像止损。成年人的依靠，本来就不，反而太轻了。",
            "这不叫逞强，更像先把脚下站稳。成年人的成熟，不是所有事都一个人扛，而是先理清眼前，再分清哪些能做、哪些该交出去。",
        ),
        ("今晚借不到人，就先借流程", "今晚先把顺序借回来，把眼前这一件事放稳"),
    )
    for source_text, target_text in replacements:
        cleaned = cleaned.replace(source_text, target_text)

    cleaned = re.sub(r"([。！？!?])\s*([。！？!?])+", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned if cleaned != body_markdown else body_markdown


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
        normalized = re.sub(r"([”\"'’])\s*[。！？!?]+$", r"\1", normalized)
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
    normalized_only_change = cleaned_markdown != body_markdown and len(collapsed_blocks) == len(body_blocks)
    cleaned_quotes = extract_isolated_quote_paragraphs(cleaned_markdown)
    if len(cleaned_quotes) > len(original_quotes):
        return body_markdown

    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=cleaned_markdown)
    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    if cleaned_summary.score > original_summary.score:
        return body_markdown
    if cleaned_summary.score == original_summary.score and len(collapsed_blocks) >= len(body_blocks) and not normalized_only_change:
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
        for connector in ("其实", "所以", "因此", "然后", "换句话说", "也就是说"):
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
    return _has_tracked_article_shell_retry_signal(
        source_markdown=source_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_markdown,
    )


def _has_tracked_article_shell_retry_signal(
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

    residual_orphaned_rebound_tails = _format_retry_examples(
        extract_orphaned_rebound_tails(candidate_markdown),
        max_items=4,
        max_length=26,
    )
    if residual_orphaned_rebound_tails:
        retry_notes.append(f"这些断裂的回钩残句必须整句删掉，不要换词续写：{' / '.join(residual_orphaned_rebound_tails)}。")

    residual_truncated_fragments = _format_retry_examples(
        extract_truncated_fragment_paragraphs(candidate_markdown),
        max_items=4,
        max_length=28,
    )
    if residual_truncated_fragments:
        retry_notes.append(f"这些没说完的半句和断尾必须直接修完整或删掉：{' / '.join(residual_truncated_fragments)}。")

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

    residual_yi_cadence = _format_retry_examples(
        _extract_clause_leading_yi_phrases(candidate_markdown),
        max_items=6,
        max_length=8,
    )
    if residual_yi_cadence:
        retry_notes.append(
            f"这些一字量词起手要至少减掉一半：{' / '.join(residual_yi_cadence)}。"
            "能直接写是谁先回了谁、拖到了几点、哪条消息还挂着、哪次动作慢了半拍，就不要再用“一个 / 一下 / 一点 / 一些”撑节奏。"
        )

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
    if _has_unbalanced_quote_fusion_signal(candidate_markdown):
        retry_notes.append("把引号没收住、半截话和两个例子黏在一起的句子直接修完整；缺少收口的对话要补回正常句法，不要让一句话突然拐进另一个例子。")

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

    residual_orphaned_rebound_tails = _format_retry_examples(
        extract_orphaned_rebound_tails(candidate_markdown),
        max_items=4,
        max_length=26,
    )
    if residual_orphaned_rebound_tails:
        retry_notes.append(f"把这些断裂回钩残句整句删掉，不要补成近义解释：{' / '.join(residual_orphaned_rebound_tails)}。")

    residual_truncated_fragments = _format_retry_examples(
        extract_truncated_fragment_paragraphs(candidate_markdown),
        max_items=4,
        max_length=28,
    )
    if residual_truncated_fragments:
        retry_notes.append(f"把这些明显没说完的半句修完整，不要保留双标点和断尾：{' / '.join(residual_truncated_fragments)}。")

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

    residual_yi_cadence = _format_retry_examples(
        _extract_clause_leading_yi_phrases(candidate_markdown),
        max_items=6,
        max_length=8,
    )
    if residual_yi_cadence:
        retry_notes.append(
            f"把这些还在拿一字量词起手的句子改掉：{' / '.join(residual_yi_cadence)}。"
            "优先换成具体动作、物件、时间点或顺序差，不要继续用“一个 / 一下 / 一点 / 一些”敲节拍。"
        )

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


_TRACKED_ARTICLE_GENERIC_OPENING_SHELL_PHRASES = (
    "灯还亮着",
    "饭热过一遍又一遍",
    "饭热了又凉",
    "人已经困了",
    "心还在值班",
    "心没下班",
    "消息还能回",
    "班还能上",
    "身体先开始交代",
    "外面看不出异样",
    "手机一亮先紧一下",
)
_TRACKED_ARTICLE_GENERIC_OPENING_OBJECT_TOKENS = (
    "灯",
    "饭",
    "水杯",
    "房间",
    "阳台",
)
_TRACKED_ARTICLE_SELECTION_SUPPORTED_MODES = {
    "inner_settlement",
    "self_reliance_inward_support",
    "self_worth_rebuild",
    "response_priority",
    "trust_boundary",
    "supportive_appreciation",
    "everyday_warmth_return",
    "relationship_aftercare",
    "resilience_reconstruction",
    "scene_first_progression",
    "emotional_engine_direct",
    "pressure_interface_direct",
}
_TRACKED_ARTICLE_THEME_COLLAPSE_RISK_MODES: dict[str, set[str]] = {
    "response_priority": {"inner_settlement", "internal_pressure", "relationship_aftercare", "trust_boundary"},
    "trust_boundary": {"inner_settlement", "internal_pressure", "relationship_aftercare", "response_priority", "emotional_engine_direct"},
    "supportive_appreciation": {"inner_settlement", "internal_pressure", "relationship_aftercare"},
    "everyday_warmth_return": {
        "inner_settlement",
        "internal_pressure",
        "relationship_aftercare",
        "response_priority",
    },
    "relationship_aftercare": {"inner_settlement", "internal_pressure", "response_priority"},
    "resilience_reconstruction": {
        "inner_settlement",
        "internal_pressure",
        "supportive_appreciation",
        "everyday_warmth_return",
    },
    "self_reliance_inward_support": {
        "inner_settlement",
        "internal_pressure",
        "relationship_aftercare",
        "response_priority",
    },
    "self_worth_rebuild": {
        "inner_settlement",
        "internal_pressure",
        "response_priority",
        "supportive_appreciation",
        "relationship_aftercare",
        "emotional_engine_direct",
    },
    "emotional_engine_direct": {"inner_settlement", "internal_pressure", "response_priority"},
    "scene_first_progression": {"inner_settlement", "internal_pressure", "relationship_aftercare"},
}


def _resolve_tracked_article_expected_selection_mode(selection_context: Mapping[str, object] | None) -> str:
    if not isinstance(selection_context, Mapping):
        return ""
    if _has_local_trust_boundary_focus(selection_context):
        return "trust_boundary"
    selection_title = str(
        selection_context.get("topic_title")
        or selection_context.get("article_title")
        or selection_context.get("project_title")
        or ""
    ).strip()
    selection_body = str(selection_context.get("body_markdown") or "").strip()
    strategy_card = selection_context.get("strategy_card")
    if _has_everyday_warmth_responsibility_shelter_focus(selection_context) or _looks_like_local_responsibility_shelter_payload(
        selection_context
    ):
        return "responsibility_shelter"
    if isinstance(strategy_card, Mapping):
        strategy_mode = str(strategy_card.get("structure_mode") or "").strip()
        if strategy_mode == "internal_pressure":
            return "pressure_interface_direct"
        if strategy_mode in _TRACKED_ARTICLE_SELECTION_SUPPORTED_MODES:
            return strategy_mode
    analysis_mode = str(selection_context.get("analysis_structure_mode") or "").strip()
    if analysis_mode == "internal_pressure":
        return "pressure_interface_direct"
    if analysis_mode in _TRACKED_ARTICLE_SELECTION_SUPPORTED_MODES:
        return analysis_mode
    reference_mode = str(selection_context.get("reference_article_analysis_structure_mode") or "").strip()
    if reference_mode == "internal_pressure":
        return "pressure_interface_direct"
    if reference_mode in _TRACKED_ARTICLE_SELECTION_SUPPORTED_MODES:
        return reference_mode
    if _payload_looks_like_scene_first_progression(selection_context):
        return "scene_first_progression"
    if _has_resilience_reconstruction_focus(selection_context):
        return "resilience_reconstruction"
    if _has_everyday_warmth_return_focus(selection_context):
        return "everyday_warmth_return"
    if _uses_local_emotional_forgiveness_release_variant(selection_context):
        return "emotional_engine_direct"
    strong_supportive_title = any(
        token in selection_title for token in ("心软的人", "别人感受放在前面", "最该被人好好珍惜", "值得被认真珍惜")
    )
    supportive_scene_text = f"{selection_title}\n{selection_body}"
    if strong_supportive_title and any(
        token in supportive_scene_text
        for token in ("原谅", "包容", "体谅", "把语气放轻", "把语气放软", "留余地", "好好接住", "好好珍惜")
    ):
        return "supportive_appreciation"
    if _has_self_worth_rebuild_focus(selection_context):
        return "self_worth_rebuild"
    if _has_response_priority_focus(selection_context):
        return "response_priority"
    if _has_supportive_appreciation_focus(selection_context):
        return "supportive_appreciation"
    if _has_relationship_aftercare_focus(selection_context):
        return "relationship_aftercare"
    if _has_inner_settlement_focus(selection_context):
        return "inner_settlement"
    if _has_self_reliance_inward_support_focus(selection_context):
        return "self_reliance_inward_support"
    if _has_broad_emotional_release_focus(selection_context):
        return "emotional_engine_direct"
    return ""


def _looks_like_everyday_warmth_candidate(*, title: str, markdown: str) -> bool:
    text = f"{title}\n{markdown}"
    if any(token in text for token in ("没时间", "回消息", "吵架", "冷暴力", "信任", "出轨", "边界", "自救", "残奥", "手术")):
        return False
    daily_hits = sum(
        1
        for token in (
            "家人",
            "家里人",
            "知己",
            "老友",
            "饭桌",
            "饭香",
            "回家",
            "平安",
            "日子",
            "人间有味是清欢",
        )
        if token in text
    )
    achievement_hits = sum(
        1
        for token in ("比较", "账户数字", "房子", "朋友圈", "追得那么急", "幸福从高处请回了日常")
        if token in text
    )
    return daily_hits >= 4 and (achievement_hits >= 1 or "有家人有知己" in title or "知己还在" in text)

def _resolve_tracked_article_candidate_mode(*, title: str, markdown: str) -> str:
    payload = {
        "source_type": "tracked_article",
        "article_title": title,
        "body_markdown": markdown,
    }
    scene_text = f"{title}\n{markdown}"
    if _looks_like_local_responsibility_shelter_payload(payload):
        return "responsibility_shelter"
    if any(token in f"{title}\n{markdown}" for token in ("手术台", "泳池", "11下", "复健", "不被定义", "残奥")):
        return "resilience_reconstruction"
    if _has_resilience_reconstruction_focus(payload):
        return "resilience_reconstruction"
    if _looks_like_everyday_warmth_candidate(title=title, markdown=markdown):
        return "everyday_warmth_return"
    if _has_everyday_warmth_return_focus(payload):
        return "everyday_warmth_return"
    strong_supportive_title = any(
        token in title for token in ("心软的人", "别人感受放在前面", "最该被人好好珍惜", "值得被认真珍惜")
    )
    supportive_scene_text = f"{title}\n{markdown}"
    if strong_supportive_title and any(
        token in supportive_scene_text
        for token in ("原谅", "包容", "体谅", "把语气放轻", "把语气放软", "留余地", "好好接住", "好好珍惜")
    ):
        return "supportive_appreciation"
    if _has_self_worth_rebuild_focus(payload):
        return "self_worth_rebuild"
    if any(
        token in scene_text
        for token in ("信任", "谎言", "隐瞒", "坦诚", "说到做到", "赤诚", "裂了一道缝")
    ):
        return "trust_boundary"
    if _has_local_trust_boundary_focus(payload):
        return "trust_boundary"
    if _has_response_priority_focus(payload):
        return "response_priority"
    if _has_supportive_appreciation_focus(payload):
        return "supportive_appreciation"
    if _has_relationship_aftercare_focus(payload):
        return "relationship_aftercare"
    inner_settlement_text = f"{title}\n{markdown}"
    if any(
        token in inner_settlement_text
        for token in (
            "心安",
            "把心放回今天",
            "日子才会慢慢安稳",
            "内心安顿",
            "内在归处",
            "与内心和解",
            "心放平",
            "心若不安",
            "心若不定",
            "此心安处",
        )
    ):
        return "inner_settlement"
    if _has_inner_settlement_focus(payload):
        return "inner_settlement"
    if _has_self_reliance_inward_support_focus(payload):
        return "self_reliance_inward_support"
    if _looks_like_scene_first_progression_candidate(markdown):
        return "scene_first_progression"
    if _has_broad_emotional_release_focus(payload):
        return "emotional_engine_direct"
    return ""


def _tracked_article_opening_shell_burden(markdown: str) -> tuple[int, int, int]:
    opening_text = "\n".join(_extract_non_heading_paragraphs(markdown)[:3])
    phrase_hits = sum(1 for phrase in _TRACKED_ARTICLE_GENERIC_OPENING_SHELL_PHRASES if phrase in opening_text)
    object_hits = sum(1 for token in _TRACKED_ARTICLE_GENERIC_OPENING_OBJECT_TOKENS if token in opening_text)
    burden = phrase_hits + max(0, object_hits - 1)
    return burden, phrase_hits, object_hits


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
    selection_context: Mapping[str, object] | None = None,
) -> bool:
    def _short_paragraph_count(markdown: str) -> int:
        return sum(
            1
            for paragraph in _extract_non_heading_paragraphs(markdown)
            if len(re.sub(r"\s+", "", paragraph)) <= 45
        )

    def _hard_template_burden(markdown: str) -> tuple[int, int, int, int, int, int, int]:
        quote_paragraphs = max(0, len(extract_isolated_quote_paragraphs(markdown)) - 1)
        explanatory_paragraphs = max(0, len(extract_explanatory_bridge_paragraphs(markdown)) - 1)
        return (
            len(extract_not_ab_skeletons(markdown)),
            len(extract_generic_reflective_openers(markdown)),
            len(extract_growth_cliches(markdown)),
            len(extract_orphaned_rebound_tails(markdown)),
            len(extract_embedded_banner_paragraphs(markdown)),
            quote_paragraphs,
            explanatory_paragraphs,
        )

    def _has_only_minor_ai_flavor_residue(*, title: str, markdown: str) -> bool:
        summary = evaluate_ai_flavor_risk(title=title, body_markdown=markdown)
        if summary.score > 22:
            return False
        if _hard_template_burden(markdown) != (0, 0, 0, 0, 0, 0, 0):
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
            and len(extract_orphaned_rebound_tails(markdown)) == 0
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

    def _residual_burden(markdown: str) -> tuple[int, int, int, int, int, int, int, int, int, int]:
        not_ab = len(extract_not_ab_skeletons(markdown))
        openers = len(extract_generic_reflective_openers(markdown))
        cliches = len(extract_growth_cliches(markdown))
        orphaned_rebound_tails = len(extract_orphaned_rebound_tails(markdown))
        short_judgments = len(extract_short_judgment_paragraphs(markdown))
        cadence_pairs = count_short_long_cadence_pairs(markdown)
        embedded_banners = len(extract_embedded_banner_paragraphs(markdown))
        quote_paragraphs = max(0, len(extract_isolated_quote_paragraphs(markdown)) - 1)
        explanatory_paragraphs = max(0, len(extract_explanatory_bridge_paragraphs(markdown)) - 1)
        return (
            not_ab
            + openers
            + cliches
            + orphaned_rebound_tails
            + short_judgments
            + cadence_pairs
            + embedded_banners
            + quote_paragraphs
            + explanatory_paragraphs,
            embedded_banners,
            orphaned_rebound_tails,
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
    current_orphaned_rebound_tails = len(extract_orphaned_rebound_tails(current_markdown))
    retried_orphaned_rebound_tails = len(extract_orphaned_rebound_tails(retried_markdown))
    current_truncated_fragments = len(extract_truncated_fragment_paragraphs(current_markdown))
    retried_truncated_fragments = len(extract_truncated_fragment_paragraphs(retried_markdown))
    tracked_article_mode = source_type == "tracked_article"
    current_structure_headings = _extract_structure_headings(current_markdown)
    if len(current_structure_headings) >= 2 and _find_missing_structure_headings(
        source_markdown=current_markdown,
        candidate_markdown=retried_markdown,
    ):
        return False
    current_quote_fusion_signal = _has_unbalanced_quote_fusion_signal(current_markdown)
    retried_quote_fusion_signal = _has_unbalanced_quote_fusion_signal(retried_markdown)
    if current_quote_fusion_signal != retried_quote_fusion_signal:
        return not retried_quote_fusion_signal
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
    if current_orphaned_rebound_tails != retried_orphaned_rebound_tails:
        return retried_orphaned_rebound_tails < current_orphaned_rebound_tails
    if current_truncated_fragments != retried_truncated_fragments:
        return retried_truncated_fragments < current_truncated_fragments
    if current_over_smoothed != retried_over_smoothed:
        return not retried_over_smoothed
    if tracked_article_mode:
        expected_mode = _resolve_tracked_article_expected_selection_mode(selection_context)
        current_mode = _resolve_tracked_article_candidate_mode(title=current_title, markdown=current_markdown)
        retried_mode = _resolve_tracked_article_candidate_mode(title=retried_title, markdown=retried_markdown)
        if expected_mode:
            if expected_mode == "inner_settlement":
                current_result_dependence = _is_inner_settlement_result_dependence_theme(
                    title=current_title,
                    markdown=current_markdown,
                )
                retried_result_dependence = _is_inner_settlement_result_dependence_theme(
                    title=retried_title,
                    markdown=retried_markdown,
                )
                if current_result_dependence != retried_result_dependence:
                    return not retried_result_dependence
            current_matches_expected = current_mode == expected_mode
            retried_matches_expected = retried_mode == expected_mode
            if current_matches_expected != retried_matches_expected:
                return retried_matches_expected
            collapse_risk_modes = _TRACKED_ARTICLE_THEME_COLLAPSE_RISK_MODES.get(expected_mode, set())
            current_theme_collapsed = current_mode in collapse_risk_modes
            retried_theme_collapsed = retried_mode in collapse_risk_modes
            if current_theme_collapsed != retried_theme_collapsed:
                return not retried_theme_collapsed
        current_opening_shell = _tracked_article_opening_shell_burden(current_markdown)
        retried_opening_shell = _tracked_article_opening_shell_burden(retried_markdown)
        if current_opening_shell != retried_opening_shell and current_opening_shell[0] >= 3:
            return retried_opening_shell < current_opening_shell
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
    selection_context: Mapping[str, object] | None = None,
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
        selection_context=selection_context,
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
        _build_nested_draft_retry_payload(
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
            },
            generator=generator,
        )
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

    candidate_selection_context = _build_draft_candidate_selection_context(
        project=project,
        reference_source_markdown=_get_project_reference_source_markdown(project),
        reference_article_payload=reference_article_payload,
        strategy_bundle_payload=strategy_bundle_payload,
    )
    excessive_openers = _find_excessive_generic_reflective_openers(
        source_markdown=source_draft_body_markdown,
        candidate_markdown=candidate_body_markdown,
    )
    if not excessive_openers:
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
        _build_nested_draft_retry_payload(
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
            },
            generator=generator,
        )
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
        reference_source_markdown=_get_project_reference_source_markdown(project),
        selection_context=candidate_selection_context,
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

    if not _has_tracked_article_shell_retry_signal(
        source_markdown=source_draft_body_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
        _build_nested_draft_retry_payload(
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
            },
            generator=generator,
        )
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

    candidate_selection_context = _build_draft_candidate_selection_context(
        project=project,
        reference_source_markdown=_get_project_reference_source_markdown(project),
        reference_article_payload=reference_article_payload,
        strategy_bundle_payload=strategy_bundle_payload,
    )
    if not _should_retry_for_remaining_ai_flavor(
        source_title=source_draft_title,
        source_markdown=source_draft_body_markdown,
        candidate_title=candidate_title,
        candidate_markdown=candidate_body_markdown,
    ):
        return candidate_body_markdown, candidate_title

    retry_result = generator.generate_draft(
        _build_nested_draft_retry_payload(
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
            },
            generator=generator,
        )
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
        reference_source_markdown=_get_project_reference_source_markdown(project),
        selection_context=candidate_selection_context,
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

    candidate_selection_context = _build_draft_candidate_selection_context(
        project=project,
        reference_source_markdown=_get_project_reference_source_markdown(project),
        reference_article_payload=reference_article_payload,
        strategy_bundle_payload=strategy_bundle_payload,
    )
    current_title = candidate_title
    current_markdown = candidate_body_markdown

    for _ in range(_creative_quality_retry_max_attempts()):
        if not _should_retry_for_final_ai_flavor_cleanup(
            candidate_title=current_title,
            candidate_markdown=current_markdown,
        ):
            break

        retry_result = generator.generate_draft(
            _build_nested_draft_retry_payload(
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
                },
                generator=generator,
            )
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
            reference_source_markdown=_get_project_reference_source_markdown(project),
            selection_context=candidate_selection_context,
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
    if _has_tracked_article_shell_retry_signal(
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


def _has_unbalanced_quote_fusion_signal(markdown: str) -> bool:
    text = str(markdown or "")
    if not text:
        return False
    opening_quotes = "“‘「『"
    closing_quotes = "”’」』"
    opening_count = sum(text.count(char) for char in opening_quotes)
    closing_count = sum(text.count(char) for char in closing_quotes)
    if opening_count <= closing_count:
        return False
    paragraphs = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    speech_verbs = ("说一句", "回一句", "问一句", "只接了句", "开口还是", "电话这头", "电话那头")
    for paragraph in paragraphs:
        paragraph_opening = sum(paragraph.count(char) for char in opening_quotes)
        paragraph_closing = sum(paragraph.count(char) for char in closing_quotes)
        if paragraph_opening > paragraph_closing and any(token in paragraph for token in speech_verbs):
            return True
    return opening_count - closing_count >= 1


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
) -> tuple[str, str]:
    if review_comment or polish_instruction:
        return body_markdown, title

    candidate_selection_context = _build_draft_candidate_selection_context(
        project=project,
        reference_source_markdown=_get_project_reference_source_markdown(project),
        reference_article_payload=reference_article_payload,
        strategy_bundle_payload=strategy_bundle_payload,
    )
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
        if _looks_like_scene_first_progression_candidate(body_markdown):
            return body_markdown, title
    needs_tracked_shell_cleanup = (
        is_tracked_article
        and _has_tracked_article_shell_retry_signal(
            source_markdown=tracked_shell_source_markdown,
            candidate_title=title,
            candidate_markdown=body_markdown,
        )
    )
    if summary.level == "低" and not needs_tracked_shell_cleanup and not (
        is_tracked_article and has_opening_explainer_shell
    ) and not _has_unbalanced_quote_fusion_signal(body_markdown):
        return body_markdown, title

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
    polished_result = generator.generate_draft(
        _build_nested_draft_retry_payload(
            polish_payload,
            generator=generator,
        )
    )
    polished_title = str(polished_result["title"])
    polished_markdown = str(polished_result["body_markdown"])
    if _should_prefer_retried_candidate_after_cleanup_preview(
        current_title=title,
        current_markdown=body_markdown,
        retried_title=polished_title,
        retried_markdown=polished_markdown,
        source_type=str(project["source_type"]),
        reference_source_markdown=_get_project_reference_source_markdown(project),
        selection_context=candidate_selection_context,
    ):
        best_markdown, best_title = polished_markdown, polished_title
    else:
        best_markdown, best_title = body_markdown, title
    working_title = polished_title
    working_markdown = polished_markdown

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

    if _creative_quality_retry_max_attempts() <= 0:
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
        reference_source_markdown=_get_project_reference_source_markdown(project),
        selection_context=candidate_selection_context,
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
    payload["recommended_title"] = str(payload.get("recommended_title") or "")
    payload["social_teaser_options"] = json.loads(payload.get("social_teaser_options", "[]"))
    payload["cover_image_status"] = str(
        payload.get("cover_image_status")
        or ("ready" if str(payload.get("cover_image_url") or "").strip() else "pending")
    )
    return AssetItem(**payload)


def _hydrate_publish_package_row(package_row: sqlite3.Row) -> PublishPackageItem:
    payload = dict(package_row)
    payload["tags"] = json.loads(payload["tags"])
    payload["publish_checklist"] = json.loads(payload["publish_checklist"])
    payload["intro_options"] = json.loads(payload.get("intro_options", "[]"))
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
    raw_prompt_for_layout = normalized
    positive_phone_scene_requested = bool(re.search(r"(?:看|握着|拿着|在看|人物[^。！？!?；;\n]{0,24}手机)手机", raw_prompt_for_layout))
    chat_ui_requested = bool(_COVER_PROMPT_CHAT_UI_PATTERN.search(raw_prompt_for_layout))
    negative_chat_guard = bool(
        re.search(
            r"(?:不要|禁止|避免|不出现|不展示)[^。！？!?；;\n]{0,80}(?:聊天界面|聊天框|输入框|消息气泡|微信聊天|聊天记录|对话界面|对话框|可读屏幕)",
            normalized,
        )
    )
    if negative_chat_guard:
        normalized = re.sub(
            r"(?:不要|禁止|避免|不出现|不展示)[^。！？!?；;\n]{0,120}(?:聊天界面|聊天框|输入框|消息气泡|微信聊天|聊天记录|对话界面|对话框|可读屏幕)[^。！？!?；;\n]{0,120}[。！？!?；;]?",
            "",
            normalized,
        )
    normalized = _COVER_PROMPT_LAYOUT_CONFLICT_PATTERN.sub("", normalized)
    phone_layout_guard_needed = bool(
        re.search(
            r"(?:人物|握着|看|拿着|亮着|屏幕)[^。！？!?；;\n]{0,36}(?:手机|屏幕)|(?:手机|屏幕|聊天界面|消息气泡)[^。！？!?；;\n]{0,36}(?:作为主视觉|亮着|可见|正面|背面|前后|双屏|屏幕\s*UI)",
            raw_prompt_for_layout,
        )
    )
    if positive_phone_scene_requested and not re.search(r"(?:手机|屏幕)", normalized):
        normalized = f"{normalized}，{_COVER_PROMPT_PHONE_BACK_SCENE}" if normalized else _COVER_PROMPT_PHONE_BACK_SCENE
        phone_layout_guard_needed = True
    normalized = re.sub(r"21\s*[:：]\s*9", "16:9", normalized)
    normalized = re.sub(
        r"(?:手机)?聊天界面[和及、，,\s]*(?:消息气泡|输入框|聊天框)(?:作为主视觉)?",
        _COVER_PROMPT_PHONE_BACK_SCENE,
        normalized,
    )
    if _COVER_PROMPT_CHAT_UI_PATTERN.search(normalized):
        phone_layout_guard_needed = True
        normalized = _COVER_PROMPT_CHAT_UI_PATTERN.sub(_COVER_PROMPT_PHONE_BACK_SCENE, normalized)
        normalized = re.sub(
            rf"(?:{re.escape(_COVER_PROMPT_PHONE_BACK_SCENE)}[，,、和\s]*){{2,}}(?:作为主视觉)?",
            _COVER_PROMPT_PHONE_BACK_SCENE,
            normalized,
        )
    normalized = re.sub(r"(?:作为主视觉|手机背面也有|背面也有)(?=[，,。！？!?；;]|$)", "", normalized)
    if _COVER_PROMPT_DOUBLE_SCREEN_PATTERN.search(normalized):
        phone_layout_guard_needed = True
        normalized = _COVER_PROMPT_DOUBLE_SCREEN_PATTERN.sub("普通单屏手机，手机背面没有屏幕，不要双面手机、前后双屏或背面屏幕", normalized)
    normalized = re.sub(
        r"(?:普通单屏手机，手机背面没有屏幕，不要双面手机、前后双屏或背面屏幕[、，,\s]*){2,}",
        "普通单屏手机，手机背面没有屏幕，不要双面手机、前后双屏或背面屏幕，",
        normalized,
    )
    normalized = re.sub(r"(?:普通单屏手机[、，,\s]*){2,}", "普通单屏手机，", normalized)
    normalized = re.sub(r"[，,]\s*[，,]+", "，", normalized)
    normalized = re.sub(r"([。！？!?])\s*[，,]", r"\1", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    normalized = normalized.strip(" ，,；;")
    if (negative_chat_guard or chat_ui_requested or phone_layout_guard_needed) and "不出现聊天界面、输入框、消息气泡或可读屏幕文字" not in normalized:
        separator = "" if normalized.endswith(("。", "！", "？", "!", "?")) else "，"
        normalized = f"{normalized}{separator}不出现聊天界面、输入框、消息气泡或可读屏幕文字" if normalized else "不出现聊天界面、输入框、消息气泡或可读屏幕文字"
    if "真实摄影感" not in normalized:
        separator = "" if not normalized or normalized.endswith(("。", "！", "？", "!", "?")) else "，"
        normalized = f"{normalized}{separator}真实摄影感" if normalized else "真实摄影感"
    if "不要扁平插画感" not in normalized:
        separator = "" if normalized.endswith(("。", "！", "？", "!", "?")) else "，"
        normalized = f"{normalized}{separator}不要扁平插画感"
    if "不要在画面里生成中文文字" not in normalized:
        separator = "" if normalized.endswith(("。", "！", "？", "!", "?")) else "，"
        normalized = f"{normalized}{separator}不要在画面里生成中文文字"

    prefix_parts: list[str] = []
    if "16:9" not in normalized and "16：9" not in normalized:
        prefix_parts.append("16:9横版公众号封面")
    elif "横版" not in normalized:
        prefix_parts.append("横版公众号封面")
    if "横向" not in normalized and "宽画幅" not in normalized:
        prefix_parts.append("横向宽画幅构图")
    if "安全区" not in normalized:
        prefix_parts.append("主体位于画面中部安全区")
    if phone_layout_guard_needed and "不要双面手机" not in normalized and "前后双屏" not in normalized:
        prefix_parts.append("普通单屏手机，手机背面没有屏幕，不要双面手机、前后双屏或背面屏幕")

    if prefix_parts and normalized:
        return f"{'，'.join(prefix_parts)}，{normalized}"
    if prefix_parts:
        return "，".join(prefix_parts)
    return normalized

def _resolve_local_cover_scene_variant(*parts: str) -> str:
    corpus = re.sub(r"\s+", "", " ".join(part for part in parts if part))
    if _has_local_scene_first_transit_markers(corpus) or any(
        token in corpus for token in ("出站口", "摆渡车", "站牌", "白气", "湿路", "围巾")
    ):
        return "transit"
    if _has_local_scene_first_household_markers(corpus) or any(
        token in corpus
        for token in ("餐桌", "窗台", "夜灯", "水壶", "药盒", "检查单", "热饭", "推门回家", "灯还亮着", "饭还热着", "校服", "冰箱")
    ):
        return "household"
    if _has_local_scene_first_office_markers(corpus) or any(
        token in corpus for token in ("会议桌", "投影幕布", "早会", "方案", "工位", "会议室", "散会")
    ):
        return "office"
    return "generic"


def _should_retry_cover_image_generation_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retry_markers = (
        "temporarily unavailable",
        "service unavailable",
        "upstream_error",
        "upstream error",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "connection refused",
        "no available compatible accounts",
    )
    if any(marker in message for marker in retry_markers):
        return True
    return isinstance(exc, (openai.InternalServerError, APIConnectionError, APITimeoutError, TimeoutError))


def _resolve_cover_image_call_deadline_seconds(generator) -> float:
    configured_timeout = getattr(generator, "_image_request_timeout_seconds", None)
    if isinstance(configured_timeout, (int, float)) and configured_timeout > 0:
        return max(float(configured_timeout), 45.0)
    if bool(getattr(generator, "image_uses_custom_base_url", False)):
        return 45.0
    return 75.0


def _raise_cover_image_generation_failure(exc: Exception) -> None:
    detail = format_image_upstream_failure_message(
        exc,
        prefix="封面生成失败",
        api_only=True,
    )
    http_error = HTTPException(status_code=502, detail=detail)
    for attr_name in ("cover_image_route_label", "cover_image_route_model", "cover_image_route_base_url"):
        attr_value = getattr(exc, attr_name, None)
        if attr_value is not None:
            setattr(http_error, attr_name, attr_value)
    raise http_error from exc


def _attach_cover_route_info_to_error(exc: Exception, route_info: Mapping[str, object] | None) -> None:
    if not isinstance(route_info, Mapping):
        return
    route_label = str(route_info.get("label") or "").strip() or None
    route_model = str(route_info.get("model") or "").strip() or None
    route_base_url = str(route_info.get("base_url") or "").strip() or None
    if route_label is not None:
        setattr(exc, "cover_image_route_label", route_label)
    if route_model is not None:
        setattr(exc, "cover_image_route_model", route_model)
    if route_base_url is not None:
        setattr(exc, "cover_image_route_base_url", route_base_url)


def _invoke_cover_image_generation_with_deadline(
    *,
    generator,
    cover_payload: dict[str, object],
    deadline_seconds: float,
) -> tuple[bytes, dict[str, object] | None]:
    result: dict[str, object] = {}

    def _runner() -> None:
        try:
            if callable(getattr(generator, "generate_cover_image_with_route_info", None)):
                image_bytes, route_info = generator.generate_cover_image_with_route_info(cover_payload)
                result["bytes"] = image_bytes
                result["route_info"] = route_info
                return
            result["bytes"] = generator.generate_cover_image(cover_payload)
            last_route_info = getattr(generator, "last_cover_image_route_info", None)
            if isinstance(last_route_info, dict):
                result["route_info"] = dict(last_route_info)
        except Exception as exc:  # pragma: no cover - exercised through caller
            last_route_info = getattr(generator, "last_cover_image_route_info", None)
            if isinstance(last_route_info, dict):
                result["route_info"] = dict(last_route_info)
                _attach_cover_route_info_to_error(exc, last_route_info)
            result["error"] = exc

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join(timeout=deadline_seconds)
    if worker.is_alive():
        timeout_error = TimeoutError(f"Cover image generation exceeded {deadline_seconds:.2f}s deadline")
        last_route_info = getattr(generator, "last_cover_image_route_info", None)
        if isinstance(last_route_info, dict):
            _attach_cover_route_info_to_error(timeout_error, last_route_info)
        raise timeout_error
    error = result.get("error")
    if isinstance(error, Exception):
        raise error
    image_bytes = result.get("bytes")
    if not isinstance(image_bytes, (bytes, bytearray)):
        raise RuntimeError("Cover image generation returned no binary payload")
    route_info = result.get("route_info")
    return bytes(image_bytes), dict(route_info) if isinstance(route_info, dict) else None


def _generate_cover_image_file(
    *,
    generator,
    project_slug: str,
    project_title: str,
    normalized_cover_prompt: str,
    cover_copy: str,
    cover_file_path: Path,
) -> _CoverImageFileResult:
    try:
        max_attempts = _image_generation_max_attempts()
        cover_payload = {
            "project_slug": project_slug,
            "project_title": project_title,
            "cover_prompt": normalized_cover_prompt,
            "cover_copy": cover_copy,
            "image_generation_max_attempts": max_attempts,
        }
        call_deadline_seconds = _resolve_cover_image_call_deadline_seconds(generator)
        cover_image_bytes, route_info = _invoke_cover_image_generation_with_deadline(
            generator=generator,
            cover_payload=cover_payload,
            deadline_seconds=call_deadline_seconds,
        )
        cover_file_path.write_bytes(cover_image_bytes)
        route_label = None
        route_model = None
        route_base_url = None
        if isinstance(route_info, dict):
            route_label = str(route_info.get("label") or "").strip() or None
            route_model = str(route_info.get("model") or "").strip() or None
            route_base_url = str(route_info.get("base_url") or "").strip() or None
        return _CoverImageFileResult(
            path=str(cover_file_path),
            url=f"/generated-assets/{cover_file_path.name}",
            route_label=route_label,
            route_model=route_model,
            route_base_url=route_base_url,
        )
    except Exception as exc:
        logger.warning(
            "AI cover image generation failed for project %s: %s; API-only mode is active, surfacing failure.",
            project_slug,
            exc,
        )
        _raise_cover_image_generation_failure(exc)


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
    error_context: BackgroundTaskErrorContext | None = None
    if isinstance(result, dict) and "__error_context" in result:
        raw_error_context = result.get("__error_context")
        if isinstance(raw_error_context, dict):
            error_context = BackgroundTaskErrorContext.model_validate(raw_error_context)
        filtered_result = {key: value for key, value in result.items() if key != "__error_context"}
        result = filtered_result or None
    return BackgroundTaskDetail(
        task_id=str(row["task_id"]),
        job_type=str(row["job_type"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row["started_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        error=str(row["error"]) if row["error"] else None,
        error_context=error_context,
        result=result,
    )


def _build_background_task_error_context(exc: Exception) -> dict[str, object] | None:
    status_code = exc.status_code if isinstance(exc, HTTPException) else None
    detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
    context: dict[str, object] = {
        "type": exc.__class__.__name__,
        "status_code": status_code,
        "detail": detail,
    }

    has_cover_route_context = False
    for attr_name in ("cover_image_route_label", "cover_image_route_model", "cover_image_route_base_url"):
        value = getattr(exc, attr_name, None)
        if value is not None:
            context[attr_name] = value
            has_cover_route_context = True

    if has_cover_route_context:
        try:
            ai_config_summary = get_ai_config_summary()
        except Exception:
            ai_config_summary = None
        if ai_config_summary is not None:
            context["fallback_account_pool_diagnosis_status"] = ai_config_summary.image_fallback_account_pool_diagnosis_status
            context["fallback_account_pool_diagnosis_label"] = ai_config_summary.image_fallback_account_pool_diagnosis_label
            context["fallback_account_pool_diagnosis_note"] = ai_config_summary.image_fallback_account_pool_diagnosis_note

    return context


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
        error_context = _build_background_task_error_context(exc)
        result_payload = {"__error_context": error_context} if error_context else None
        with _get_connection() as connection:
            connection.execute(
                """
                UPDATE background_tasks
                SET status = ?, error = ?, result = ?, finished_at = ?
                WHERE task_id = ?
                """,
                (
                    "failed",
                    str(exc.detail),
                    json.dumps(result_payload, ensure_ascii=False) if result_payload is not None else None,
                    _utc_now_iso(),
                    task_id,
                ),
            )
            _update_background_task_log_status(
                connection,
                background_task_id=task_id,
                status="failed",
            )
            connection.commit()
    except Exception as exc:
        error_context = _build_background_task_error_context(exc)
        result_payload = {"__error_context": error_context} if error_context else None
        with _get_connection() as connection:
            connection.execute(
                """
                UPDATE background_tasks
                SET status = ?, error = ?, result = ?, finished_at = ?
                WHERE task_id = ?
                """,
                (
                    "failed",
                    str(exc),
                    json.dumps(result_payload, ensure_ascii=False) if result_payload is not None else None,
                    _utc_now_iso(),
                    task_id,
                ),
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
            _ensure_runtime_chain_schema(connection)
            assets_row = connection.execute(
                """
                SELECT
                    project_slug,
                    draft_version,
                    version,
                    title_options,
                    recommended_title,
                    cover_prompt,
                    cover_copy,
                    social_teaser,
                    social_teaser_options,
                    cover_image_path,
                    cover_image_url,
                    cover_image_status,
                    cover_image_error,
                    cover_image_route_label,
                    cover_image_route_model,
                    cover_image_route_base_url,
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
            if str(assets_row["cover_image_status"] or "pending") == "quality_blocked":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "封面图暂未重生成：素材包装未通过主题质量门。请先重新生成素材包，再生成封面图。"
                        + (f" 原始返回：{assets_row['cover_image_error']}" if assets_row["cover_image_error"] else "")
                    ),
                )

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
            cover_result = _generate_cover_image_file(
                generator=get_ai_generator(),
                project_slug=project_slug,
                project_title=str(project["title"]),
                normalized_cover_prompt=normalized_cover_prompt,
                cover_copy=str(assets_row["cover_copy"]),
                cover_file_path=cover_file_path,
            )
            cover_image_path = cover_result.path
            cover_image_url = cover_result.url

            connection.execute(
                """
                INSERT INTO assets (
                    project_slug, draft_version, version, title_options, recommended_title, cover_prompt, cover_copy, social_teaser, social_teaser_options,
                    cover_image_path, cover_image_url, cover_image_status, cover_image_error,
                    cover_image_route_label, cover_image_route_model, cover_image_route_base_url,
                    created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    assets_row["draft_version"],
                    next_version,
                    assets_row["title_options"],
                    assets_row["recommended_title"],
                    normalized_cover_prompt,
                    assets_row["cover_copy"],
                    assets_row["social_teaser"],
                    assets_row["social_teaser_options"],
                    cover_image_path,
                    cover_image_url,
                    "ready",
                    None,
                    cover_result.route_label,
                    cover_result.route_model,
                    cover_result.route_base_url,
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
        recommended_title=str(assets_row["recommended_title"] or ""),
        cover_prompt=normalized_cover_prompt,
        cover_copy=str(assets_row["cover_copy"]),
        social_teaser=str(assets_row["social_teaser"]),
        social_teaser_options=json.loads(str(assets_row["social_teaser_options"])),
        cover_image_path=cover_image_path,
        cover_image_url=cover_image_url,
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label=cover_result.route_label,
        cover_image_route_model=cover_result.route_model,
        cover_image_route_base_url=cover_result.route_base_url,
        created_at=created_at,
        origin=origin,
        tone_profile_id=int(assets_row["tone_profile_id"]) if assets_row["tone_profile_id"] is not None else None,
        tone_profile_name=str(assets_row["tone_profile_name"]) if assets_row["tone_profile_name"] is not None else None,
    )


def restore_assets_version(project_slug: str, version: int) -> AssetItem:
    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            _ensure_runtime_chain_schema(connection)
            assets_row = connection.execute(
                """
                SELECT
                    project_slug,
                    draft_version,
                    version,
                    title_options,
                    recommended_title,
                    cover_prompt,
                    cover_copy,
                    social_teaser,
                    social_teaser_options,
                    cover_image_path,
                    cover_image_url,
                    cover_image_status,
                    cover_image_error,
                    cover_image_route_label,
                    cover_image_route_model,
                    cover_image_route_base_url,
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
                    project_slug, draft_version, version, title_options, recommended_title, cover_prompt, cover_copy, social_teaser, social_teaser_options,
                    cover_image_path, cover_image_url, cover_image_status, cover_image_error,
                    cover_image_route_label, cover_image_route_model, cover_image_route_base_url,
                    created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    assets_row["draft_version"],
                    next_version,
                    assets_row["title_options"],
                    assets_row["recommended_title"],
                    assets_row["cover_prompt"],
                    assets_row["cover_copy"],
                    assets_row["social_teaser"],
                    assets_row["social_teaser_options"],
                    assets_row["cover_image_path"],
                    assets_row["cover_image_url"],
                    assets_row["cover_image_status"],
                    assets_row["cover_image_error"],
                    assets_row["cover_image_route_label"],
                    assets_row["cover_image_route_model"],
                    assets_row["cover_image_route_base_url"],
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
                (
                    "assets_ready"
                    if str(assets_row["cover_image_status"] or "pending") == "ready"
                    and str(assets_row["cover_image_url"] or "").strip()
                    else "assets_quality_blocked"
                    if str(assets_row["cover_image_status"] or "pending") == "quality_blocked"
                    else "assets_pending_cover",
                    project_slug,
                ),
            )
            connection.commit()

    return AssetItem(
        project_slug=project_slug,
        draft_version=int(assets_row["draft_version"]),
        version=next_version,
        title_options=json.loads(str(assets_row["title_options"])),
        recommended_title=str(assets_row["recommended_title"] or ""),
        cover_prompt=str(assets_row["cover_prompt"]),
        cover_copy=str(assets_row["cover_copy"]),
        social_teaser=str(assets_row["social_teaser"]),
        social_teaser_options=json.loads(str(assets_row["social_teaser_options"])),
        cover_image_path=str(assets_row["cover_image_path"]),
        cover_image_url=str(assets_row["cover_image_url"]),
        cover_image_status=str(assets_row["cover_image_status"] or "pending"),
        cover_image_error=str(assets_row["cover_image_error"]) if assets_row["cover_image_error"] is not None else None,
        cover_image_route_label=str(assets_row["cover_image_route_label"]) if assets_row["cover_image_route_label"] is not None else None,
        cover_image_route_model=str(assets_row["cover_image_route_model"]) if assets_row["cover_image_route_model"] is not None else None,
        cover_image_route_base_url=str(assets_row["cover_image_route_base_url"]) if assets_row["cover_image_route_base_url"] is not None else None,
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
            _ensure_runtime_chain_schema(connection)
            problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(
                connection,
                project_slug,
                adopted_only=True,
            )
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
            assets_payload: dict[str, object] = {
                "trend_title": project["trend_title"],
                "topic_title": project["topic_title"],
                "topic_angle": project["topic_angle"],
                "project_title": project["title"],
                "source_type": project["source_type"],
                "draft": {
                    "title": draft_row["title"],
                    "body_markdown": draft_row["body_markdown"],
                },
                "tone_profile": tone_profile.model_dump(),
                "domain_pack": domain_pack,
                "review_comment": review_comment,
                "reference_article_hidden": str(project["source_type"]) == "tracked_article" and bool(problem_brief and strategy_card),
            }
            if problem_brief and strategy_card:
                assets_payload["problem_brief"] = problem_brief.model_dump()
                assets_payload["strategy_card"] = strategy_card.model_dump()
                assets_payload["benchmarks"] = [benchmark.model_dump() for benchmark in benchmarks]
            generator = get_ai_generator()
            used_local_assets_fallback = False

            def _build_current_local_assets_fallback() -> dict[str, object]:
                return _build_local_assets_fallback(
                    project_title=str(project["title"]),
                    topic_title=str(project["topic_title"]),
                    topic_angle=str(project["topic_angle"]),
                    draft_title=str(draft_row["title"]),
                    draft_body_markdown=str(draft_row["body_markdown"]),
                )

            if (
                bool(getattr(generator, "uses_custom_base_url", False))
                and str(project["source_type"]) == "tracked_article"
                and problem_brief
                and strategy_card
            ):
                try:
                    ai_result = generator.generate_assets(assets_payload)
                except _OUTLINE_TRANSIENT_PROVIDER_ERRORS as exc:
                    logger.warning(
                        "Tracked article assets transient failure for project %s; retrying with compact packaging prompt: %s",
                        project_slug,
                        exc,
                    )
                    recovery_payload = _build_assets_timeout_recovery_payload(
                        assets_payload=assets_payload,
                    )
                    try:
                        ai_result = generator.generate_assets(recovery_payload)
                    except Exception as recovery_exc:
                        if not _allow_local_creative_fallbacks():
                            if isinstance(recovery_exc, _OUTLINE_TRANSIENT_PROVIDER_ERRORS):
                                _raise_creative_upstream_failure("素材文案生成", recovery_exc)
                            raise
                        logger.warning(
                            "Tracked article assets recovery failed for project %s; using local assets fallback: %s",
                            project_slug,
                            recovery_exc,
                        )
                        ai_result = _build_current_local_assets_fallback()
                        used_local_assets_fallback = True
                except Exception as exc:
                    if not _allow_local_creative_fallbacks():
                        raise
                    logger.warning(
                        "Tracked article assets generation failed for project %s; using local assets fallback: %s",
                        project_slug,
                        exc,
                    )
                    ai_result = _build_current_local_assets_fallback()
                    used_local_assets_fallback = True
            else:
                try:
                    ai_result = generator.generate_assets(assets_payload)
                except _OUTLINE_TRANSIENT_PROVIDER_ERRORS as exc:
                    if not bool(getattr(generator, "uses_custom_base_url", False)):
                        raise
                    logger.warning(
                        "Assets transient failure for project %s; retrying with compact packaging prompt: %s",
                        project_slug,
                        exc,
                    )
                    recovery_payload = _build_assets_timeout_recovery_payload(
                        assets_payload=assets_payload,
                    )
                    ai_result = generator.generate_assets(recovery_payload)
            ai_result = _sanitize_assets_packaging_result(ai_result)
            if (
                _creative_quality_retry_max_attempts() > 0
                and (not used_local_assets_fallback)
                and _should_retry_assets_for_packaging(
                    strategy_bundle_payload={
                        "problem_brief": assets_payload.get("problem_brief"),
                        "strategy_card": assets_payload.get("strategy_card"),
                    },
                    ai_result=ai_result,
                )
            ):
                retry_payload = dict(assets_payload)
                retry_payload["review_comment"] = _merge_retry_review_comment(
                    review_comment,
                    _build_assets_packaging_retry_instruction(
                        {
                            "problem_brief": assets_payload.get("problem_brief"),
                            "strategy_card": assets_payload.get("strategy_card"),
                        }
                    ),
                )
                try:
                    retried_result = generator.generate_assets(retry_payload)
                except _OUTLINE_TRANSIENT_PROVIDER_ERRORS as exc:
                    if not _allow_local_creative_fallbacks():
                        _raise_creative_upstream_failure("素材文案生成", exc)
                    if not (
                        bool(getattr(generator, "uses_custom_base_url", False))
                        and str(project["source_type"]) == "tracked_article"
                        and problem_brief
                        and strategy_card
                    ):
                        raise
                    logger.warning(
                        "Assets packaging retry failed for project %s; using local assets fallback: %s",
                        project_slug,
                        exc,
                    )
                    ai_result = _build_current_local_assets_fallback()
                    used_local_assets_fallback = True
                else:
                    retried_result = _sanitize_assets_packaging_result(retried_result)
                    retried_still_needs_retry = _should_retry_assets_for_packaging(
                        strategy_bundle_payload={
                            "problem_brief": assets_payload.get("problem_brief"),
                            "strategy_card": assets_payload.get("strategy_card"),
                        },
                        ai_result=retried_result,
                    )
                    if not retried_still_needs_retry:
                        ai_result = retried_result
                    elif str(project["source_type"]) == "tracked_article" and problem_brief and strategy_card:
                        logger.warning(
                            "Assets packaging retry still failed quality gate for project %s; keeping API result and skipping local fallback.",
                            project_slug,
                        )
                        ai_result = retried_result
            if str(project["source_type"]) == "tracked_article":
                ai_result = _rewrite_tracked_article_danger_result_fields(
                    source_markdown=str(project["reference_article_body_markdown"] or ""),
                    ai_result=ai_result,
                    text_fields=("recommended_title", "cover_prompt", "cover_copy", "social_teaser"),
                    list_fields=("title_options", "social_teaser_options"),
                )
                ai_result = _sanitize_responsibility_shelter_result_fields(
                    ai_result=ai_result,
                    title=str(draft_row["title"]),
                    body_markdown=str(draft_row["body_markdown"]),
                    reference_source_markdown=str(project["reference_article_body_markdown"] or ""),
                    text_fields=("recommended_title", "cover_prompt", "cover_copy", "social_teaser"),
                    list_fields=("title_options", "social_teaser_options"),
                )
                ai_result = _sanitize_assets_packaging_result(ai_result)
                assets_packaging_quality_failed = (not used_local_assets_fallback) and _should_retry_assets_for_packaging(
                    strategy_bundle_payload={
                        "problem_brief": assets_payload.get("problem_brief"),
                        "strategy_card": assets_payload.get("strategy_card"),
                    },
                    ai_result=ai_result,
                )
                if assets_packaging_quality_failed:
                    logger.warning(
                        "Assets post-processing failed packaging quality gate for project %s; keeping API result and skipping local fallback.",
                        project_slug,
                    )
            else:
                assets_packaging_quality_failed = False
            recommended_title = str(ai_result.get("recommended_title") or "").strip()
            title_options = list(ai_result["title_options"])
            if not recommended_title:
                recommended_title = title_options[0] if title_options else ""
            elif recommended_title not in title_options and recommended_title:
                title_options = [recommended_title, *[title for title in title_options if title != recommended_title]]
            normalized_cover_prompt = _normalize_cover_prompt_layout(str(ai_result["cover_prompt"]))
            cover_filename = f"{project_slug}-assets-v{version}.png"
            cover_file_path = GENERATED_ASSETS_DIR / cover_filename
            cover_image_path = ""
            cover_image_url = ""
            cover_image_status = "pending"
            cover_image_error: str | None = None
            cover_image_route_label: str | None = None
            cover_image_route_model: str | None = None
            cover_image_route_base_url: str | None = None
            packaging_quality_blocked = (
                str(project["source_type"]) == "tracked_article"
                and bool(assets_packaging_quality_failed)
            )
            if packaging_quality_blocked:
                cover_image_status = "quality_blocked"
                cover_image_error = "素材包装未通过主题质量门，已跳过封面图 API。请先重新生成素材包。"
                logger.warning(
                    "Assets packaging quality gate failed for project %s; skipping cover image API call.",
                    project_slug,
                )
            else:
                try:
                    cover_result = _generate_cover_image_file(
                        generator=generator,
                        project_slug=project_slug,
                        project_title=str(project["title"]),
                        normalized_cover_prompt=normalized_cover_prompt,
                        cover_copy=str(ai_result["cover_copy"]),
                        cover_file_path=cover_file_path,
                    )
                except HTTPException as exc:
                    if exc.status_code != 502:
                        raise
                    cover_image_error = str(exc.detail)
                    cover_image_route_label = getattr(exc, "cover_image_route_label", None)
                    cover_image_route_model = getattr(exc, "cover_image_route_model", None)
                    cover_image_route_base_url = getattr(exc, "cover_image_route_base_url", None)
                    logger.warning(
                        "Cover image remains pending for project %s; preserving generated text assets for API retry.",
                        project_slug,
                    )
                else:
                    cover_image_path = cover_result.path
                    cover_image_url = cover_result.url
                    cover_image_status = "ready"
                    cover_image_route_label = cover_result.route_label
                    cover_image_route_model = cover_result.route_model
                    cover_image_route_base_url = cover_result.route_base_url
            connection.execute(
                """
                INSERT INTO assets (
                    project_slug, draft_version, version, title_options, recommended_title, cover_prompt, cover_copy, social_teaser, social_teaser_options,
                    cover_image_path, cover_image_url, cover_image_status, cover_image_error,
                    cover_image_route_label, cover_image_route_model, cover_image_route_base_url,
                    created_at, origin, tone_profile_id, tone_profile_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_slug,
                    draft_row["version"],
                    version,
                    json.dumps(title_options, ensure_ascii=False),
                    recommended_title,
                    normalized_cover_prompt,
                    ai_result["cover_copy"],
                    ai_result["social_teaser"],
                    json.dumps(ai_result.get("social_teaser_options", []), ensure_ascii=False),
                    cover_image_path,
                    cover_image_url,
                    cover_image_status,
                    cover_image_error,
                    cover_image_route_label,
                    cover_image_route_model,
                    cover_image_route_base_url,
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
                (
                    "assets_ready"
                    if cover_image_status == "ready"
                    else "assets_quality_blocked"
                    if cover_image_status == "quality_blocked"
                    else "assets_pending_cover",
                    project_slug,
                ),
            )
            connection.commit()

    return AssetItem(
        project_slug=project_slug,
        draft_version=int(draft_row["version"]),
        version=version,
        title_options=title_options,
        recommended_title=recommended_title,
        cover_prompt=normalized_cover_prompt,
        cover_copy=str(ai_result["cover_copy"]),
        social_teaser=str(ai_result["social_teaser"]),
        social_teaser_options=list(ai_result.get("social_teaser_options", [])),
        cover_image_path=cover_image_path,
        cover_image_url=cover_image_url,
        cover_image_status=cover_image_status,
        cover_image_error=cover_image_error,
        cover_image_route_label=cover_image_route_label,
        cover_image_route_model=cover_image_route_model,
        cover_image_route_base_url=cover_image_route_base_url,
        created_at=created_at,
        origin=origin,
        tone_profile_id=tone_profile.id,
        tone_profile_name=tone_profile.name,
    )


def build_publish_package(project_slug: str) -> PublishPackageItem:
    return _build_publish_package(project_slug)


def _maybe_reuse_latest_publish_package_after_cover_refresh(
    connection: sqlite3.Connection,
    *,
    project_slug: str,
    draft_version: int,
    assets_row: sqlite3.Row,
) -> dict[str, object] | None:
    if str(assets_row["origin"] or "") != "cover_regeneration":
        return None

    latest_package_row = connection.execute(
        """
        SELECT
            draft_version,
            assets_version,
            abstract,
            tags,
            publish_checklist,
            editor_note,
            publish_title,
            publish_lead,
            intro_options,
            tone_profile_id,
            tone_profile_name
        FROM publish_packages
        WHERE project_slug = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (project_slug,),
    ).fetchone()
    if not latest_package_row or int(latest_package_row["draft_version"]) != draft_version:
        return None

    source_assets_row = connection.execute(
        """
        SELECT
            title_options,
            recommended_title,
            cover_prompt,
            cover_copy,
            social_teaser,
            social_teaser_options
        FROM assets
        WHERE project_slug = ? AND version = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_slug, int(latest_package_row["assets_version"])),
    ).fetchone()
    if not source_assets_row:
        return None

    comparable_columns = (
        "title_options",
        "recommended_title",
        "cover_prompt",
        "cover_copy",
        "social_teaser",
        "social_teaser_options",
    )
    if any(str(assets_row[column] or "") != str(source_assets_row[column] or "") for column in comparable_columns):
        return None

    return {
        "abstract": str(latest_package_row["abstract"]),
        "tags": json.loads(str(latest_package_row["tags"])),
        "publish_checklist": json.loads(str(latest_package_row["publish_checklist"])),
        "editor_note": str(latest_package_row["editor_note"]),
        "publish_title": str(latest_package_row["publish_title"]),
        "publish_lead": str(latest_package_row["publish_lead"]),
        "intro_options": json.loads(str(latest_package_row["intro_options"] or "[]")),
        "tone_profile_id": latest_package_row["tone_profile_id"],
        "tone_profile_name": latest_package_row["tone_profile_name"],
    }


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
    _ensure_generated_assets_dir()
    with _get_connection() as connection:
        _ensure_runtime_chain_schema(connection)
        problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(
            connection,
            project_slug,
            adopted_only=True,
        )
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
                recommended_title,
                cover_prompt,
                cover_copy,
                social_teaser,
                social_teaser_options,
                cover_image_path,
                cover_image_url,
                cover_image_status,
                cover_image_error,
                cover_image_route_label,
                cover_image_route_model,
                cover_image_route_base_url,
                origin,
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
        if str(project["source_type"]) == "tracked_article":
            draft_body_markdown = _apply_final_tracked_article_guard(
                title=draft_title,
                body_markdown=draft_body_markdown,
                source_type="tracked_article",
                reference_source_markdown=str(project["reference_article_body_markdown"] or ""),
            )
        assets = _hydrate_asset_row(assets_row)
        if assets.cover_image_status != "ready" or not assets.cover_image_url.strip():
            if assets.cover_image_status == "quality_blocked":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "发布包暂未生成：素材包装未通过主题质量门。请先重新生成素材包，再生成封面和发布包。"
                        + (f" 原始返回：{assets.cover_image_error}" if assets.cover_image_error else "")
                    ),
                )
            cover_pending_error = HTTPException(
                status_code=409,
                detail=(
                    "发布包暂未生成：封面图片仍待 API 补齐。请先重试图片 API，成功后再生成发布包。"
                    + (f" 原始返回：{assets.cover_image_error}" if assets.cover_image_error else "")
                ),
            )
            _attach_cover_route_info_to_error(
                cover_pending_error,
                {
                    "label": assets.cover_image_route_label,
                    "model": assets.cover_image_route_model,
                    "base_url": assets.cover_image_route_base_url,
                },
            )
            raise cover_pending_error
        if package_override is None:
            package_override = _maybe_reuse_latest_publish_package_after_cover_refresh(
                connection,
                project_slug=project_slug,
                draft_version=draft_version,
                assets_row=assets_row,
            )

    if package_override and package_override.get("tone_profile_name") is not None:
        effective_tone_profile_id = int(package_override["tone_profile_id"]) if package_override.get("tone_profile_id") is not None else None
        effective_tone_profile_name = str(package_override["tone_profile_name"])

    publish_payload: dict[str, object] = {
        "project_title": project["title"],
        "source_type": project["source_type"],
        "draft": {
            "title": draft_title,
            "body_markdown": draft_body_markdown,
        },
        "assets": assets.model_dump(),
        "tone_profile": tone_profile.model_dump(),
        "domain_pack": domain_pack,
        "review_comment": review_comment,
        "reference_article_hidden": str(project["source_type"]) == "tracked_article" and bool(problem_brief and strategy_card),
    }
    if problem_brief and strategy_card:
        publish_payload["problem_brief"] = problem_brief.model_dump()
        publish_payload["strategy_card"] = strategy_card.model_dump()
        publish_payload["benchmarks"] = [benchmark.model_dump() for benchmark in benchmarks]

    fallback_asset_title = assets.recommended_title or (assets.title_options[0] if assets.title_options else "")
    generator = get_ai_generator()
    if package_override:
        ai_result = package_override
    else:
        try:
            if (
                bool(getattr(generator, "uses_custom_base_url", False))
                and str(project["source_type"]) == "tracked_article"
                and problem_brief
                and strategy_card
            ):
                try:
                    ai_result = generator.generate_publish_package(publish_payload)
                except (APITimeoutError, APIConnectionError, openai.InternalServerError) as exc:
                    logger.warning(
                        "Tracked article publish package transient failure for project %s; retrying with compact publish prompt: %s",
                        project_slug,
                        exc,
                    )
                    recovery_payload = _build_publish_timeout_recovery_payload(
                        publish_payload=publish_payload,
                    )
                    ai_result = generator.generate_publish_package(recovery_payload)
            else:
                ai_result = generator.generate_publish_package(publish_payload)
            ai_result = _sanitize_publish_packaging_result(
                ai_result,
                draft_body_markdown=draft_body_markdown,
                assets=assets,
                fallback_title=fallback_asset_title or draft_title,
            )
            if _creative_quality_retry_max_attempts() > 0 and _should_retry_publish_package_for_packaging(
                strategy_bundle_payload={
                    "problem_brief": publish_payload.get("problem_brief"),
                    "strategy_card": publish_payload.get("strategy_card"),
                },
                ai_result=ai_result,
            ):
                retry_payload = dict(publish_payload)
                retry_payload["review_comment"] = _merge_retry_review_comment(
                    review_comment,
                    _build_publish_packaging_retry_instruction(
                        {
                            "problem_brief": publish_payload.get("problem_brief"),
                            "strategy_card": publish_payload.get("strategy_card"),
                        }
                    ),
                )
                retried_result = generator.generate_publish_package(retry_payload)
                retried_result = _sanitize_publish_packaging_result(
                    retried_result,
                    draft_body_markdown=draft_body_markdown,
                    assets=assets,
                    fallback_title=fallback_asset_title or draft_title,
                )
                retried_still_needs_retry = _should_retry_publish_package_for_packaging(
                    strategy_bundle_payload={
                        "problem_brief": publish_payload.get("problem_brief"),
                        "strategy_card": publish_payload.get("strategy_card"),
                    },
                    ai_result=retried_result,
                )
                if not retried_still_needs_retry:
                    ai_result = retried_result
                elif str(project["source_type"]) == "tracked_article" and problem_brief and strategy_card:
                    logger.warning(
                        "Publish packaging retry still failed quality gate for project %s; keeping API result and skipping local fallback.",
                        project_slug,
                    )
                    ai_result = retried_result
        except (APITimeoutError, APIConnectionError, openai.InternalServerError, openai.RateLimitError) as exc:
            if not _allow_local_creative_fallbacks():
                _raise_creative_upstream_failure("发布包生成", exc)
            logger.warning(
                "Publish package generation failed for project %s: %s; using local fallback.",
                project_slug,
                exc,
            )
            ai_result = _build_local_publish_package_fallback(
                draft_title=draft_title,
                draft_body_markdown=draft_body_markdown,
                assets=assets,
            )
    if str(project["source_type"]) == "tracked_article":
        ai_result = _rewrite_tracked_article_danger_result_fields(
            source_markdown=str(project["reference_article_body_markdown"] or ""),
            ai_result=ai_result,
            text_fields=("abstract", "publish_title", "publish_lead", "editor_note"),
            list_fields=("intro_options",),
        )
        ai_result = _sanitize_responsibility_shelter_result_fields(
            ai_result=ai_result,
            title=draft_title,
            body_markdown=draft_body_markdown,
            reference_source_markdown=str(project["reference_article_body_markdown"] or ""),
            text_fields=("abstract", "publish_title", "publish_lead", "editor_note"),
            list_fields=("intro_options",),
        )
        ai_result = _sanitize_publish_packaging_result(
            ai_result,
            draft_body_markdown=draft_body_markdown,
            assets=assets,
            fallback_title=fallback_asset_title or draft_title,
        )
        if _should_retry_publish_package_for_packaging(
            strategy_bundle_payload={
                "problem_brief": publish_payload.get("problem_brief"),
                "strategy_card": publish_payload.get("strategy_card"),
            },
            ai_result=ai_result,
        ):
            logger.warning(
                "Publish post-processing failed packaging quality gate for project %s; keeping API result and skipping local fallback.",
                project_slug,
            )
    publish_title = str(ai_result.get("publish_title") or fallback_asset_title or draft_title)
    publish_lead = str(ai_result.get("publish_lead") or assets.social_teaser)
    intro_options = list(ai_result.get("intro_options", []))
    if not intro_options:
        intro_options = list(assets.social_teaser_options)
    if publish_lead and publish_lead not in intro_options:
        intro_options = [publish_lead, *[item for item in intro_options if item != publish_lead]]
    publish_checklist = list(package_override["publish_checklist"]) if package_override and "publish_checklist" in package_override else _build_publish_checklist()

    with _get_project_version_lock(project_slug):
        with _get_connection() as connection:
            _ensure_runtime_chain_schema(connection)
            connection.commit()
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
                publish_title=publish_title,
                publish_lead=publish_lead,
                intro_options=intro_options,
                tone_profile_name=effective_tone_profile_name,
            )
            manifest_body = {
                "project_slug": project_slug,
                "project_title": project["title"],
                "draft_version": draft_version,
                "assets_version": assets.version,
                "abstract": ai_result["abstract"],
                "publish_title": publish_title,
                "publish_lead": publish_lead,
                "intro_options": intro_options,
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
                "publish_title": publish_title,
                "publish_lead": publish_lead,
                "intro_options": json.dumps(intro_options, ensure_ascii=False),
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
                payload["cover_title"] = fallback_asset_title or draft_title
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
        publish_title=publish_title,
        publish_lead=publish_lead,
        intro_options=intro_options,
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
            SELECT abstract, tags, publish_checklist, editor_note, publish_title, publish_lead, intro_options, tone_profile_id, tone_profile_name
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
            "publish_title": str(package_row["publish_title"]),
            "publish_lead": str(package_row["publish_lead"]),
            "intro_options": json.loads(str(package_row["intro_options"] or "[]")),
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
    payload["intro_options"] = json.loads(payload.get("intro_options", "[]"))
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
    publish_title: str,
    publish_lead: str,
    intro_options: list[str],
    tone_profile_name: str | None,
) -> str:
    sections = [f"# {publish_title or draft_title}".strip()]
    lead = str(publish_lead or "").strip()
    body = str(draft_body or "").strip()
    if lead and body:
        first_body_sentence = ""
        for paragraph in _extract_non_heading_paragraphs(body):
            sentences = _split_block_sentences(paragraph)
            if sentences:
                first_body_sentence = sentences[0].strip()
                break
        if first_body_sentence and lead.startswith(first_body_sentence):
            trimmed_lead = lead[len(first_body_sentence) :].lstrip("，,；;。.!?？、 ").strip()
            if trimmed_lead:
                lead = trimmed_lead
    if lead:
        sections.append(lead)
    if body:
        sections.append(body)
    return "\n\n".join(section for section in sections if section).rstrip() + "\n"


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
    if next_required_step == "regenerate_cover_image":
        return regenerate_cover_image(project_slug)
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
        if project.current_chain_state == "assets_quality_blocked":
            skipped_count += 1
            results.append(
                BatchContinueProjectResult(
                    slug=project.slug,
                    status="blocked",
                    started_next_step=started_next_step,
                    error="素材包装未通过主题质量门；批量续链已停止，避免重复消耗文本和图片 API。请先重新生成素材包。",
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

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATED_RULES_PATH = REPO_ROOT / "generated" / "dbskill" / "tracked_article_rules.json"

_LOCALIZED_RULE_REPLACEMENTS = {
    "如果一句话还说不清楚，先退回到具体场景、动作和顺序，不要急着下结论。": (
        "如果一句话还说不清楚，先退回到现实接口、读者处境和价值承接，"
        "不要急着铺场景或下结论。"
    ),
    "不要只给概念命名，要让每个判断都落到具体用法、动作或关系变化上。": (
        "不要只给概念命名，要让每个判断都落到情绪推进、关系变化或现实落点上。"
    ),
    "每一节都要能落到具体场景、动作或关系变化，不能只摆概念。": (
        "每一节都要能落到情绪推进、关系变化或现实落点，不能只摆概念，也不能用场景描写凑篇幅。"
    ),
    "遇到匀速排比和整齐翻转时，优先把句子拉回动作、停顿和关系变化。": (
        "遇到匀速排比和整齐翻转时，优先把句子拉回现实接口、判断推进和关系变化。"
    ),
    "开头先给一个抓手：动作、界面、物件、空间距离或身体反应，先别下总判断。": (
        "开头先给一个现实抓手：动作、关系、物件、场景或当下卡点，"
        "不用大道理冷启动。"
    ),
    "每次只保留一个最想强调的判断，其余判断埋回过程、动作和后果里。": (
        "每次只保留一个最想强调的判断，其余判断埋回过程、情绪推进和现实落点里。"
    ),
    "不要段段收束、段段出金句，至少留一段只停在观察、动作或关系变化上。": (
        "不要段段收束、段段出金句，至少留一段只推进观察、情绪命名或关系变化。"
    ),
    "少用固定连接词去硬撑顺序，让转折长在动作、停顿和后果里。": (
        "少用固定连接词去硬撑顺序，让转折长在判断推进、情绪变化和现实落点里。"
    ),
    "结尾回到一个小动作、关系余波或现实阻力，不要祝福式收尾。": (
        "结尾回到一个明确结论、关系余波或具体动作，不要祝福式收尾，也不要另补小动作。"
    ),
    "大纲里的目标和段落职责都要能指向可观察动作，不要用“更好、更重要、更有价值”这类空转词充当推进。": (
        "大纲里的目标和段落职责都要能指向可验证的情绪价值、关系变化或现实落点，"
        "不要用“更好、更重要、更有价值”这类空转词充当推进。"
    ),
}

_DEFAULT_TRACKED_ARTICLE_RULES: dict[str, Any] = {
    "source": {
        "version": "embedded-default",
        "origin": "repo-default",
        "synced_at": None,
        "referenced_skills": [],
    },
    "strategy": {
        "problem_constraints": [
            "先把事情搞清楚，再把事情说清楚；不要急着把处境包装成标准答案。",
            "参考文章只负责提供赛道冲突和处境类型，不负责提供标题骨架、判断句和段落顺序。",
            "不要把“我适不适合”这类关于作者自我的噪音带进问题说明书，只保留和读者处境、冲突、动作有关的事实。",
            "不要直接回答大问题，先把要解释的处境钉成一个可观察现象。",
            "先写清哪里和预期不一致、哪里真正卡住，不要只给一个泛泛主题。",
        ],
        "problem_brief_steps": [
            "写前先把问题钉成一个可观察现象，不要直接回答大问题。",
            "先明确一处不一致：行为和预期、重要和紧急，或想说和没说出来。",
            "静默补齐对象、目标、冲突、约束和反馈入口这 5 个约束，缺一项就先补。",
        ],
        "divergence_axes": [
            "如果只是借到了观点，没有借到颗粒度和段落职责，就不算真正完成对标消化。",
        ],
        "divergence_checks": [
            "逐项检查标题骨架、开头入口、段落职责、转折节奏和结尾动作是否都已经换掉。",
            "凡是还顺着原文先讲什么、后讲什么的地方，先重排观察路径，再写句子。",
        ],
        "execution_checklist": [
            "问题说明书里是否已经把大词拆成现实接口、读者处境或主题推进，而不是继续停在抽象概念上。",
            "对象、目标和关键冲突是否已经写清，能不能限制后文推理空间。",
            "有没有现实反馈入口；如果没有，就不要急着把文章修成过度确定的结论。",
        ],
    },
    "outline": {
        "extra_instructions": [
            "大纲先解决“这件事到底是什么”，再考虑怎么把它包装得更好看。",
            "如果开头只是一个抽象判断，说明事情还没有被真正搞清楚，先退回到现实接口和读者处境。",
            "开头先钉一个可观察现象或断点，再展开，不要一上来先讲大道理。",
            "至少保留一处明确冲突：行为和预期不一致、想说和没说出来不一致，或重要和紧急不一致。",
        ],
    },
        "draft": {
        "extra_instructions": [
            "AI 味的高风险信号往往不是写得差，而是写得太光滑、太均匀、太像一次性完稿。",
            "不要为了显得深刻，把实操问题一路升维到更大的哲学判断；能停在眼前动作，就先停在眼前动作。",
            "改写不是伪装成人类，而是把作者自己真正想说的话从过度完美的模板里救出来。",
            "不要直接回答大问题，先让一个可观察现象承担解释压力。",
            "正文里至少保留一处还没完全解释完的观察，不要每段都收束得过于圆满。",
            "不要花太多篇幅包装一个已经说过的判断，优先继续推进处境和冲突。",
        ],
        "execution_protocol": [
            "开头先给一个现实抓手：动作、关系、物件、场景或当下卡点，不用大道理冷启动。",
            "不要写平台化的“钩子 + 痛点 + 承诺”三件套开头，直接进入要解释的处境。",
            "不要段段收束、段段出金句，至少留一段只推进观察、关系变化或现实落点。",
            "每次只保留一个最想强调的判断，其余判断埋回过程、情绪推进和现实落点里。",
            "结尾回到一个明确结论、关系余波或具体动作，不要祝福式收尾，也不要另补小动作。",
        ],
        "self_checklist": [
            "开头不要同时出现痛点放大、普遍判断和解决承诺这三件套。",
            "不要每段都单独敲一个结论段或金句段。",
            "“不是 X 是 Y”这类翻转全篇最多保留 1 处，开头和结尾最好不要出现。",
            "连续五句的长度和句式不要太整齐，至少打断一次匀速节拍。",
            "删掉最后一段祝福或喊话后，如果全文仍成立，就不要补回去。",
        ],
    },
    "diagnosis": {
        "signals": [
            "如果一篇稿子没有毛边、没有犹豫、没有任何作者自己也没想通的地方，它往往会更像 AI 成稿。",
            "如果文本一直在追求匀速排比、整齐翻转和段段收束，就要怀疑它是在展示模板，而不是展示观察。",
            "如果一篇稿子花很多篇幅包装一个已经说过的判断，它更像在做成稿，不像在推进问题。",
        ],
    },
    "assets": {
        "extra_instructions": [
            "标题组可以参考公式意识，但不要只套标题公式；每个标题都要对应正文的信息增量、情绪入口或现实损失。",
        ],
    },
    "publish_package": {
        "extra_instructions": [
            "编辑备注要像小型复盘：写清这篇稿子的核心主诉、已确认结论、已否决方向和保留经验。",
        ],
    },
}


def _deepcopy_default_rules() -> dict[str, Any]:
    return json.loads(json.dumps(_DEFAULT_TRACKED_ARTICLE_RULES, ensure_ascii=False))


def _clean_line(value: object) -> str:
    if value is None:
        return ""
    line = str(value).strip()
    return _LOCALIZED_RULE_REPLACEMENTS.get(line, line)


def _normalize_rule_lines(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        line = _clean_line(item)
        if line and line not in normalized:
            normalized.append(line)
    return normalized


def _overlay_rule_section(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    section: str,
    keys: tuple[str, ...],
) -> None:
    source_section = source.get(section)
    if not isinstance(source_section, dict):
        return
    target_section = target.setdefault(section, {})
    if not isinstance(target_section, dict):
        return
    for key in keys:
        lines = _normalize_rule_lines(source_section.get(key))
        if lines:
            target_section[key] = lines


def _normalize_rules(payload: object) -> dict[str, Any]:
    normalized = _deepcopy_default_rules()
    if not isinstance(payload, dict):
        return normalized

    source = payload.get("source")
    if isinstance(source, dict):
        normalized_source = normalized.setdefault("source", {})
        if isinstance(normalized_source, dict):
            for key in ("version", "origin", "synced_at"):
                value = _clean_line(source.get(key))
                if value:
                    normalized_source[key] = value
            referenced_skills = source.get("referenced_skills")
            if isinstance(referenced_skills, list):
                normalized_source["referenced_skills"] = _normalize_rule_lines(referenced_skills)

    _overlay_rule_section(
        normalized,
        payload,
        section="strategy",
        keys=("problem_constraints", "problem_brief_steps", "divergence_axes", "divergence_checks", "execution_checklist"),
    )
    _overlay_rule_section(
        normalized,
        payload,
        section="outline",
        keys=("extra_instructions",),
    )
    _overlay_rule_section(
        normalized,
        payload,
        section="draft",
        keys=("extra_instructions", "execution_protocol", "self_checklist"),
    )
    _overlay_rule_section(
        normalized,
        payload,
        section="diagnosis",
        keys=("signals",),
    )
    _overlay_rule_section(
        normalized,
        payload,
        section="assets",
        keys=("extra_instructions",),
    )
    _overlay_rule_section(
        normalized,
        payload,
        section="publish_package",
        keys=("extra_instructions",),
    )
    return normalized


@lru_cache(maxsize=1)
def load_dbskill_tracked_article_rules() -> dict[str, Any]:
    if not GENERATED_RULES_PATH.exists():
        return _deepcopy_default_rules()

    try:
        payload = json.loads(GENERATED_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _deepcopy_default_rules()
    return _normalize_rules(payload)


def get_dbskill_rule_lines(section: str, key: str) -> list[str]:
    section_payload = load_dbskill_tracked_article_rules().get(section)
    if not isinstance(section_payload, dict):
        return []
    return _normalize_rule_lines(section_payload.get(key))


def get_dbskill_source_version() -> str:
    source = load_dbskill_tracked_article_rules().get("source")
    if not isinstance(source, dict):
        return ""
    return _clean_line(source.get("version"))


def merge_unique_lines(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            line = _clean_line(item)
            if line and line not in merged:
                merged.append(line)
    return merged

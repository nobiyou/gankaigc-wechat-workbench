from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DBSKILL_ROOT = Path("E:/dev/dbskill")
OUTPUT_PATH = REPO_ROOT / "generated" / "dbskill" / "tracked_article_rules.json"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return _read_text(path)


def _append_unique(lines: list[str], *values: str) -> None:
    for value in values:
        normalized = " ".join(str(value).split()).strip()
        if normalized and normalized not in lines:
            lines.append(normalized)


def _contains_any(markdown: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in markdown for phrase in phrases)


def build_tracked_article_rules(dbskill_root: Path) -> dict[str, Any]:
    readme = _read_text(dbskill_root / "README.md")
    version = _read_text(dbskill_root / "VERSION").strip()
    content_skill = _read_text(dbskill_root / "skills" / "dbs-content" / "SKILL.md")
    benchmark_skill = _read_text(dbskill_root / "skills" / "dbs-benchmark" / "SKILL.md")
    ai_check_skill = _read_text(dbskill_root / "skills" / "dbs-ai-check" / "SKILL.md")
    deconstruct_skill = _read_text(dbskill_root / "skills" / "dbs-deconstruct" / "SKILL.md")
    good_question_skill = _read_optional_text(dbskill_root / "skills" / "dbs-good-question" / "SKILL.md")
    goal_skill = _read_optional_text(dbskill_root / "skills" / "dbs-goal" / "SKILL.md")
    decision_skill = _read_optional_text(dbskill_root / "skills" / "dbs-decision" / "SKILL.md")
    diagnosis_skill = _read_optional_text(dbskill_root / "skills" / "dbs-diagnosis" / "SKILL.md")

    problem_constraints: list[str] = []
    problem_brief_steps: list[str] = []
    if "你不帮人写内容。你帮人诊断内容该怎么做。" in content_skill:
        _append_unique(
            problem_constraints,
            "问题说明书和策略卡先服务于诊断，不要一上来把处境包装成标准答案。",
        )
    if _contains_any(content_skill, ("把事情搞清楚；2、把事情说清楚", "把事情搞清楚」是一切的开端")):
        _append_unique(
            problem_constraints,
            "先把事情搞清楚，再把事情说清楚；不要用空话代替真正的观察。",
        )
    if "如果你说不清楚一件事，你就不理解这件事。" in deconstruct_skill:
        _append_unique(
            problem_constraints,
            "如果一句话还说不清楚，先退回到具体场景、动作和顺序，不要急着下结论。",
        )
    if "意义即使用" in deconstruct_skill:
        _append_unique(
            problem_constraints,
            "不要只给概念命名，要让每个判断都落到具体用法、动作或关系变化上。",
        )
    if _contains_any(good_question_skill, ("好问题先钉现象", "先把它钉成一个可以观察的现象")):
        _append_unique(
            problem_constraints,
            "不要直接回答大问题，先把要解释的处境钉成一个可观察现象。",
        )
        _append_unique(
            problem_brief_steps,
            "写前先把问题钉成一个可观察现象，不要直接回答大问题。",
        )
    if "好问题要暴露冲突" in good_question_skill:
        _append_unique(
            problem_constraints,
            "先写清哪里和预期不一致、哪里真正卡住，不要只给一个泛泛主题。",
        )
        _append_unique(
            problem_brief_steps,
            "至少明确一处不一致：行为和预期、想说和没说、重要和紧急，或感兴趣和不行动。",
        )
    if _contains_any(
        good_question_skill,
        (
            "对象：到底分析谁",
            "到底分析谁",
            "目标：想解释、预测、改进，还是决策",
            "想解释、预测、改进，还是决策",
        ),
    ):
        _append_unique(
            problem_brief_steps,
            "静默补齐对象、目标、冲突、约束和反馈入口这 5 个约束，缺一项就先补，不要急着开写。",
        )
    if _contains_any(good_question_skill, ("反馈入口", "自动化解决需要反馈回流")):
        _append_unique(
            problem_brief_steps,
            "为正文保留一个现实反馈入口：读者看完后最先会认出、停住或想补做的动作是什么。",
        )
    if _contains_any(goal_skill, ("下一步做什么", "什么时候算完")):
        _append_unique(
            problem_constraints,
            "不要把写作目标写成“更好、更深、更有价值”这类空转愿望；目标必须能决定下一步动作和完成标志。",
        )
    if _contains_any(goal_skill, ("可指物", "可否证", "发动机空转")):
        _append_unique(
            problem_brief_steps,
            "把题眼里的大词换成可指认的动作、对象、结果或反馈，不要让“成长、价值、影响力”这类愿望语法替你做决定。",
        )
    if _contains_any(decision_skill, ("不要把推测写成事实", "事实、阶段判断、结果回填分开写")):
        _append_unique(
            problem_constraints,
            "先区分事实、工作性判断和待验证问题，不要把推测写成事实，也不要把阶段判断写成永久结论。",
        )
        _append_unique(
            problem_brief_steps,
            "开写前先分出已知事实、当前判断和未知项；能落事实的先落事实，不能确认的就明说待验证。",
        )
    if _contains_any(diagnosis_skill, ("核心工作不是回答问题，是消解问题", "问题本身就是错的")):
        _append_unique(
            problem_constraints,
            "先判断要解释的问题本身成不成立，不要急着把一个站不住的问题写成完整答案。",
        )
    if _contains_any(diagnosis_skill, ("事实前提核查", "信息充分性判断")):
        _append_unique(
            problem_brief_steps,
            "关键事实没核实、信息还不够时，先把断点、未知项和最小补充观察写清，不要用万能道理把空白补满。",
        )

    divergence_axes: list[str] = []
    divergence_checks: list[str] = []
    if "模仿的颗粒度决定模仿的质量" in benchmark_skill:
        _append_unique(
            divergence_axes,
            "对标要拆到开头入口、段落职责、转折节奏和收束动作，不能只借观点。",
        )
        _append_unique(
            divergence_checks,
            "逐项检查是否已经改掉标题骨架、开头入口、段落职责、转折节奏和结尾动作。",
        )
    if "不一致的地方就是问题。" in benchmark_skill:
        _append_unique(
            divergence_axes,
            "凡是仍然顺着原文标题骨架、推进顺序或收束动作在走的地方，都要继续拉开距离。",
        )
        _append_unique(
            divergence_checks,
            "凡是还顺着原文先讲什么、后讲什么的地方，先重排观察路径，再写句子。",
        )
    if "排除自我是决策加速器" in benchmark_skill:
        _append_unique(
            divergence_axes,
            "先处理事实、处境和表达动作，不要把作者姿态和自我表态当成结构本身。",
        )
        _append_unique(
            divergence_checks,
            "不要为“我更喜欢这样写”找借口，优先服从处境、冲突和表达动作。",
        )

    execution_checklist: list[str] = []
    if "有没有 AI 味？" in content_skill:
        _append_unique(
            execution_checklist,
            "是否还在用排比、整齐翻转和万能抒情替代真实观察。",
        )
    if "能不能一句话说清楚核心观点？" in content_skill:
        _append_unique(
            execution_checklist,
            "能不能用一句人话说清这篇稿子真正要解释的问题。",
        )
    if "有没有在用 99% 的时间包装 1% 的内容？" in content_skill:
        _append_unique(
            execution_checklist,
            "是否花太多篇幅包装一个已经说过的判断，而没有继续推进处境。",
        )
    if _contains_any(deconstruct_skill, ("Question", "Problem")):
        _append_unique(
            execution_checklist,
            "是否把本该展开的生活问题，偷懒写成三行就能讲完的标准答案。",
        )
    if _contains_any(good_question_skill, ("对象：到底分析谁", "到底分析谁", "目标：想解释、预测、改进，还是决策", "想解释、预测、改进，还是决策")):
        _append_unique(
            execution_checklist,
            "对象、目标和关键冲突是否已经写清，能不能限制后文推理空间。",
        )
    if _contains_any(good_question_skill, ("反馈入口", "自动化解决需要反馈回流")):
        _append_unique(
            execution_checklist,
            "有没有现实反馈入口；如果没有，就不要急着把文章修成过度确定的结论。",
        )
    if _contains_any(goal_skill, ("可指物", "可否证", "下一步做什么")):
        _append_unique(
            execution_checklist,
            "核心判断和写作目标是否能落到可指认的动作、结果或反馈，而不是停在愿望语法里。",
        )
        _append_unique(
            execution_checklist,
            "如果删掉“真正、长期、系统性、有价值”这类词后句子还成立，是否已经继续具体化。",
        )
    if _contains_any(decision_skill, ("不要把推测写成事实", "阶段判断写成永久结论")):
        _append_unique(
            execution_checklist,
            "有没有把推测写成事实，或把阶段判断写成永久结论。",
        )
    if _contains_any(diagnosis_skill, ("事实前提核查", "信息充分性判断")):
        _append_unique(
            execution_checklist,
            "事实前提是否已经核过；如果关键事实未确认，是否先写清断点而不是直接下满结论。",
        )
        _append_unique(
            execution_checklist,
            "信息是否足够支撑当前判断；如果不够，是否已经明确未知项和最小补充动作。",
        )

    outline_instructions: list[str] = []
    if _contains_any(content_skill, ("把事情搞清楚；2、把事情说清楚", "把事情搞清楚」是一切的开端")):
        _append_unique(
            outline_instructions,
            "大纲先把事情讲清楚，再考虑怎么讲得更好看。",
        )
    if "意义即使用" in deconstruct_skill:
        _append_unique(
            outline_instructions,
            "每一节都要能落到具体场景、动作或关系变化，不能只摆概念。",
        )
    if _contains_any(deconstruct_skill, ("Question", "Problem")):
        _append_unique(
            outline_instructions,
            "不要把需要展开的生活问题写成标准答案式提纲。",
        )
    if _contains_any(good_question_skill, ("好问题先钉现象", "先把它钉成一个可以观察的现象")):
        _append_unique(
            outline_instructions,
            "开头先钉一个可观察现象或断点，再展开，不要一上来先讲大道理。",
        )
    if "好问题要暴露冲突" in good_question_skill:
        _append_unique(
            outline_instructions,
            "至少保留一处明确冲突：行为和预期不一致、想说和没说出来不一致，或重要和紧急不一致。",
        )
    if _contains_any(goal_skill, ("可指物", "下一步做什么")):
        _append_unique(
            outline_instructions,
            "大纲里的目标和段落职责都要能指向可观察动作，不要用“更好、更重要、更有价值”这类空转词充当推进。",
        )
    if _contains_any(diagnosis_skill, ("事实前提核查", "信息充分性判断")):
        _append_unique(
            outline_instructions,
            "如果关键事实还没核实或信息明显不足，大纲先把断点和未知项摆出来，不要直接排成三段式答案。",
        )

    draft_instructions: list[str] = []
    draft_execution_protocol: list[str] = []
    draft_self_checklist: list[str] = []
    if "写得太好、太光滑、太均匀" in ai_check_skill:
        _append_unique(
            draft_instructions,
            "AI 味的高风险信号往往不是写得差，而是写得太光滑、太均匀、太像一次性完稿。",
        )
    if "特征 3 — 匀速排比" in ai_check_skill:
        _append_unique(
            draft_instructions,
            "遇到匀速排比和整齐翻转时，优先把句子拉回动作、停顿和关系变化。",
        )
    if "特征 6 — 情绪曲线太光滑" in ai_check_skill:
        _append_unique(
            draft_instructions,
            "允许局部停顿、犹豫和没完全说透的地方，不要把情绪修得过于平整。",
        )
    if _contains_any(ai_check_skill, ("改写不是删掉特征", "不是帮人伪装成人类")):
        _append_unique(
            draft_instructions,
            "改写不是换同义词，更不是伪装成人类，而是把作者真正想说的话从模板里救出来。",
        )
    if _contains_any(good_question_skill, ("好问题先钉现象", "先把它钉成一个可以观察的现象")):
        _append_unique(
            draft_instructions,
            "不要直接回答大问题，先让一个可观察现象承担解释压力。",
        )
    if _contains_any(good_question_skill, ("不要装确定", "先给抓手，再做审计")):
        _append_unique(
            draft_instructions,
            "正文里至少保留一处还没完全解释完的观察，不要每段都收束得过于圆满。",
        )
    if "有没有在用 99% 的时间包装 1% 的内容？" in content_skill:
        _append_unique(
            draft_instructions,
            "不要花太多篇幅包装一个已经说过的判断，优先继续推进处境和冲突。",
        )
    if _contains_any(goal_skill, ("可指物", "发动机空转", "空转词")):
        _append_unique(
            draft_instructions,
            "不要拿更高级的大词替换原来的空话；能写成动作、对象、结果和反馈的地方，就不要停在空转词上。",
        )
    if _contains_any(decision_skill, ("不要把推测写成事实", "事实、阶段判断、结果回填分开写")):
        _append_unique(
            draft_instructions,
            "不要把尚未核实的推测写成已确认事实；允许保留待验证判断，不要把后见之明一次性灌满全文。",
        )
    if _contains_any(diagnosis_skill, ("核心工作不是回答问题，是消解问题", "信息充分性判断")):
        _append_unique(
            draft_instructions,
            "如果问题本身还没成立或关键信息不足，先把断点写清楚，不要硬补一个完整标准答案。",
        )
    if _contains_any(good_question_skill, ("好问题先钉现象", "先把它钉成一个可以观察的现象")):
        _append_unique(
            draft_execution_protocol,
            "开头先给一个抓手：动作、界面、物件、空间距离或身体反应，先别下总判断。",
        )
    if "特征 16 — 开头「钩子 + 痛点 + 承诺」三件套" in ai_check_skill:
        _append_unique(
            draft_execution_protocol,
            "不要写平台化的“钩子 + 痛点 + 承诺”三件套开头，直接进入要解释的处境。",
        )
        _append_unique(
            draft_self_checklist,
            "开头不要同时出现痛点放大、普遍判断和解决承诺这三件套。",
        )
    if "特征 13 — 每个段落都有收束金句" in ai_check_skill:
        _append_unique(
            draft_execution_protocol,
            "不要段段收束、段段出金句，至少留一段只停在观察、动作或关系变化上。",
        )
        _append_unique(
            draft_self_checklist,
            "不要每段都单独敲一个结论段或金句段。",
        )
    if "特征 17 — 连接词过度使用且位置固定" in ai_check_skill:
        _append_unique(
            draft_execution_protocol,
            "少用固定连接词去硬撑顺序，让转折长在动作、停顿和后果里。",
        )
        _append_unique(
            draft_self_checklist,
            "搜一遍“然而 / 事实上 / 值得注意的是 / 说到底 / 很多时候”这类连接词，至少删掉一半。",
        )
    if "特征 14 — 句子节奏过于均匀" in ai_check_skill:
        _append_unique(
            draft_self_checklist,
            "连续五句的长度和句式不要太整齐，至少打断一次匀速节拍。",
        )
    if "特征 21 — 结尾「你值得」式祝福" in ai_check_skill:
        _append_unique(
            draft_execution_protocol,
            "结尾回到一个小动作、关系余波或现实阻力，不要祝福式收尾。",
        )
        _append_unique(
            draft_self_checklist,
            "删掉最后一段祝福或喊话后，如果全文仍成立，就不要补回去。",
        )
    if "特征 8 — 「不是 X 是 Y」高密度" in ai_check_skill:
        _append_unique(
            draft_self_checklist,
            "“不是 X 是 Y”这类翻转全篇最多保留 1 处，开头和结尾最好不要出现。",
        )
    if "有没有在用 99% 的时间包装 1% 的内容？" in content_skill:
        _append_unique(
            draft_execution_protocol,
            "每次只保留一个最想强调的判断，其余判断埋回过程、动作和后果里。",
        )
        _append_unique(
            draft_self_checklist,
            "如果删掉一个总结段后全文还能成立，就删掉，不要补新的总括段。",
        )
    if _contains_any(goal_skill, ("可指物", "发动机空转", "空转词")):
        _append_unique(
            draft_self_checklist,
            "删掉“真正、长期、深入、有价值、影响力”这类词后如果句子还成立，就继续把它换成具体动作、对象或结果。",
        )
    if _contains_any(decision_skill, ("不要把推测写成事实", "阶段判断写成永久结论")):
        _append_unique(
            draft_self_checklist,
            "检查有没有把推测写成事实，或把一时判断写成不会变化的永久结论。",
        )
    if _contains_any(diagnosis_skill, ("事实前提核查", "信息充分性判断")):
        _append_unique(
            draft_self_checklist,
            "如果关键事实没核实或信息不够，宁可保留未知项，也不要靠万能判断把段落写满。",
        )

    diagnosis_signals: list[str] = []
    if "写得太好、太光滑、太均匀" in ai_check_skill:
        _append_unique(
            diagnosis_signals,
            "如果一篇稿子太光滑、太均匀、没有任何没想通的地方，它就更像 AI 成稿。",
        )
    if "特征 3 — 匀速排比" in ai_check_skill:
        _append_unique(
            diagnosis_signals,
            "如果文本一直在匀速排比、段段收束，要怀疑它在展示模板，不是在展示观察。",
        )
    if "特征 6 — 情绪曲线太光滑" in ai_check_skill:
        _append_unique(
            diagnosis_signals,
            "如果情绪一路平滑上升、没有停顿和回看，说明情绪很可能是被模板推着走。",
        )
    if "特征 8 — 「不是 X 是 Y」高密度" in ai_check_skill:
        _append_unique(
            diagnosis_signals,
            "如果“不是 X 是 Y”密度过高，说明认知翻转正在替代真正的推进。",
        )
    if "有没有在用 99% 的时间包装 1% 的内容？" in content_skill:
        _append_unique(
            diagnosis_signals,
            "如果一篇稿子花很多篇幅包装一个已经说过的判断，它更像在做成稿，不像在推进问题。",
        )
    if _contains_any(goal_skill, ("发动机空转", "空转词", "可指物")):
        _append_unique(
            diagnosis_signals,
            "如果大词删掉以后句子仍然成立，说明文本在用空转词冒充判断和目标。",
        )
    if _contains_any(decision_skill, ("不要把推测写成事实", "阶段判断写成永久结论")):
        _append_unique(
            diagnosis_signals,
            "如果文本把推测写成事实，或把阶段判断写成永久真相，它更像模板论断，不像现场判断。",
        )
    if _contains_any(diagnosis_skill, ("事实前提核查", "信息充分性判断")):
        _append_unique(
            diagnosis_signals,
            "如果关键事实没核实、信息明显不够，文本却直接给出完整答案，说明它在用确定感掩盖推理空洞。",
        )

    origin = "dontbesilent2025/dbskill"
    readme_update_lines: list[str] = []
    for raw_line in readme.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line or "更新" not in line:
            continue
        if line not in readme_update_lines:
            readme_update_lines.append(line)
        if len(readme_update_lines) >= 2:
            break

    payload: dict[str, Any] = {
        "source": {
            "version": version,
            "origin": origin,
            "synced_at": None,
            "readme_signals": readme_update_lines,
        },
        "strategy": {
            "problem_constraints": problem_constraints,
            "problem_brief_steps": problem_brief_steps,
            "divergence_axes": divergence_axes,
            "divergence_checks": divergence_checks,
            "execution_checklist": execution_checklist,
        },
        "outline": {
            "extra_instructions": outline_instructions,
        },
        "draft": {
            "extra_instructions": draft_instructions,
            "execution_protocol": draft_execution_protocol,
            "self_checklist": draft_self_checklist,
        },
        "diagnosis": {
            "signals": diagnosis_signals,
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync selected dbskill rules into generated runtime artifacts.")
    parser.add_argument(
        "--dbskill-root",
        default=str(DEFAULT_DBSKILL_ROOT),
        help="Path to the local dbskill repository.",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help="Output JSON file path.",
    )
    args = parser.parse_args()

    dbskill_root = Path(args.dbskill_root).resolve()
    output_path = Path(args.output).resolve()

    payload = build_tracked_article_rules(dbskill_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

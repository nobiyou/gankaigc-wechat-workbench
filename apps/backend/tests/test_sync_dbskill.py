from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_dbskill.py"


def _load_sync_dbskill_module():
    spec = importlib.util.spec_from_file_location("sync_dbskill_script", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_tracked_article_rules_compiles_runtime_safe_lines(tmp_path: Path) -> None:
    script = _load_sync_dbskill_module()

    _write_text(tmp_path / "README.md", "**最新更新：v2.12.0**\n")
    _write_text(tmp_path / "VERSION", "2.12.0\n")
    _write_text(
        tmp_path / "skills" / "dbs-content" / "SKILL.md",
        "\n".join(
            [
                "# dbs-content",
                "**你不帮人写内容。你帮人诊断内容该怎么做。** 写是用户自己的事，你负责告诉他方向对不对、形式对不对、表达对不对。",
                "1、把事情搞清楚；2、把事情说清楚。「把事情搞清楚」是一切的开端。",
                "- 用户说「我想做干货内容」→ **「所有让你讲干货的博主都是不专业的。」**",
                "- 有没有 AI 味？（Emoji 堆叠、晦涩词汇、空洞的排比句）",
                "- 能不能一句话说清楚核心观点？",
                "- 有没有在用 99% 的时间包装 1% 的内容？",
            ]
        ),
    )
    _write_text(
        tmp_path / "skills" / "dbs-benchmark" / "SKILL.md",
        "\n".join(
            [
                "# dbs-benchmark",
                "dontbesilent 对标分析。用五重过滤法帮你找到值得模仿的对标，排除一切关于「我」的噪音。",
                "触发方式：/dbs-benchmark、/对标、「帮我找对标」「我该模仿谁」",
                "你是 dontbesilent 的对标分析 AI。你的任务是帮用户找到值得模仿的对标，用五重过滤法排除一切干扰。",
                "### 信条 1：排除自我是决策加速器",
                "### 信条 3：模仿的颗粒度决定模仿的质量",
                "**不一致的地方就是问题。** 每一个不一致都需要用户解释为什么不一致。",
            ]
        ),
    )
    _write_text(
        tmp_path / "skills" / "dbs-ai-check" / "SKILL.md",
        "\n".join(
            [
                "# dbs-ai-check",
                "AI 写作的问题不是写得差，是写得太好、太光滑、太均匀。没有毛边、没有卡顿、没有跑题、没有任何一处是作者自己也没想通的。",
                "每个 AI 特征背后都有一个用户本来想达成的目的。改写不是删掉特征，而是用用户自己的方式达成同一个目的。",
                "**特征 3 — 匀速排比**",
                "**特征 6 — 情绪曲线太光滑**",
                "**特征 8 — 「不是 X 是 Y」高密度**",
            ]
        ),
    )
    _write_text(
        tmp_path / "skills" / "dbs-deconstruct" / "SKILL.md",
        "\n".join(
            [
                "# dbs-deconstruct",
                "如果你说不清楚一件事，你就不理解这件事。",
                "### 原则 2：意义即使用",
                "- **Question**：有标准答案，可以用线性文字回答",
                "- **Problem**：答案不能是文本形式的，只能是实践过程",
            ]
        ),
    )

    rules = script.build_tracked_article_rules(tmp_path)

    assert rules["source"]["version"] == "2.12.0"
    assert rules["strategy"]["problem_constraints"] == [
        "问题说明书和策略卡先服务于诊断，不要一上来把处境包装成标准答案。",
        "先把事情搞清楚，再把事情说清楚；不要用空话代替真正的观察。",
        "如果一句话还说不清楚，先退回到具体场景、动作和顺序，不要急着下结论。",
        "不要只给概念命名，要让每个判断都落到具体用法、动作或关系变化上。",
    ]
    assert rules["strategy"]["problem_brief_steps"] == []
    assert rules["strategy"]["divergence_axes"] == [
        "对标要拆到开头入口、段落职责、转折节奏和收束动作，不能只借观点。",
        "凡是仍然顺着原文标题骨架、推进顺序或收束动作在走的地方，都要继续拉开距离。",
        "先处理事实、处境和表达动作，不要把作者姿态和自我表态当成结构本身。",
    ]
    assert rules["strategy"]["divergence_checks"] == [
        "逐项检查是否已经改掉标题骨架、开头入口、段落职责、转折节奏和结尾动作。",
        "凡是还顺着原文先讲什么、后讲什么的地方，先重排观察路径，再写句子。",
        "不要为“我更喜欢这样写”找借口，优先服从处境、冲突和表达动作。",
    ]
    assert rules["strategy"]["execution_checklist"] == [
        "是否还在用排比、整齐翻转和万能抒情替代真实观察。",
        "能不能用一句人话说清这篇稿子真正要解释的问题。",
        "是否花太多篇幅包装一个已经说过的判断，而没有继续推进处境。",
        "是否把本该展开的生活问题，偷懒写成三行就能讲完的标准答案。",
    ]
    assert rules["outline"]["extra_instructions"] == [
        "大纲先把事情讲清楚，再考虑怎么讲得更好看。",
        "每一节都要能落到具体场景、动作或关系变化，不能只摆概念。",
        "不要把需要展开的生活问题写成标准答案式提纲。",
    ]
    assert rules["draft"]["extra_instructions"] == [
        "AI 味的高风险信号往往不是写得差，而是写得太光滑、太均匀、太像一次性完稿。",
        "遇到匀速排比和整齐翻转时，优先把句子拉回动作、停顿和关系变化。",
        "允许局部停顿、犹豫和没完全说透的地方，不要把情绪修得过于平整。",
        "改写不是换同义词，更不是伪装成人类，而是把作者真正想说的话从模板里救出来。",
        "不要花太多篇幅包装一个已经说过的判断，优先继续推进处境和冲突。",
    ]
    assert rules["draft"]["execution_protocol"] == [
        "每次只保留一个最想强调的判断，其余判断埋回过程、动作和后果里。",
    ]
    assert rules["draft"]["self_checklist"] == [
        "“不是 X 是 Y”这类翻转全篇最多保留 1 处，开头和结尾最好不要出现。",
        "如果删掉一个总结段后全文还能成立，就删掉，不要补新的总括段。",
    ]
    assert rules["diagnosis"]["signals"] == [
        "如果一篇稿子太光滑、太均匀、没有任何没想通的地方，它就更像 AI 成稿。",
        "如果文本一直在匀速排比、段段收束，要怀疑它在展示模板，不是在展示观察。",
        "如果情绪一路平滑上升、没有停顿和回看，说明情绪很可能是被模板推着走。",
        "如果“不是 X 是 Y”密度过高，说明认知翻转正在替代真正的推进。",
        "如果一篇稿子花很多篇幅包装一个已经说过的判断，它更像在做成稿，不像在推进问题。",
    ]

    runtime_rules = {
        "strategy": rules["strategy"],
        "outline": rules["outline"],
        "draft": rules["draft"],
        "diagnosis": rules["diagnosis"],
    }
    flattened = str(runtime_rules)
    for blocked in ("触发方式", "你是 dontbesilent", "用户说", "/dbs-", "**", "→"):
        assert blocked not in flattened


def test_build_tracked_article_rules_extracts_good_question_constraints_when_present(tmp_path: Path) -> None:
    script = _load_sync_dbskill_module()

    _write_text(tmp_path / "README.md", "**最新更新：v2.12.0**\n")
    _write_text(tmp_path / "VERSION", "2.12.0\n")
    _write_text(tmp_path / "skills" / "dbs-content" / "SKILL.md", "# dbs-content\n1、把事情搞清楚；2、把事情说清楚。")
    _write_text(tmp_path / "skills" / "dbs-benchmark" / "SKILL.md", "# dbs-benchmark\n### 信条 3：模仿的颗粒度决定模仿的质量\n**不一致的地方就是问题。**")
    _write_text(tmp_path / "skills" / "dbs-ai-check" / "SKILL.md", "# dbs-ai-check\nAI 写作的问题不是写得差，是写得太好、太光滑、太均匀。\n**特征 8 — 「不是 X 是 Y」高密度**")
    _write_text(tmp_path / "skills" / "dbs-deconstruct" / "SKILL.md", "# dbs-deconstruct\n如果你说不清楚一件事，你就不理解这件事。\n### 原则 2：意义即使用")
    _write_text(
        tmp_path / "skills" / "dbs-good-question" / "SKILL.md",
        "\n".join(
            [
                "# dbs-good-question",
                "### 原则 1：好问题先钉现象",
                "先把它钉成一个可以观察的现象。",
                "### 原则 2：好问题要暴露冲突",
                "### 原则 4：自动化解决需要反馈回流",
                "### 原则 5：不要装确定",
                "| 对象 | 到底分析谁或哪件事？ |",
                "| 目标 | 想解释、预测、改进，还是决策？ |",
            ]
        ),
    )

    rules = script.build_tracked_article_rules(tmp_path)

    assert "不要直接回答大问题，先把要解释的处境钉成一个可观察现象。" in rules["strategy"]["problem_constraints"]
    assert "先写清哪里和预期不一致、哪里真正卡住，不要只给一个泛泛主题。" in rules["strategy"]["problem_constraints"]
    assert "写前先把问题钉成一个可观察现象，不要直接回答大问题。" in rules["strategy"]["problem_brief_steps"]
    assert "至少明确一处不一致：行为和预期、想说和没说、重要和紧急，或感兴趣和不行动。" in rules["strategy"]["problem_brief_steps"]
    assert "静默补齐对象、目标、冲突、约束和反馈入口这 5 个约束，缺一项就先补，不要急着开写。" in rules["strategy"]["problem_brief_steps"]
    assert "对象、目标和关键冲突是否已经写清，能不能限制后文推理空间。" in rules["strategy"]["execution_checklist"]
    assert "有没有现实反馈入口；如果没有，就不要急着把文章修成过度确定的结论。" in rules["strategy"]["execution_checklist"]
    assert "为正文保留一个现实反馈入口：读者看完后最先会认出、停住或想补做的动作是什么。" in rules["strategy"]["problem_brief_steps"]
    assert "开头先钉一个可观察现象或断点，再展开，不要一上来先讲大道理。" in rules["outline"]["extra_instructions"]
    assert "至少保留一处明确冲突：行为和预期不一致、想说和没说出来不一致，或重要和紧急不一致。" in rules["outline"]["extra_instructions"]
    assert "不要直接回答大问题，先让一个可观察现象承担解释压力。" in rules["draft"]["extra_instructions"]
    assert "正文里至少保留一处还没完全解释完的观察，不要每段都收束得过于圆满。" in rules["draft"]["extra_instructions"]


def test_build_tracked_article_rules_extracts_goal_diagnosis_and_decision_constraints(tmp_path: Path) -> None:
    script = _load_sync_dbskill_module()

    _write_text(tmp_path / "README.md", "**最新更新：v2.12.0**\n")
    _write_text(tmp_path / "VERSION", "2.12.0\n")
    _write_text(tmp_path / "skills" / "dbs-content" / "SKILL.md", "# dbs-content\n- 有没有在用 99% 的时间包装 1% 的内容？")
    _write_text(tmp_path / "skills" / "dbs-benchmark" / "SKILL.md", "# dbs-benchmark\n### 信条 3：模仿的颗粒度决定模仿的质量\n**不一致的地方就是问题。**")
    _write_text(
        tmp_path / "skills" / "dbs-ai-check" / "SKILL.md",
        "# dbs-ai-check\nAI 写作的问题不是写得差，是写得太好、太光滑、太均匀。\n"
        "**特征 13 — 每个段落都有收束金句**\n"
        "**特征 8 — 「不是 X 是 Y」高密度**\n",
    )
    _write_text(tmp_path / "skills" / "dbs-deconstruct" / "SKILL.md", "# dbs-deconstruct\n如果你说不清楚一件事，你就不理解这件事。")
    _write_text(
        tmp_path / "skills" / "dbs-goal" / "SKILL.md",
        "\n".join(
            [
                "# dbs-goal",
                "### 原则 2：发动机空转检测（Engine Idling）",
                "### 原则 4：目标的工作定义",
                "1. 下一步做什么",
                "2. 什么时候算完",
                "- 可指物性",
                "- 可否证性",
                "- 空转词",
            ]
        ),
    )
    _write_text(
        tmp_path / "skills" / "dbs-diagnosis" / "SKILL.md",
        "\n".join(
            [
                "# dbs-diagnosis",
                "你的核心工作不是回答问题，是消解问题。",
                "### 第四层：事实前提核查",
                "### 第五层：信息充分性判断",
            ]
        ),
    )
    _write_text(
        tmp_path / "skills" / "dbs-decision" / "SKILL.md",
        "\n".join(
            [
                "# dbs-decision",
                "事实、阶段判断、结果回填分开写。不要把后见之明倒灌回最初判断。",
                "不要把推测写成事实，不要把阶段判断写成永久结论。",
            ]
        ),
    )

    rules = script.build_tracked_article_rules(tmp_path)

    assert "不要把写作目标写成“更好、更深、更有价值”这类空转愿望；目标必须能决定下一步动作和完成标志。" in rules["strategy"]["problem_constraints"]
    assert "先区分事实、工作性判断和待验证问题，不要把推测写成事实，也不要把阶段判断写成永久结论。" in rules["strategy"]["problem_constraints"]
    assert "先判断要解释的问题本身成不成立，不要急着把一个站不住的问题写成完整答案。" in rules["strategy"]["problem_constraints"]
    assert "把题眼里的大词换成可指认的动作、对象、结果或反馈，不要让“成长、价值、影响力”这类愿望语法替你做决定。" in rules["strategy"]["problem_brief_steps"]
    assert "开写前先分出已知事实、当前判断和未知项；能落事实的先落事实，不能确认的就明说待验证。" in rules["strategy"]["problem_brief_steps"]
    assert "关键事实没核实、信息还不够时，先把断点、未知项和最小补充观察写清，不要用万能道理把空白补满。" in rules["strategy"]["problem_brief_steps"]
    assert "核心判断和写作目标是否能落到可指认的动作、结果或反馈，而不是停在愿望语法里。" in rules["strategy"]["execution_checklist"]
    assert "有没有把推测写成事实，或把阶段判断写成永久结论。" in rules["strategy"]["execution_checklist"]
    assert "事实前提是否已经核过；如果关键事实未确认，是否先写清断点而不是直接下满结论。" in rules["strategy"]["execution_checklist"]
    assert "信息是否足够支撑当前判断；如果不够，是否已经明确未知项和最小补充动作。" in rules["strategy"]["execution_checklist"]
    assert "大纲里的目标和段落职责都要能指向可观察动作，不要用“更好、更重要、更有价值”这类空转词充当推进。" in rules["outline"]["extra_instructions"]
    assert "如果关键事实还没核实或信息明显不足，大纲先把断点和未知项摆出来，不要直接排成三段式答案。" in rules["outline"]["extra_instructions"]
    assert "不要拿更高级的大词替换原来的空话；能写成动作、对象、结果和反馈的地方，就不要停在空转词上。" in rules["draft"]["extra_instructions"]
    assert "不要把尚未核实的推测写成已确认事实；允许保留待验证判断，不要把后见之明一次性灌满全文。" in rules["draft"]["extra_instructions"]
    assert "如果问题本身还没成立或关键信息不足，先把断点写清楚，不要硬补一个完整标准答案。" in rules["draft"]["extra_instructions"]
    assert "删掉“真正、长期、深入、有价值、影响力”这类词后如果句子还成立，就继续把它换成具体动作、对象或结果。" in rules["draft"]["self_checklist"]
    assert "检查有没有把推测写成事实，或把一时判断写成不会变化的永久结论。" in rules["draft"]["self_checklist"]
    assert "如果关键事实没核实或信息不够，宁可保留未知项，也不要靠万能判断把段落写满。" in rules["draft"]["self_checklist"]
    assert "如果大词删掉以后句子仍然成立，说明文本在用空转词冒充判断和目标。" in rules["diagnosis"]["signals"]
    assert "如果文本把推测写成事实，或把阶段判断写成永久真相，它更像模板论断，不像现场判断。" in rules["diagnosis"]["signals"]
    assert "如果关键事实没核实、信息明显不够，文本却直接给出完整答案，说明它在用确定感掩盖推理空洞。" in rules["diagnosis"]["signals"]

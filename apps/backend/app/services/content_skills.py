from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentSkill:
    key: str
    label: str
    stages: tuple[str, ...]
    instructions_by_stage: dict[str, str]

    def instructions_for(self, stage: str) -> str:
        normalized_stage = stage.strip()
        if normalized_stage not in self.stages:
            return ""
        return self.instructions_by_stage.get(normalized_stage, "")


WECHAT_PLATFORM_VALUE_SKILL = ContentSkill(
    key="wechat_platform_value",
    label="公众号平台价值守门",
    stages=("topic", "outline", "draft", "assets", "publish_package"),
    instructions_by_stage={
        "topic": (
            "平台鼓励具有丰富信息含量、信息增量或情绪价值的内容。"
            "不管采用哪种风格，都必须明确给读者一层情绪价值：被看见、被安放、被允许、被提醒或被轻轻推动。"
            "选题不能只靠反差标题、情绪词堆叠、热点蹭词或泛成长口号成立。"
            "标题和切入角度必须说明这篇稿子新增了什么观察、处境拆解、现实机制或情绪承接。"
            "不要把生活场景作为默认入口，优先用现实接口、反常识判断、情绪命名或直接处境打开。"
            "不要生产疑似投机的低创作度内容。"
        ),
        "outline": (
            "平台鼓励具有丰富信息含量、信息增量或情绪价值的内容。"
            "大纲必须规划清楚每一段给读者新增什么：新观察、具体处境、原因机制、情绪承接、行动落点或现实提醒。"
            "原则上不规划空场景段，先规划现实承压点和情绪推进：哪件事先出代价、哪里被反复往后放、后面又留下什么影响。"
            "需要例证时优先保留一句事实、一个后果，或 1 到 2 个有判断功能的现实细节，不展开整段环境、动作、物件和氛围描写。"
            "不要把大纲写成标题党承诺后的空泛三段式、情绪反复、概念换皮或低创作度拼贴。"
            "如果某段只能复述主题情绪，没有信息增量或情绪价值，先删掉或改成具体推进。"
        ),
        "draft": (
            "平台鼓励具有丰富信息含量、信息增量或情绪价值的内容。"
            "正文每个主要段落都要承担新的内容价值：补充事实细节、拆开原因机制、命名真实情绪或给出可执行落点。"
            "不管风格多直接或多克制，正文都要让读者获得情绪价值，至少完成一次被理解、被松绑、被提醒或被推动。"
            "不要只做低创作度改写：换标题、换近义词、堆情绪、套热门句式、拼接金句或把同一个判断反复说。"
            "正文默认不用整段场景描写，不用生活场景冷启动，不连续写动作、环境、物件或氛围。"
            "需要例证时优先保留一句事实、一个后果，或 1 到 2 个有情绪功能的现实细节，并立刻接上情绪命名、矛盾拆解、现实机制或行动答案。"
            "例证不要单独长篇成段，不写只负责摆拍的“手机亮一下”“电梯门开了”这类空动作残留。"
            "输出前静默检查：如果文章删掉标题后只剩泛情绪和通用道理，就重写中段，补足信息增量或情绪价值。"
        ),
        "assets": (
            "标题备选、封面文案和分发导语要准确呈现正文的信息增量或情绪价值。"
            "外层文案要让读者马上知道自己会被理解、被提醒或获得一个现实出口。"
            "不要包装成夸张反差、蹭热点、低创作度标题党或只剩情绪刺激的导语。"
        ),
        "publish_package": (
            "发布摘要和编辑备注必须点明这篇稿子的核心信息增量或情绪价值。"
            "编辑备注要说明这篇稿子提供的情绪承接是什么，不能只复述题材、场景或标题。"
            "不要把发布包写成泛泛推荐、情绪口号或低创作度流量话术。"
        ),
    },
)


DIRECT_ANSWER_SCENE_BUDGET_SKILL = ContentSkill(
    key="direct_answer_scene_budget",
    label="直接表达与场景预算",
    stages=("topic", "outline", "draft", "assets", "publish_package"),
    instructions_by_stage={
        "topic": (
            "表达要直接，不要含蓄绕弯。"
            "标题和切入角度先给问题、判断、现实接口或答案入口，不要用场景氛围包装选题。"
        ),
        "outline": (
            "大纲默认不规划整段场景描述。"
            "单段优先写问题、判断、原因、行动或情绪承接。"
            "如需例证，优先写一句事实、一个后果，或 1 到 2 个有判断功能的现实细节，不展开生活表面陈列。"
            "结尾要明确结论、边界或行动落点，不要含蓄留白。"
        ),
        "draft": (
            "正文不需要含蓄，默认不用整段场景描写。"
            "多数段落优先控制在 1 到 2 句；如果单段超过 3 句，先拆段，不要让解释挤成一整块。"
            "不要用生活场景冷启动，不要连续铺动作、环境、物件和氛围。"
            "例证优先一句事实、一个后果，或 1 到 2 个有情绪功能的现实细节，写完立刻回到判断、机制、答案或行动落点。"
            "例证不要单独拖成长段，不能保留只负责摆拍的孤立动作残留。"
            "不要连续多段写环境、动作、光线、房间、夜晚等氛围。"
            "结尾直接给结论、边界或行动落点，不要靠留白让读者自己猜。"
        ),
        "assets": (
            "标题备选和导语要直接说清问题、答案入口或读者收益。"
            "尽量短句化，不要铺成长导语。"
            "不要用含蓄氛围、场景感文案或暧昧留白来包装正文。"
        ),
        "publish_package": (
            "发布摘要、标签和编辑备注直接写清核心结论、信息增量和情绪价值。"
            "不要写成含蓄推荐语、氛围描述或需要读者自己猜的编辑备注。"
        ),
    },
)


TRACKED_ARTICLE_STRATEGY_DIRECT_ANSWER_SKILL = ContentSkill(
    key="direct_answer_scene_budget",
    label="参考文章策略优先直答节奏",
    stages=("outline", "draft"),
    instructions_by_stage={
        "outline": (
            "大纲仍然要直接，但这里的“直接”是先把真实卡点钉住，不是把所有稿子都压成整齐三段式。"
            "开头优先落一个现实接口、顺序落差、身体反应或当下阻力，再推进判断。"
            "如已有策略包，段落快慢、推进顺序和结尾动作优先服从策略模式。"
            "结尾给方向感、位置感、现实落点或轻微余波即可，不强行把话说成标准答案。"
        ),
        "draft": (
            "正文可以先让一个现实接口、动作后果、顺序落差或身体反应顶上来，不必第一句就把答案喊满。"
            "多数段落仍保持短段，但允许前半篇出现 1 到 2 处一句一段的人话短句或可摘录句，不要把每段都写成同样宽度的成熟讲解段。"
            "例证之后可以先给情绪承接、关系余波或位置感变化，再给判断，不必句句立刻落成结论。"
            "如已有策略包，结构、节奏和情绪落点优先服从策略模式，不要统一写成“先讲结论、再展开讲解、最后完整收口”的厂牌样板。"
            "结尾给方向感、位置感、现实落点或轻微余波即可，不强求口号式答案句。"
        ),
    },
)


TRACKED_ARTICLE_THEME_FIRST_PACKAGING_SKILL = ContentSkill(
    key="direct_answer_scene_budget",
    label="参考文章主题优先包装节奏",
    stages=("assets", "publish_package"),
    instructions_by_stage={
        "assets": (
            "包装仍然要清楚，但不要默认先把问题、答案和收益压成同一种直答标题模板。"
            "标题、封面文案和分发导语优先服从这篇的主题主线、包装抓手和正向落点。"
            "允许先用一个阶段节点、现实接口、关系落差、引用或短判断把读者截住，再把落点带回正文已经成立的方向。"
            "导语尽量短句化，但不要为了显得利落，把不同题材统一写成同一类问题解答或情绪结论。"
        ),
        "publish_package": (
            "发布包表达要清楚，但不要默认先把摘要、标题和导语压成标准答案或统一结论句。"
            "发布标题、导语、摘要和编辑备注优先服从正文主线、正向落点和包装钩子。"
            "允许先给一个更像真人会转发的开口，再把读者带回正文已经成立的主题，而不是为了顺口偷换成另一条泛情绪赛道。"
        ),
    },
)


TRACKED_ARTICLE_THEME_FIRST_PLATFORM_VALUE_SKILL = ContentSkill(
    key="wechat_platform_value",
    label="参考文章主题优先守门",
    stages=("outline", "draft", "assets", "publish_package"),
    instructions_by_stage={
        "outline": (
            "先根据上游主题主线、正向落点和结构模式安排段落职责。"
            "不要把不同参考文章统一压成同一种反常识开头、整齐三段式或标准答案节拍。"
            "只要服务当前主题，场景、判断、关系接口、引用和现实细节都可以成为开场抓手。"
        ),
        "draft": (
            "先把这篇真正的主题、正向落点和现实抓手写对，再追求统一平台腔。"
            "情绪价值要正向，但要从当前这篇的处境里长出来，不要把不同题材都写成同一类内耗、自救、放下或心安模板。"
            "入口、段落快慢和人味细节优先服从当前主题与结构模式，不统一压成“现实接口 + 判断 + 答案”的厂牌样板。"
        ),
        "assets": (
            "标题、封面文案和分发导语先服务正文主线、正向落点和包装抓手。"
            "要像真人会转发时写下的开口，不要为了更顺手把主题换成另一条泛情绪赛道。"
        ),
        "publish_package": (
            "发布标题、导语、摘要和编辑备注都先服务正文主线和正向落点。"
            "要像真人发布前的取舍与开场，不要把这篇稿子改写成更常见的泛成长、泛疗愈或泛关系结论。"
        ),
    },
)


DEFAULT_CONTENT_SKILLS: tuple[ContentSkill, ...] = (
    WECHAT_PLATFORM_VALUE_SKILL,
    DIRECT_ANSWER_SCENE_BUDGET_SKILL,
)


def _has_tracked_article_strategy_package(payload: Mapping[str, object] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if str(payload.get("source_type") or "").strip() != "tracked_article":
        return False
    return isinstance(payload.get("strategy_card"), Mapping) or isinstance(payload.get("problem_brief"), Mapping)


def _resolve_content_skills(
    *,
    stage: str,
    payload: Mapping[str, object] | None,
    skills: Iterable[ContentSkill],
) -> tuple[ContentSkill, ...]:
    if stage not in {"outline", "draft", "assets", "publish_package"} or not _has_tracked_article_strategy_package(payload):
        return tuple(skills)

    resolved: list[ContentSkill] = []
    for skill in skills:
        if skill.key == WECHAT_PLATFORM_VALUE_SKILL.key:
            resolved.append(TRACKED_ARTICLE_THEME_FIRST_PLATFORM_VALUE_SKILL)
            continue
        if skill.key == DIRECT_ANSWER_SCENE_BUDGET_SKILL.key:
            if stage in {"outline", "draft"}:
                resolved.append(TRACKED_ARTICLE_STRATEGY_DIRECT_ANSWER_SKILL)
            else:
                resolved.append(TRACKED_ARTICLE_THEME_FIRST_PACKAGING_SKILL)
            continue
        resolved.append(skill)
    return tuple(resolved)


def build_content_skill_instructions(
    *,
    stage: str,
    payload: Mapping[str, object] | None = None,
    skills: Iterable[ContentSkill] = DEFAULT_CONTENT_SKILLS,
) -> str:
    resolved_skills = _resolve_content_skills(stage=stage, payload=payload, skills=skills)
    return "".join(skill.instructions_for(stage) for skill in resolved_skills)

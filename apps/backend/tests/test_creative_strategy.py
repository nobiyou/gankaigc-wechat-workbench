from app.services.creative_strategy import (
    _resolve_inner_settlement_variant,
    build_strategy_package,
    resolve_tracked_article_structure_mode,
)


def test_build_strategy_package_supports_manual_original_idea_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "manual-original-project",
            "topic_title": "为什么总在深夜反复确认一段关系",
            "topic_angle": "从反复点开聊天框但迟迟不敢发消息的动作切入，解释不安怎样把表达变成试探。",
            "trend_title": "",
            "source_type": "manual",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-19T00:00:00Z",
    )

    assert result.problem_brief.source_mode == "manual"
    assert result.problem_brief.raw_goal == "为什么总在深夜反复确认一段关系"
    assert result.problem_brief.status == "ready"
    assert result.benchmarks[0].reference_kind == "operator_reference"
    assert result.benchmarks[0].reference_label == "为什么总在深夜反复确认一段关系"
    assert "不要复用现成判断句" in result.benchmarks[0].avoid_focus


def test_build_strategy_package_marks_vague_upstream_input_as_unknown() -> None:
    result = build_strategy_package(
        project={
            "slug": "vague-topic-project",
            "topic_title": "女性成长",
            "topic_angle": "",
            "trend_title": "女性成长",
            "source_type": "trend",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-19T00:00:00Z",
    )

    assert "切口仍偏泛，大纲阶段要主动收窄到一个更具体的处境。" in result.problem_brief.unknowns
    assert "女性成长" in result.problem_brief.raw_goal
    assert result.strategy_card.status == "ready"


def test_build_strategy_package_records_benchmark_borrow_and_avoid_boundaries() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-reference-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟复查和总说等忙完的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "开头先给身体提醒，中段写一次次顺延，结尾回到生活排序。",
            "reference_article_body_markdown": (
                "# 别把日子过反了\n\n"
                "朋友阿杰总说等忙完再体检，后来连复查也一次次往后推。\n\n"
                "直到医生说要透析，他才发现身体提醒早就出现过。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-19T00:00:00Z",
    )

    benchmark = result.benchmarks[0]
    assert benchmark.reference_kind == "tracked_article"
    assert benchmark.reference_label == "别把日子过反了"
    assert "原文压力类型和情绪发动机" in benchmark.borrow_focus
    assert "段落职责分配" in benchmark.borrow_focus
    assert "不要复用原标题骨架" in benchmark.avoid_focus
    assert "只借观察路径、冲突组织和节奏职责" in benchmark.rationale
    assert any("不得沿用原标题骨架" in constraint for constraint in result.problem_brief.constraints)


def test_resolve_tracked_article_structure_mode_keeps_response_priority_when_analysis_copy_mentions_ignore() -> None:
    body_markdown = (
        "听过一句话：‘红灯30秒，我喝了一口水，拍了张照片，回了条消息。’\n\n"
        "真正的原因可能是，因为我们不够重要，所以对方漫不经心，爱搭不理。人对在乎的人，永远都有时间。\n\n"
        "没时间，是因为你不在他心里，或者顺序没那么优先。一个人的时间在哪儿，他的心就在哪儿。"
    )

    resolved = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary="文章借‘没时间回消息’这一高频关系场景，讨论一个人是否真的忙，还是只是没有把你放在靠前的位置。",
        structure_notes="开头先借‘红灯30秒’的日常感受切入；中段连续拆解‘忙’与‘在乎’的关系；结尾落到关系选择上。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：在亲密关系和暧昧互动里，一个人如何通过回应优先级判断自己是否被重视。",
        analysis_core_conflict="表面冲突是‘对方说自己忙、没时间’，真正要拆开的是：关系里的忽视常被包装成客观原因，而被等待的人却不断替这种低优先级找理由。",
        analysis_emotional_exit="不再反复追问对方为什么慢回，而是根据回应的优先级重新分配自己的情感和时间。",
        analysis_opening_pattern="从一个‘红灯30秒也能做很多事’的生活片段起笔。",
        analysis_do_not_turn_into="不要写成单纯控诉谁不够爱谁的关系审判文。",
    )

    assert resolved == "response_priority"


def test_resolve_tracked_article_structure_mode_prefers_supportive_appreciation_for_soft_hearted_article() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "有一种人，习惯了燃烧自己，去照亮别人。你对他好，他会对你更好。\n\n"
            "心软的人并不傻，他们的心里比谁都拎得清。不去计较，是因为心里在乎，不想与爱的人争辩输赢、对错和得失。\n\n"
            "那些愿意包容你的人，一定很爱你。如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
        ),
        summary="文章重点不是谁在关系里耗空自己，而是心软为什么常被误解，以及那些明明拎得清、却还是愿意包容和体谅别人的人，为什么最值得被珍惜。",
        structure_notes="先写心软的人总会先替别人着想，再拆这种柔软为什么常被误读，结尾回到这样的人最值得被珍惜。",
        analysis_structure_mode_hint="relationship_aftercare",
        analysis_theme="这篇文章真正想讨论的是：很多人把柔软误读成好说话，却忽略了那些明明拎得清、却还是愿意包容和体谅别人的人，其实最值得被认真珍惜。",
        analysis_core_conflict="一边是心软的人总在关系里先让一步、先顾及别人感受；另一边是旁人把这种包容误认成没底线、好说话，忽略了它背后的分寸感和珍贵。",
        analysis_emotional_exit="让读者重新看见：心软不是傻，真正稀缺的是那份明明看得清，却还是愿意把温柔给出来的分量。",
        analysis_opening_pattern="先从心软的人总在关系里先让一步的常见处境切入，再慢慢提判断。",
        analysis_do_not_turn_into="不要改写成谁在关系里耗空自己、谁总在善后或谁该先照顾自己的诊断稿。",
    )

    assert resolved == "supportive_appreciation"


def test_resolve_tracked_article_structure_mode_does_not_blindly_trust_scene_first_hint_for_regret_release() -> None:
    body_markdown = (
        "傍晚下楼扔垃圾，撞见邻居阿婆正蹲在垃圾桶旁，对着一袋旧衣物发呆。\n\n"
        "原来我们都一样，总爱攥着过去的遗憾不放，盯着没走成的路反复设想，却忘了脚下的路，从来都是朝前延伸的。\n\n"
        "你看，放下从来都不是遗忘，而是给心找一个更轻盈的去处。"
    )

    resolved = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary="文章借一位老人反复看旧裙子的细节，讨论人为什么总被‘如果当初’困住。重点不在否认遗憾，而在提醒读者把回不去的部分安放好。",
        structure_notes="开头用阿婆看旧裙子的场景起笔；中段从个体画面推开到普遍经验；结尾再回到阿婆买新裙子的后续。",
        analysis_structure_mode_hint="scene_first_progression",
        analysis_theme="这篇文章真正想讨论的是：如何和无法重来的过去拉开距离，把遗憾从持续消耗变成可以安放的人生部分。",
        analysis_core_conflict="人明知过去无法改写，却还是会反复停留在‘如果当初’的设想里。",
        analysis_emotional_exit="不必否认遗憾，但可以把它收好，重新把注意力交还给明天、日常和仍可发生的新体验。",
        analysis_opening_pattern="从日常偶遇的具体场景起笔。",
        analysis_do_not_turn_into="不要改写成喊口号式的励志文。",
    )

    assert resolved == "emotional_engine_direct"


def test_resolve_tracked_article_structure_mode_keeps_scene_first_when_local_structure_evidence_exists() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "她推开门，先看见餐桌上还冒热气的汤。\n\n"
            "第二天清晨，她又在同一间屋子里对着还没说出口的话停住。"
        ),
        summary="文章重点不是先下结论，而是让读者先跟着一个处境慢慢走进去。",
        structure_notes="开头先让一到两个连续场景带路，中段再展开判断，不要直接平铺观点，结尾回到同一处境现场。",
        analysis_structure_mode_hint="scene_first_progression",
        analysis_theme="这篇文章真正想讨论的是：人在迟迟开不了口的时候，往往先被现场情绪卡住。",
        analysis_core_conflict="不是不知道要说什么，而是始终没有跨过那个当下。",
        analysis_emotional_exit="等情绪被看见以后，表达才有可能慢慢发生。",
        analysis_opening_pattern="先让场景带路，后面再提判断。",
        analysis_do_not_turn_into="不要一上来就平铺观点。",
    )

    assert resolved == "scene_first_progression"


def test_resolve_tracked_article_structure_mode_promotes_scene_first_from_body_even_with_wrong_hint() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "夜里十点，她听见钥匙转动，先把茶几上的药盒往里推了推。\n\n"
            "他弯腰换鞋，问了一句\"孩子睡了？\"她点头，把那张揉皱的检查单重新压回杯子底下。\n\n"
            "第二天送孩子出门前，她又看见那张单子露出一角，想开口，最后只说了句\"路上慢点\"。\n\n"
            "有些人不是不知道问题在那儿，而是每次走到那个场景里，就先把更重要的话往后放。"
        ),
        summary="文章重点不是先给答案，而是让读者先跟着一连串家庭现场慢慢走进去，再意识到真正卡住的是什么。",
        structure_notes="开头先让连续场景带路，中段再把迟迟开不了口这件事讲明白，不要一上来平铺观点。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：很多关系里的卡住，不是没有问题，而是总在那个该开口的现场里把更重要的话压后。",
        analysis_core_conflict="明明知道有事该说，可一回到那个具体场景里，人就会先把更要紧的话咽回去。",
        analysis_emotional_exit="先让人认出自己是怎么一步步错过开口时机的，后面才谈表达和面对。",
        analysis_opening_pattern="先从家里的连续现场切入，再慢慢提判断。",
        analysis_do_not_turn_into="不要一开头就把它写成抽象关系道理。",
    )

    assert resolved == "scene_first_progression"


def test_resolve_tracked_article_structure_mode_promotes_scene_first_for_office_scene_chain() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "周一早会开始前，她站在投影幕布旁，把昨晚改好的方案又往后翻了一页。\n\n"
            "主管进门，随手把咖啡放在桌角，先说了一句‘今天先按老方案过吧’，会议室里的人都低头去翻手里的资料。\n\n"
            "散会以后，她还坐在原位，看着屏幕上的最后一页，直到清洁阿姨来收水杯，才把那句本来该在会上说出来的话关掉。\n\n"
            "很多时候，问题不是没看见，而是一个人总在那个现场里先替气氛让路。"
        ),
        summary="文章不是先讲职场道理，而是先让读者跟着会议前、中、后的连续现场走一遍，再意识到真正被压后的是什么。",
        structure_notes="开头先让会议前后几个连续场景带路，后面再把总在现场里先让路这件事讲明白，不要一上来平铺观点。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：很多职场沉默不是没想法，而是总有人在那个现场里先替秩序和气氛让路。",
        analysis_core_conflict="明明知道有话该说，可一回到会议室和现场顺序里，人就先把更重要的话压后。",
        analysis_emotional_exit="先让人认出自己是怎么一步步把发言机会让过去的，后面才谈表达和位置感。",
        analysis_opening_pattern="先从会议室前后连续现场切入，再慢慢提判断。",
        analysis_do_not_turn_into="不要一开头就把它写成抽象职场说理文。",
    )

    assert resolved == "scene_first_progression"


def test_resolve_tracked_article_structure_mode_prefers_verified_emotional_engine_hint_over_pressure_topic_copy() -> None:
    body_markdown = (
        "傍晚下楼扔垃圾，撞见邻居阿婆正蹲在垃圾桶旁，对着一袋旧衣物发呆。\n\n"
        "原来我们都一样，总爱攥着过去的遗憾不放，盯着没走成的路反复设想，却忘了脚下的路，从来都是朝前延伸的。\n\n"
        "你看，放下从来都不是遗忘，而是给心找一个更轻盈的去处。"
    )

    resolved = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary="文章借一位老人反复看旧裙子的细节，讨论人为什么总被‘如果当初’困住。重点不在劝人强行忘记，而在提醒读者承认遗憾存在，同时把注意力慢慢挪回仍在继续的当下生活。",
        structure_notes="开头从生活场景切入，用旧裙子的细节带出对过往遗憾的停留；中段扩展到普遍心理；结尾回到阿婆买新裙子的后续，落到放下不是遗忘，而是继续生活。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想谈的是：人该怎样和已经无法更改的遗憾相处，才能不再被过去持续消耗。",
        analysis_core_conflict="一边是人对错过的人、事、选择反复设想、迟迟不肯松手；另一边是现实已经无法回退，继续沉溺只会占用当下和未来的生活感受。",
        analysis_emotional_exit="不必否认曾经在意过，也不必逼自己立刻忘掉，而是允许过去被安放，再把心力转回新的日常、新的关系和新的期待里。",
        analysis_opening_pattern="从生活接口里的偶遇场景起笔，以邻居阿婆对旧衣物发呆的细节切入遗憾与回头心理。",
        analysis_do_not_turn_into="不要改写成单纯鼓吹立刻断舍离、彻底忘掉过去的励志口号文。",
    )

    assert resolved == "emotional_engine_direct"


def test_build_strategy_package_keeps_scene_first_office_strategy_semantics() -> None:
    result = build_strategy_package(
        project={
            "slug": "scene-first-office-strategy-project",
            "topic_title": "你在会上反复删掉的那句话，正在把你训练成一个越来越少提需求的人",
            "topic_angle": "从“先把气氛稳住”这类职场自我要求切入，拆开女性如何在一次次当场撤回里，把表达压缩成对自己需求的长期忽略。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "很多话不是没想好，是总在那个要开口的会议室里被咽回去",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借一次会议上没说出口的方案意见，观察很多人并非没有判断，而是在职场现场里长期先顾及气氛与秩序。它真正拆解的是，沉默如何从一次退让慢慢变成对‘重要的话不该打扰别人’的自我训练。",
            "reference_article_structure_notes": "开头先用早会前后的细节场景建立‘想说却咽回去’的瞬间；中段从这次沉默推进到更普遍的心理机制，指出问题不在没看见，而在习惯先给气氛让路；结尾收束到长期后果，点出被卡住的不只是一次发言，而是对自身位置的默认压低。",
            "reference_article_body_markdown": (
                "周一早会开始前，她站在投影幕布旁，把昨晚改好的方案又往后翻了一页。\n\n"
                "主管进门，随手把咖啡放在桌角，先说了一句‘今天先按老方案过吧’，会议室里的人都低头去翻手里的资料。\n\n"
                "散会以后，她还坐在原位，看着屏幕上的最后一页，直到清洁阿姨来收水杯，才把那句本来该在会上说出来的话关掉。\n\n"
                "很多时候，问题不是没看见，而是一个人总在那个现场里先替气氛让路。"
            ),
            "reference_article_analysis_structure_mode": "scene_first_progression",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：在职场关系和现场气氛里反复自我让位的人，如何一步步把表达能力误认成了‘不该开口’。",
            "reference_article_analysis_core_conflict": "看见问题、也有判断的人，在职场现场里却总是先照顾气氛和权力秩序，结果把表达需求压成了自我收缩。",
            "reference_article_analysis_emotional_exit": "文章最后把读者带向一种自我识别：不是你没有想法，而是你总在现场里先把自己撤回。这个出口带着一点心疼，也给人一个重新看待沉默习惯的空间。",
            "reference_article_analysis_opening_pattern": "从具体会议室场景切入，用一个临场没说出口的瞬间把人物的压抑状态直接落地。",
            "reference_article_analysis_do_not_turn_into": "不要改写成单纯鼓励‘勇敢发声’的职场鸡汤，或上升为女性不会沟通的性格问题；重点不是技巧灌输，而是长期让位如何塑造沉默。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-27T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "scene_first_progression"
    assert result.problem_brief.target_reader_situation == "总在会议上先把关键意见、边界或需求压回去，散会后再一个人补救的人"
    assert result.problem_brief.writing_goal == "把人为什么总在会上先把关键意见、边界和需求压回去讲清楚，也让读者看见，事后补救为什么会慢慢把位置感和协作里的分量一起让出去。"
    assert result.strategy_card.point_of_view == "不急着讲职场沟通技巧，先把一句话为什么总在会议室里被咽回去讲清楚。"
    assert result.strategy_card.body_shift == "中段先拆那句话为什么在当场没说出口，再写散会后补邮件、补解释、自己兜底这套动作怎样把需求表达训练得越来越晚。"
    assert "从会议现场里那句想说又咽回去的话切入，重点写人为什么总在会上先替气氛和秩序让路，事后又把需求和补救一起揽回自己身上。" in result.problem_brief.problem_statement_markdown
    assert "越想稳住越累" not in result.problem_brief.problem_statement_markdown
    assert "不要把场景优先稿写成泛内耗、单人稳情绪或勇敢发声技巧稿。" in result.strategy_card.expression_constraints


def test_build_strategy_package_keeps_generic_scene_first_relationship_semantics() -> None:
    result = build_strategy_package(
        project={
            "slug": "scene-first-relationship-strategy-project",
            "topic_title": "真正把关系拉远的，常常不是争吵，是那句在地铁口还是没问出口的话",
            "topic_angle": "从地铁口等车、想问又收回、上车后谁都没再提那句话的连续现场切入，写很多关系怎样在一次次‘先算了’里慢慢失去继续靠近的机会。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "很多关系后来变淡，不是因为吵散了，是因为每次想说的时候都先算了",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章不是先讲关系道理，而是先让读者跟着地铁口和接驳车前后的连续现场走一遍，再意识到真正被压后的，是那些本来可以确认和靠近的话。",
            "reference_article_structure_notes": "开头先让连续场景带路，中段再把一次次先算了这件事讲明白，不要一上来平铺观点。",
            "reference_article_body_markdown": (
                "雨停以后，她们站在地铁口等最后一班接驳车，手机屏幕上还停着那句没发出去的‘你最近是不是不太开心’。\n\n"
                "朋友把围巾往上拉了拉，只说‘最近有点忙’，然后低头去看脚边那滩还没干透的水。\n\n"
                "车来了，她们一前一后上去，坐定以后谁都没有再提刚才的话题，只剩窗户上被呵出来的一小团白雾。\n\n"
                "很多疏远，不是从翻脸开始的，而是从这些明明看见了、却还是决定先不碰的瞬间开始的。"
            ),
            "reference_article_analysis_structure_mode": "scene_first_progression",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：许多关系的冷却，并非源于激烈冲突，而是源于察觉之后仍选择沉默的日常退缩。",
            "reference_article_analysis_core_conflict": "明明感觉到了关系在变，可一回到那个现场里，人还是先把更重要的话压后。",
            "reference_article_analysis_emotional_exit": "先让人认出自己是怎么一步步把靠近的机会让过去的，后面才谈关系距离是怎么被慢慢拉开的。",
            "reference_article_analysis_opening_pattern": "先从地铁口前后的连续现场切入，再慢慢提判断。",
            "reference_article_analysis_do_not_turn_into": "不要一开头就把它写成抽象关系说理文。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-27T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "scene_first_progression"
    assert result.problem_brief.target_reader_situation == "总在那个该开口的现场里，先把更重要的话压回去的人"
    assert result.problem_brief.writing_goal == "把人为什么总在该开口的现场里先把更重要的话压回去讲清楚，也让读者看见，一次次让位是怎样慢慢改写位置感和关系里的在场感。"
    assert result.strategy_card.point_of_view == "不急着给关系道理或沟通答案，先把那句为什么总在现场里被压回去讲清楚。"
    assert "会议室" not in result.strategy_card.point_of_view
    assert "越想稳住越累" not in result.strategy_card.strategy_markdown


def test_build_strategy_package_inner_settlement_daily_return_avoids_fixed_night_objects() -> None:
    result = build_strategy_package(
        project={
            "slug": "inner-settlement-rumination-project",
            "topic_title": "很多事迟迟过不去，往往不是事情本身，而是那颗一直没松下来的心",
            "topic_angle": "从人为什么总想把过去想透、把未来想稳切入，写外界未必最糟时，那颗心为什么还是一直悬着。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "此心安处，才是一个人最好的归宿",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "reference_article_structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "reference_article_body_markdown": (
                "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
            ),
            "reference_article_analysis_structure_mode": "inner_settlement",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：很多时候拖住人的，不是外界已经彻底失控，而是那颗一直悬着、迟迟没落下来的心。",
            "reference_article_analysis_core_conflict": "人总想把过去想透、把未来想稳，结果把今天的自己一直留在心里那块悬空处。",
            "reference_article_analysis_emotional_exit": "不是逼自己瞬间看开，而是慢慢把那颗心放回今天正在过的生活里。",
            "reference_article_analysis_opening_pattern": "先从心为什么一直悬着、一直没有真正松下来的状态切入，再慢慢提判断。",
            "reference_article_analysis_do_not_turn_into": "不要改写成关系等待、身体告警或夜深小失序模板文。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-28T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "inner_settlement"
    assert "灯还亮着" not in result.strategy_card.opening_move
    assert "饭热了又凉" not in result.strategy_card.opening_move
    assert "终于坐下来吃一顿饭" in result.strategy_card.opening_move
    assert "普通安排重新有了分量" in result.strategy_card.opening_move
    assert "总想先把自己说服明白" in result.strategy_card.body_shift


def test_resolve_inner_settlement_variant_detects_regret_release() -> None:
    variant = _resolve_inner_settlement_variant(
        topic_title="遗忘再长，也长不过明天和以后",
        topic_angle="从人为什么总会被过去和如果当初拉回去切入，写遗憾怎样被慢慢安放。",
        context_text="开头用会勾回旧念头的现实接口切入，中段再拆为什么总会回头，结尾落回把遗憾收好、继续生活。",
    )

    assert variant == "regret_release"


def test_build_strategy_package_keeps_self_reliance_theme_out_of_relationship_expression_sink() -> None:
    result = build_strategy_package(
        project={
            "slug": "self-reliance-strategy-project",
            "topic_title": "当外求未必总能及时接住你时，真正能托住你的，往往是你自己",
            "topic_angle": "从成年人想找人倾诉、想向外求助，却发现别人也各自承压切入，写一个人怎样慢慢把依靠收回自己身上，学会向内求冷静、沉淀和成长。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "即使没有帮助，也要学会自救自渡",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章从想找人倾诉却发现身边人也自顾不暇的场景切入，写成年人在低谷里对外求助常常得不到及时回应，于是逐渐学会收起委屈、转向自我消化和自我修复。核心落点不是拒绝他人，而是提醒人在不被接住的时候，也要有把自己托起来的能力。",
            "reference_article_structure_notes": "先写想倾诉却发现别人也各自承压的现实处境，中段再拆为什么外求未必总能接住人，结尾回到向内稳住、自救自渡和慢慢把自己托起来。",
            "reference_article_body_markdown": (
                "相信你也有过这样的时刻：心情不好的时候想找朋友倾诉，却发现朋友也愁眉不展。\n\n"
                "只有向内求，才能自我疗愈，生生不息。只有靠自己，你才能有所顿悟、有所收获、有所改变。\n\n"
                "即使没有帮助，也不会孤立无援，而是能够自救自渡。"
            ),
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "文章真正讨论的是：成年人在困境中如何从依赖外界安慰，转向建立内在的自我支撑与恢复能力。",
            "reference_article_analysis_core_conflict": "想向外寻求安慰和帮助，但现实里身边的人也各自承压，外部支撑不稳定，只能重新把依靠收回到自己身上。",
            "reference_article_analysis_emotional_exit": "把读者从无助和失望带到一种更稳的状态：接受帮助未必及时，但自己也有能力慢慢把日子撑过去。",
            "reference_article_analysis_opening_pattern": "从生活接口和现实压力切入，先写想倾诉却无人可依的具体处境。",
            "reference_article_analysis_do_not_turn_into": "不要写成鼓励一味硬扛、拒绝求助，或把自我成长说成空泛的鸡汤式宣言。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-28T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "self_reliance_inward_support"
    assert "等外面的安慰" in result.problem_brief.writing_goal
    assert "先把自己安顿好" in result.problem_brief.writing_goal
    assert "先把日子稳稳接回来" in result.problem_brief.writing_goal
    assert "自救自渡不是硬扛" in result.problem_brief.problem_statement_markdown
    assert "低谷里" in result.strategy_card.reader_situation
    assert "安顿住" in result.strategy_card.reader_situation
    assert "想解释，却越来越不想开口" not in result.strategy_card.reader_situation
    assert "越想解释越说不出口" not in result.problem_brief.writing_goal
    assert "真正把关系拖住的" not in result.strategy_card.conflict_frame
    assert "刚好有空的位置" in result.strategy_card.body_shift
    assert "把今天过完" in result.strategy_card.emotional_path
    assert "现实已经挤满眼前" in result.strategy_card.opening_move
    assert "帮助未必赶得上" in result.strategy_card.opening_move
    assert any("外面的帮扶一时赶不上的现实接口" in item for item in result.strategy_card.recomposition_recipe)
    assert any("托底动作" in item for item in result.strategy_card.recomposition_recipe)
    assert any("现实承压" in axis for axis in result.strategy_card.divergence_axes)
    assert any("回稳动作必须更早出现" in axis for axis in result.strategy_card.divergence_axes)

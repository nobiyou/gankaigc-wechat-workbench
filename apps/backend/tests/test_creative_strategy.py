import json

from app.services.creative_strategy import (
    _build_emotional_value_goal,
    _build_packaging_focus,
    _build_packaging_hook,
    _is_usable_analysis_emotional_exit,
    _resolve_analysis_opening_kind,
    _resolve_inner_settlement_variant,
    build_complete_contract_execution_surface,
    build_strategy_package,
    has_complete_tracked_article_generation_contract,
    has_complete_tracked_article_analysis_contract,
    has_source_aligned_tracked_article_generation_contract,
    has_source_aligned_tracked_article_topic,
    resolve_tracked_article_structure_mode,
)


def test_analysis_exit_rejects_negative_only_instruction() -> None:
    assert _is_usable_analysis_emotional_exit("别等了，离开不值得的人。") is False
    assert _is_usable_analysis_emotional_exit("放下过去，带着期待继续奔向新的生活。") is True


def test_complete_analysis_contract_requires_a_forward_emotional_exit() -> None:
    base = {
        "analysis_structure_mode_hint": "response_priority",
        "analysis_theme": "真正的在乎会在时间安排里显形。",
        "analysis_core_conflict": "表面的热闹和真正的投入并不相同。",
        "analysis_opening_pattern": "从一个日常互动切入。",
        "analysis_hook_trigger": "一个细小的回应落差。",
        "analysis_progression_drive": "由顺序落差推进到关系判断。",
        "analysis_share_reason": "读者会在熟悉的等待里认出自己。",
        "analysis_do_not_turn_into": "泛泛的关系控诉。",
        "analysis_content_pillars": [
            "时间安排如何显出关系里的真实投入",
            "回应落差如何改变一个人的关系判断",
        ],
    }
    assert has_complete_tracked_article_analysis_contract(
        **base,
        analysis_emotional_exit="别等了，离开不值得的人。",
    ) is False
    assert has_complete_tracked_article_analysis_contract(
        **base,
        analysis_emotional_exit="看清位置，也把时间留给真正愿意回应你的人。",
    ) is True
    incomplete = dict(base)
    incomplete.pop("analysis_content_pillars")
    assert has_complete_tracked_article_analysis_contract(
        **incomplete,
        analysis_emotional_exit="看清位置，也把时间留给真正愿意回应你的人。",
    ) is False


def test_generation_contract_requires_specific_expression_profile() -> None:
    base = {
        "analysis_structure_mode_hint": "response_priority",
        "analysis_theme": "真正的在乎会在时间安排里显形。",
        "analysis_core_conflict": "表面的热闹和真正的投入并不相同。",
        "analysis_emotional_exit": "把时间留给真正愿意回应你的人。",
        "analysis_opening_pattern": "从一个日常互动切入。",
        "analysis_hook_trigger": "一个细小的回应落差。",
        "analysis_progression_drive": "由顺序落差推进到关系判断。",
        "analysis_share_reason": "读者会在熟悉的等待里认出自己。",
        "analysis_do_not_turn_into": "泛泛的关系控诉。",
        "analysis_content_pillars": [
            "时间安排如何显出关系里的真实投入",
            "回应落差如何改变一个人的关系判断",
        ],
    }

    assert has_complete_tracked_article_generation_contract(
        **base,
        analysis_expression_profile=["先写现场，再让判断出现", "中段用行动推进"],
    ) is False
    assert has_complete_tracked_article_generation_contract(
        **base,
        analysis_expression_profile=[
            "先写现场停顿，再让判断从动作余波里出现",
            "中段用现实选择承接主题，不平铺抽象观点",
            "结尾回到关系里的下一步，不用统一祝福收束",
        ],
    ) is True
    assert has_complete_tracked_article_generation_contract(
        **base,
        analysis_expression_profile=["语言优美", "有共鸣", "正能量"],
    ) is False


def test_complete_analysis_contract_accepts_specific_emotional_engine_mode() -> None:
    assert has_complete_tracked_article_analysis_contract(
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="遗憾需要被安放，生活才能重新向前。",
        analysis_core_conflict="人反复追问如果当初，却把已经无法回退的现实和仍在继续的生活放在了一边。",
        analysis_emotional_exit="承认曾经在意过，把留下来的温暖带回新的日常。",
        analysis_opening_pattern="从一次普通偶遇里突然被旧事触发的停顿切入。",
        analysis_hook_trigger="一个熟悉的背影让人短暂地回到了过去。",
        analysis_progression_drive="从回头追问推进到看见现实，再落到重新安排今天。",
        analysis_share_reason="让仍被旧事牵住的人看见继续生活并不等于否定过去。",
        analysis_do_not_turn_into="不要写成催促读者立刻忘掉过去的励志口号。",
        analysis_content_pillars=[
            "旧事如何在普通时刻重新出现",
            "承认在意之后如何把生活带回今天",
        ],
    ) is True


def test_source_aligned_generation_contract_rejects_a_complete_but_wrong_theme() -> None:
    common = {
        "source_title": "信任很贵，请别辜负",
        "source_summary": "文章讨论隐瞒怎样改变信任，以及坦诚如何重新托住关系。",
        "source_body_markdown": "一句谎言，一次隐瞒，那个叫信任的东西就裂了一道缝。真正的修复需要坦诚、交代和持续兑现。",
        "analysis_structure_mode_hint": "everyday_warmth_return",
        "analysis_core_conflict": "外在拥有和生活踏实之间有落差。",
        "analysis_emotional_exit": "重新看见家人、知己和日常的分量。",
        "analysis_opening_pattern": "从一句关于幸福的判断起笔。",
        "analysis_hook_trigger": "一个普通愿望让幸福坐标变化。",
        "analysis_progression_drive": "从比较推进到知足和陪伴。",
        "analysis_share_reason": "让忙着追赶的人重新看见眼前生活。",
        "analysis_do_not_turn_into": "不要写成关系修复稿。",
        "analysis_content_pillars": [
            "幸福标准从外在拥有转向知足",
            "家人的平安和日常温度构成归处",
        ],
        "analysis_expression_profile": [
            "先用判断句立住幸福标准，再落到现实选择",
            "中段用日常细节承接主题，不平铺抽象观点",
            "结尾回到眼前生活的分量，不用关系修复收束",
        ],
    }

    assert has_source_aligned_tracked_article_generation_contract(**common) is False

    aligned = {
        **common,
        "analysis_structure_mode_hint": "trust_boundary",
        "analysis_theme": "亲密关系里的信任，需要被坦诚和持续兑现共同守住。",
        "analysis_core_conflict": "一次隐瞒会让交出的放心变成反复确认，关系表面仍在继续，心却已经不敢像从前那样打开。",
        "analysis_emotional_exit": "珍惜愿意交付的赤诚，用坦诚和守护把关系里的心安托住。",
        "analysis_opening_pattern": "从一句关于信任的判断起笔，再落到谎言让人心里裂开一道缝的现实。",
        "analysis_hook_trigger": "一次隐瞒让原本放心的人开始反复确认。",
        "analysis_progression_drive": "从信任裂开的瞬间推进到辜负的代价，再落到坦诚和兑现如何修复关系。",
        "analysis_share_reason": "让拥有别人赤诚交付的人意识到，信任不是默认存在，而是需要每天守护的关系底气。",
        "analysis_do_not_turn_into": "不要写成回消息、点赞评论或谁更在乎你的关系排序稿。",
        "analysis_content_pillars": [
            "谎言和隐瞒如何让放心变成反复确认",
            "坦诚、交代和持续兑现如何重新托住关系",
        ],
    }
    assert has_source_aligned_tracked_article_generation_contract(**aligned) is True


def test_relationship_fatigue_reference_uses_self_worth_mode_when_the_issue_is_shared_work() -> None:
    body = (
        "我们总习惯用爱不爱丈量一段关系，却忘了问自己累不累。"
        "吵架时总是先低头，不敢说真话，也不敢提需求，心里只剩失望。"
        "成熟的感情里会有妥协和磨合，遇到问题共同解决，而不是一个人独自承担。"
    )

    assert resolve_tracked_article_structure_mode(
        article_title="别只问爱不爱，累不累才是答案",
        body_markdown=body,
        analysis_structure_mode_hint="trust_boundary",
        analysis_theme="关系里的疲惫提醒人重新确认是否存在对等回应。",
        analysis_core_conflict="共同磨合和一个人独自迁就之间存在失衡。",
        analysis_emotional_exit="让关系回到坦诚、共同承担和相处自在。",
        analysis_opening_pattern="从一句关系判断切入。",
        analysis_hook_trigger="爱不爱被改写成会不会累。",
        analysis_progression_drive="从迁就和压抑推进到共同解决与继续相处。",
        analysis_share_reason="让长期独自承担关系问题的人看见自己的疲惫。",
        analysis_do_not_turn_into="不要写成简单的分手劝告。",
        analysis_content_pillars=[
            "过度迁就怎样让关系变成单方面承担",
            "共同解决和磨合怎样让关系重新获得分量",
        ],
        trust_complete_analysis_contract=True,
    ) == "self_worth_rebuild"


def test_source_aligned_generation_contract_accepts_responsibility_sub_lane_of_everyday_warmth() -> None:
    responsibility = {
        "source_title": "万般辛苦，皆为序章，人间安稳，终会如愿",
        "source_summary": "文章写成年人把父母、孩子、伴侣和一个家的安稳放在前面，认真承担最后换来家人的照应。",
        "source_body_markdown": (
            "电话的那头，是父母、孩子和每个月的账单；电话的这头，你说没事，有我。"
            "你熬过的每一个黑夜，都在为身边所爱之人撑起一片晴空。"
            "人间安稳，从来不是没有风雨，而是风雨再大，你知道家在哪里。"
        ),
        "analysis_structure_mode_hint": "everyday_warmth_return",
        "analysis_theme": "承担家庭责任，怎样从个人的辛苦变成家人可感知的安稳。",
        "analysis_core_conflict": "人明明很累，还是会把父母、孩子和伴侣的安稳先护住。",
        "analysis_emotional_exit": "看见认真安排生活正在给家人留下照应，也允许自己被家人分担和接住。",
        "analysis_opening_pattern": "从一项临时的家庭安排切入，再让责任的分量从后续反馈里显出来。",
        "analysis_hook_trigger": "一项需要先处理的家庭安排，让责任的顺序先显形。",
        "analysis_progression_drive": "从现实安排推进到家人被照应，再落到彼此分担和安稳回到日常。",
        "analysis_share_reason": "让总在家里先把事情安排好的人，看见自己的认真也值得被回应。",
        "analysis_do_not_turn_into": "不要写成泛中年励志、关系回应排序或只歌颂硬撑的文章。",
        "analysis_content_pillars": [
            "家庭责任如何把现实顺序推到眼前",
            "父母孩子伴侣如何在承担之外彼此照应",
        ],
        "analysis_expression_profile": [
            "先从一项现实安排落笔，再让责任判断从动作后果里出现",
            "中段写家人如何被照应，也写承担者如何得到分担",
            "结尾回到家里恢复秩序的具体动作，不用统一祝福收束",
        ],
    }

    assert has_source_aligned_tracked_article_generation_contract(**responsibility) is True


def test_source_aligned_generation_contract_accepts_daily_order_during_a_low_point() -> None:
    contract = {
        "source_title": "把此刻过好，转机总会在路上",
        "source_summary": "文章写人在看不到出路时，先用规律生活和手边小事恢复行动感。",
        "source_body_markdown": (
            "跌入低谷时，不必反复追问未来，先把今天过好。"
            "每天按时起床、运动、阅读、整理房间，认真完成手边小事，"
            "在日复一日的生活秩序里慢慢等来转机。"
        ),
        "analysis_structure_mode_hint": "self_reliance_inward_support",
        "analysis_theme": "人在暂时看不到出路时，如何靠守住当下的生活秩序恢复行动感。",
        "analysis_core_conflict": "想立刻找到答案的急切，与低谷只能靠重复而缓慢的日常行动走出去之间的冲突。",
        "analysis_emotional_exit": "先照顾好睡眠、饮食和手边事务，重新找回对生活的掌控，并为新的转机保留可能。",
        "analysis_opening_pattern": "从一个人在低谷期仍准时起床的具体变化切入，再引出普遍处境。",
        "analysis_hook_trigger": "看不到前路时，仍像上班打卡一样准时起床。",
        "analysis_progression_drive": "由人物经历推进到对焦虑误区的拆解，再落到日常秩序如何成为现实支点。",
        "analysis_share_reason": "让正在失业或受挫的人看见，今天仍有几件低门槛的小事可以掌握。",
        "analysis_do_not_turn_into": "不要写成只靠忍耐就能改变命运的泛励志鸡汤。",
        "analysis_content_pillars": [
            "低谷期用规律生活恢复行动感",
            "把焦虑拆成当下可以完成的小事",
            "缓慢持续的行动为转机保留可能",
        ],
        "analysis_expression_profile": [
            "先以人物经历进入，再从单一经验扩展到普遍处境",
            "用连续日常动作铺出日复一日的稳定节奏",
            "中段由判断句拆解焦虑，随后用生活细节落地",
        ],
    }

    assert has_source_aligned_tracked_article_generation_contract(**contract) is True


def test_complete_responsibility_contract_does_not_repeat_analysis_meta_language() -> None:
    result = build_strategy_package(
        project={
            "slug": "complete-responsibility-contract-project",
            "topic_title": "真正托住一个家的，不只是一个人的能扛",
            "topic_angle": "从一次临时家庭安排切入，写责任怎样变成彼此照应和日常安稳。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "万般辛苦，皆为序章，人间安稳，终会如愿",
            "reference_article_summary": "文章写成年人把父母、孩子、伴侣和一个家的安稳放在前面，认真承担最后换来家人的照应。",
            "reference_article_body_markdown": (
                "电话的那头，是父母、孩子和每个月的账单；电话的这头，你说没事，有我。"
                "你熬过的每一个黑夜，都在为身边所爱之人撑起一片晴空。"
                "人间安稳，从来不是没有风雨，而是风雨再大，你知道家在哪里。"
            ),
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "文章真正讨论的是，中年人承担家庭责任，怎样从个人的辛苦变成家人可感知的安稳。",
            "reference_article_analysis_core_conflict": "一边是成年人要把父母、孩子和伴侣的安稳先护住，另一边是长期疲惫后想被分担的需要；文章试图拆开这两者之间的张力。",
            "reference_article_analysis_emotional_exit": "看见认真安排生活正在给家人留下照应，也允许自己被家人分担和接住。",
            "reference_article_analysis_opening_pattern": "从一项临时的家庭安排切入，再让责任的分量从后续反馈里显出来。",
            "reference_article_analysis_hook_trigger": "一项需要先处理的家庭安排，让责任的顺序先显形。",
            "reference_article_analysis_progression_drive": "从现实安排推进到家人被照应，再落到彼此分担和安稳回到日常。",
            "reference_article_analysis_share_reason": "让总在家里先把事情安排好的人，看见自己的认真也值得被回应。",
            "reference_article_analysis_do_not_turn_into": "不要写成泛中年励志、关系回应排序或只歌颂硬撑的文章。",
            "reference_article_analysis_content_pillars": [
                "家庭责任如何把现实顺序推到眼前",
                "父母孩子伴侣如何在承担之外彼此照应",
            ],
            "reference_article_analysis_expression_profile": [
                "先从一项现实安排落笔，再让责任判断从动作后果里出现",
                "中段写家人如何被照应，也写承担者如何得到分担",
                "结尾回到家里恢复秩序的具体动作，不用统一祝福收束",
            ],
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-03T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    combined = json.dumps(result.model_dump(), ensure_ascii=False)
    assert combined.count("文章真正讨论的是") == 0
    assert "家庭责任" in combined
    assert "彼此分担" in combined or "照应" in combined


def test_strategy_package_does_not_adopt_a_complete_but_wrong_analysis_contract() -> None:
    result = build_strategy_package(
        project={
            "slug": "mismatched-contract-project",
            "topic_title": "把幸福放回日常",
            "topic_angle": "从一个普通愿望切入，写幸福标准怎样重新排序。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "信任很贵，请别辜负",
            "reference_article_summary": "文章讨论隐瞒怎样改变信任，以及坦诚如何重新托住关系。",
            "reference_article_body_markdown": "一句谎言，一次隐瞒，那个叫信任的东西就裂了一道缝。真正的修复需要坦诚、交代和持续兑现。",
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "幸福来自普通日子的陪伴和安稳。",
            "reference_article_analysis_core_conflict": "外在拥有和生活踏实之间有落差。",
            "reference_article_analysis_emotional_exit": "重新看见家人、知己和日常的分量。",
            "reference_article_analysis_opening_pattern": "从一句关于幸福的判断起笔。",
            "reference_article_analysis_hook_trigger": "一个普通愿望让幸福坐标变化。",
            "reference_article_analysis_progression_drive": "从比较推进到知足和陪伴。",
            "reference_article_analysis_share_reason": "让忙着追赶的人重新看见眼前生活。",
            "reference_article_analysis_do_not_turn_into": "不要写成关系修复稿。",
            "reference_article_analysis_content_pillars": [
                "幸福标准从外在拥有转向知足",
                "家人的平安和日常温度构成归处",
            ],
            "reference_article_analysis_expression_profile": [
                "先用判断句立住幸福标准，再落到现实选择",
                "中段用日常细节承接主题，不平铺抽象观点",
                "结尾回到眼前生活的分量，不用关系修复收束",
            ],
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-03T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    assert result.strategy_card.structure_mode == "trust_boundary"
    assert "幸福来自普通日子的陪伴和安稳" not in result.strategy_card.positive_direction


def test_complete_analysis_contract_rejects_execution_placeholder_entry() -> None:
    base = {
        "analysis_structure_mode_hint": "everyday_warmth_return",
        "analysis_theme": "幸福在普通日子里重新有了分量。",
        "analysis_core_conflict": "人容易把更大的拥有误认成更好的生活。",
        "analysis_opening_pattern": "一个具体生活停顿。",
        "analysis_hook_trigger": "一个具体生活停顿。",
        "analysis_progression_drive": "由标准变化推进到知足惜福。",
        "analysis_share_reason": "读者会重新看见眼前生活的价值。",
        "analysis_do_not_turn_into": "不要写成空泛反成功学。",
        "analysis_emotional_exit": "把注意力收回家人、知己和眼前的踏实。",
    }

    assert has_complete_tracked_article_analysis_contract(**base) is False


def test_complete_contract_execution_surface_preserves_content_pillars() -> None:
    surface = build_complete_contract_execution_surface(
        {
            "source_type": "tracked_article",
            "topic_title": "把幸福从远方搬回日常",
            "topic_angle": "从一次家庭安排切入，写幸福标准怎样重新排序。",
            "reference_article_body_markdown": "身体安稳、知己可靠、家里有爱。",
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "幸福在经历之后重新有了分量。",
            "reference_article_analysis_core_conflict": "外在拥有和真实安稳之间存在落差。",
            "reference_article_analysis_emotional_exit": "珍惜眼前的平安和爱。",
            "reference_article_analysis_opening_pattern": "从一个现实安排切入。",
            "reference_article_analysis_hook_trigger": "一次家庭安排让人停下来。",
            "reference_article_analysis_progression_drive": "从标准变化推进到关系和日常。",
            "reference_article_analysis_share_reason": "让人重新看见平凡生活的分量。",
            "reference_article_analysis_do_not_turn_into": "不要写成反成功学口号。",
            "reference_article_analysis_content_pillars": [
                "幸福标准从外在拥有转向知足",
                "知己关系比泛泛社交更有分量",
                "家人的平安和日常温度构成归处",
            ],
        }
    )

    assert surface["content_pillars"] == [
        "幸福标准从外在拥有转向知足",
        "知己关系比泛泛社交更有分量",
        "家人的平安和日常温度构成归处",
    ]


def test_complete_contract_execution_surface_reads_json_lists_from_project_rows() -> None:
    surface = build_complete_contract_execution_surface(
        {
            "source_type": "tracked_article",
            "topic_title": "把责任落到家里的踏实",
            "topic_angle": "从一次家庭安排切入，写承担怎样换来安稳。",
            "reference_article_title": "中年人的世界，半生风雨，半生奔波",
            "reference_article_summary": "文章写成年人承担家庭责任，后来换来家人的安稳和彼此照应。",
            "reference_article_body_markdown": "父母、孩子、账单和家里的安稳，构成成年人持续承担的现实。",
            "reference_article_analysis_structure_mode": "responsibility_shelter",
            "reference_article_analysis_theme": "承担家庭责任怎样从个人忍耐转化为家人可感知的安稳。",
            "reference_article_analysis_core_conflict": "一边是必须把家庭责任接住的现实，另一边是长期压住疲惫后对回应和分担的需要。",
            "reference_article_analysis_emotional_exit": "确认认真安排生活正在给家人留出照应和选择，也允许自己在被回应时恢复力量。",
            "reference_article_analysis_opening_pattern": "从一次家庭安排切入，再让承担的分量从后续反馈里显出来。",
            "reference_article_analysis_hook_trigger": "一项需要先处理的家庭安排，让责任的顺序先显形。",
            "reference_article_analysis_progression_drive": "从当场取舍推进到生活顺序被理顺，再落到家人获得安稳和分担。",
            "reference_article_analysis_share_reason": "让总在家里先扛住事情的人看见自己的付出，也看见自己可以被接住。",
            "reference_article_analysis_do_not_turn_into": "不要写成无条件牺牲或苦尽甘来的保证。",
            "reference_article_analysis_content_pillars": '["责任落到具体安排", "承担如何改变家里的顺序", "安稳如何被家人感知"]',
            "reference_article_analysis_expression_profile": '["先写安排，再让判断出现", "用前后反馈推进，不平铺抽象观点", "结尾停在被分担的具体动作"]',
        }
    )

    assert surface["content_pillars"] == [
        "责任落到具体安排",
        "承担如何改变家里的顺序",
        "安稳如何被家人感知",
    ]


def test_social_boundaries_execution_surface_keeps_three_scales_and_mode_packaging() -> None:
    source = (
        "人与人相处，恰似山谷的回声。慎言，避免妄言、恶言和多余的话；"
        "让渡细枝末节的输赢，却不让原则；知止，看透以后给彼此留体面。"
    )
    project = {
        "source_type": "tracked_article",
        "reference_article_title": "人与人相处的分寸",
        "reference_article_summary": "文章讨论慎言、让渡和知止如何共同改善相处。",
        "reference_article_body_markdown": source,
        "reference_article_analysis_structure_mode": "social_boundaries",
        "reference_article_analysis_theme": "成年人如何在善待他人与保护自身之间找到相处分寸。",
        "reference_article_analysis_core_conflict": "既想维持和气，又不愿因多嘴、退让和忍耐失去边界。",
        "reference_article_analysis_emotional_exit": "该缓和时不争，该开口时不退，该止步时不追问。",
        "reference_article_analysis_opening_pattern": "从判断性比喻起笔。",
        "reference_article_analysis_hook_trigger": "付出善意却未必得到善意的落差。",
        "reference_article_analysis_progression_drive": "先写慎言，再写让渡，最后写知止。",
        "reference_article_analysis_share_reason": "读者能对照自己说多、争过或忍过的时刻。",
        "reference_article_analysis_do_not_turn_into": "不要写成圆滑讨好或对所有冒犯保持沉默。",
        "reference_article_analysis_content_pillars": [
            "以慎言处理语言损耗。",
            "以让渡处理细枝末节的取舍。",
            "以知止处理看透后的停口和体面。",
        ],
        "reference_article_analysis_expression_profile": [
            "总起判断后逐层推进",
            "短判断配合生活场景",
            "结尾回收为相处尺度",
        ],
        "topic_title": "别把好脾气用错地方",
        "topic_angle": "从一次相处中的停口与退让切入，写温和如何和边界同时成立。",
    }

    surface = build_complete_contract_execution_surface(project)

    assert surface["structure_mode"] == "social_boundaries"
    assert surface["content_pillars"] == [
        "以慎言处理语言损耗",
        "以让渡处理细枝末节的取舍",
        "以知止处理看透后的停口和体面",
    ]
    assert "信任裂开" not in str(surface["packaging_hook"])
    assert "一句话、一次让步或一次适时停下" in str(surface["packaging_hook"])
    assert surface["expression_profile"] == (
        "总起判断后逐层推进",
        "短判断配合生活场景",
        "结尾回收为相处尺度",
    )
    assert surface["opening_kind"] == "judgment"


def test_complete_contract_respects_quote_opening_instead_of_forcing_a_scene() -> None:
    project = {
        "source_type": "tracked_article",
        "topic_title": "先把那句判断说清楚，再谈怎样把自己放回生活",
        "topic_angle": "从一句关于分量的判断切入，再用新的现实选择承接自我尊重。",
        "reference_article_body_markdown": "参考文章用一句引语起笔，随后拆开将就和边界。",
        "reference_article_analysis_structure_mode": "emotional_engine_direct",
        "reference_article_analysis_theme": "人不断将就时，生活会慢慢失去分量。",
        "reference_article_analysis_core_conflict": "害怕失去关系和重新尊重自己之间存在拉扯。",
        "reference_article_analysis_emotional_exit": "把精力收回来，重新守住自己的边界和体面。",
        "reference_article_analysis_opening_pattern": "从一句带判断性的引语起笔，再落到现实里的选择。",
        "reference_article_analysis_hook_trigger": "一句关于分量的判断先把人停住。",
        "reference_article_analysis_progression_drive": "从将就的代价推进到边界重新立住。",
        "reference_article_analysis_share_reason": "让总在关系里放轻自己的人获得一次确认。",
        "reference_article_analysis_do_not_turn_into": "不要写成回消息或争吵善后稿。",
        "reference_article_analysis_content_pillars": [
            "将就如何改变一个人的位置",
            "边界如何在一次选择里重新立住",
        ],
        "analysis_expression_profile": ["先用判断句立住问题，再用现实选择承接"],
    }

    surface = build_complete_contract_execution_surface(project)

    assert _resolve_analysis_opening_kind(
        project["reference_article_analysis_opening_pattern"],
        project["reference_article_analysis_structure_mode"],
    ) == "quotation"
    assert surface["opening_kind"] == "quotation"
    assert "表达入口" in surface["scene_anchor_requirements"][0]
    assert "动作、物件、场所或选择发生" not in " ".join(surface["scene_anchor_requirements"])
    assert "现实入口发生" not in " ".join(surface["writing_texture_notes"])
    assert list(surface["expression_profile"]) == project["analysis_expression_profile"]


def test_strategy_package_does_not_propagate_negative_only_analysis_exit() -> None:
    result = build_strategy_package(
        project={
            "slug": "negative-exit-contract",
            "topic_title": "别把时间交给总让你等的人",
            "topic_angle": "从一次次等不到回应的日常切入，写清关系里的投入如何显出位置。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "什么是没时间",
            "reference_article_summary": "文章讨论时间安排如何显出一个人把谁放在心上。",
            "reference_article_structure_notes": "先从时间落差切入，再写在乎如何通过行动显形。",
            "reference_article_body_markdown": "等不到回应的人，最后学会把时间留给自己。",
            "reference_article_analysis_theme": "真正的在乎会在时间安排里显形。",
            "reference_article_analysis_core_conflict": "表面的忙碌和实际的投入并不相同。",
            "reference_article_analysis_emotional_exit": "别等了，离开不值得的人。",
            "reference_article_analysis_structure_mode": "response_priority",
            "reference_article_analysis_opening_pattern": "从一个日常互动切入。",
            "reference_article_analysis_hook_trigger": "一个细小的回应落差。",
            "reference_article_analysis_progression_drive": "由顺序落差推进到关系判断。",
            "reference_article_analysis_share_reason": "读者会在熟悉的等待里认出自己。",
            "reference_article_analysis_do_not_turn_into": "泛泛的关系控诉。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-02T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    assert result.strategy_card.positive_direction
    assert "别等了" not in result.strategy_card.positive_direction
    assert "离开不值得" not in result.strategy_card.positive_direction
    assert any(
        marker in result.strategy_card.positive_direction
        for marker in ("认清位置", "重新分配", "留给自己")
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


def test_strategy_generic_fallbacks_do_not_reintroduce_diagnostic_packaging_shell() -> None:
    values = [
        _build_emotional_value_goal(
            structure_mode="unknown_new_theme",
            reference_analysis_emotional_exit="",
        ),
        _build_packaging_focus(
            structure_mode="unknown_new_theme",
            reference_analysis_opening_pattern="",
        ),
        _build_packaging_hook(
            structure_mode="unknown_new_theme",
            topic_title="",
            topic_angle="",
            reference_analysis_opening_pattern="",
            reference_body_markdown="",
        ),
    ]

    combined = "\n".join(values)
    assert "参考文自己的" in combined or "这篇文章自己的" in combined
    for stale in ("先抓一个具体入口", "被点破的误判", "更暖一点的落点", "被分析", "被接住、被点醒"):
        assert stale not in combined


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


def test_responsibility_shelter_strategy_uses_reference_scene_lane_without_fixed_entry() -> None:
    result = build_strategy_package(
        project={
            "slug": "responsibility-shelter-project",
            "topic_title": "家里一有事，总是你先把顺序理出来",
            "topic_angle": "从家里临时有事、自己先把顺序理清切入，写电话、日历、请假和孩子接送怎样一下子推到眼前，也写这些安排最后怎样变成家里的安稳。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "万般辛苦，皆为序章，人间安稳，终会如愿",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章围绕成年人把辛苦和委屈先往后收、把父母孩子伴侣的安稳顶在前面展开，重点不在控诉生活难，而在那些认真撑住的日子后来怎样变成一个家的底气。",
            "reference_article_structure_notes": "先从一句没事有我和电话账单这些现实重量切入，中段写责任怎样让人把家里理顺，结尾落回家里安稳和这些辛苦没有白费。",
            "reference_article_body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。\n\n"
                "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "人间安稳，从来不是没有风雨，而是风雨再大，你知道家在哪里，路再难走，你知道有人在爱你。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-21T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "responsibility_shelter"
    combined = "\n".join(
        [
            result.problem_brief.clarified_problem,
            result.strategy_card.point_of_view,
            result.strategy_card.opening_move,
            result.strategy_card.body_shift,
            result.strategy_card.ending_move,
        ]
    )
    assert "电话" in combined
    assert "我来安排" in combined
    assert "现实安排" in combined
    assert "不要硬套电话、日历或消息入口" in combined
    assert "中年励志" in combined
    assert "回消息排序" not in combined
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


def test_resolve_tracked_article_structure_mode_can_trust_complete_analysis_contract() -> None:
    body_markdown = (
        "一句谎言，一次隐瞒，那个叫信任的东西就裂了一道缝。\n\n"
        "真正长久的关系，靠坦诚和说到做到。"
    )
    contract = {
        "analysis_structure_mode_hint": "self_worth_rebuild",
        "analysis_theme": "文章真正讨论的是：人总在关系里先把自己放轻，后来怎样重新尊重自己。",
        "analysis_core_conflict": "越怕失去，越容易把边界和标准让出去。",
        "analysis_emotional_exit": "把精力收回自己，守住边界，重新确认自己的分量。",
        "analysis_opening_pattern": "从一次明明不舒服却还是说都可以的现实接口起笔。",
        "analysis_hook_trigger": "那句明明不舒服却还是说出口的都可以。",
        "analysis_progression_drive": "从一次次退让如何变成习惯推进到边界回收。",
        "analysis_share_reason": "让总在关系里把自己放轻的人重新看见自己的分量。",
        "analysis_do_not_turn_into": "不要写成信任裂缝或关系修复稿。",
        "analysis_content_pillars": [
            "习惯性退让如何压低一个人的感受",
            "边界和标准如何在日常选择里重新回来",
        ],
    }

    assert (
        resolve_tracked_article_structure_mode(
            body_markdown=body_markdown,
            **contract,
        )
        == "trust_boundary"
    )
    assert (
        resolve_tracked_article_structure_mode(
            body_markdown=body_markdown,
            trust_complete_analysis_contract=True,
            **contract,
        )
        == "self_worth_rebuild"
    )


def test_build_strategy_package_can_use_complete_analysis_contract_as_production_authority() -> None:
    result = build_strategy_package(
        project={
            "slug": "complete-analysis-contract-authority",
            "topic_title": "请先好好对待自己",
            "topic_angle": "从关系里的委屈和退让切入。",
            "source_type": "tracked_article",
            "trend_title": "参考文章 / 手动录入",
            "reference_article_title": "请先好好对待自己",
            "reference_article_summary": "文章真正讨论的是重新尊重自己。",
            "reference_article_structure_notes": "先写自我轻放，再写边界和标准回归。",
            "reference_article_body_markdown": "一句谎言，一次隐瞒，那个叫信任的东西就裂了一道缝。真正长久的关系，靠坦诚和说到做到。",
            "reference_article_analysis_structure_mode": "self_worth_rebuild",
            "reference_article_analysis_theme": "文章真正讨论的是：人总在关系里先把自己放轻，后来怎样重新尊重自己。",
            "reference_article_analysis_core_conflict": "越怕失去，越容易把边界和标准让出去。",
            "reference_article_analysis_emotional_exit": "把精力收回自己，守住边界，重新确认自己的分量。",
            "reference_article_analysis_opening_pattern": "从一次明明不舒服却还是说都可以的现实接口起笔。",
            "reference_article_analysis_hook_trigger": "那句明明不舒服却还是说出口的都可以。",
            "reference_article_analysis_progression_drive": "从一次次退让如何变成习惯推进到边界回收。",
            "reference_article_analysis_share_reason": "让总在关系里把自己放轻的人重新看见自己的分量。",
            "reference_article_analysis_do_not_turn_into": "不要写成信任裂缝或关系修复稿。",
            "reference_article_analysis_content_pillars": [
                "习惯性退让如何压低一个人的感受",
                "边界和标准如何在日常选择里重新回来",
            ],
            "reference_article_analysis_expression_profile": [
                "先从一次退让的现场切入，再让判断从余波里出现",
                "中段用具体选择推进，不平铺关系道理",
                "结尾回到边界重新立住的动作，不用统一祝福收束",
            ],
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-01T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    assert result.strategy_card.structure_mode == "self_worth_rebuild"
    assert result.problem_brief.core_conflict == "越怕失去，越容易把边界和标准让出去"
    assert "一次明明不舒服却还是说都可以" in result.strategy_card.opening_move
    assert "习惯性退让" not in result.strategy_card.opening_move
    assert "那句明明不舒服却还是说出口的都可以" == result.strategy_card.hook_trigger
    assert "一次次退让" in result.strategy_card.progression_drive
    assert result.strategy_card.ending_move == "把精力收回自己，守住边界，重新确认自己的分量"
    assert "总在关系里把自己放轻" in result.strategy_card.share_reason


def test_build_strategy_package_preserves_quote_opening_anchor_from_complete_contract() -> None:
    result = build_strategy_package(
        project={
            "slug": "quote-opening-anchor",
            "topic_title": "先把幸福的标准说清楚",
            "topic_angle": "从一句关于幸福的判断切入，再落到眼前的生活选择。",
            "source_type": "tracked_article",
            "trend_title": "参考文章 / 手动录入",
            "reference_article_title": "幸福不在远方",
            "reference_article_summary": "文章讨论人如何从外在比较回到知足、知己和家人的日常。",
            "reference_article_structure_notes": "先用一句判断提出幸福，再沿知己、家庭和生活回到知足。",
            "reference_article_body_markdown": "参考文章讨论比较、知足、知己和家人的生活分量。",
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "真正的幸福来自对眼前生活的重新确认。",
            "reference_article_analysis_core_conflict": "外在比较不断抬高标准，反而让已经拥有的安稳失去分量。",
            "reference_article_analysis_emotional_exit": "把注意力带回知足、知己和家人的日常。",
            "reference_article_analysis_opening_pattern": "从一句关于幸福的判断性引语起笔，再落到现实选择。",
            "reference_article_analysis_hook_trigger": "一句关于幸福的判断先让人停下来重新衡量生活。",
            "reference_article_analysis_progression_drive": "从外在比较推进到知足，再落到家人和知己的真实分量。",
            "reference_article_analysis_share_reason": "让总在追赶的人重新看见眼前生活并不贫乏。",
            "reference_article_analysis_do_not_turn_into": "不要写成反成功学口号或固定家庭温情故事。",
            "reference_article_analysis_content_pillars": [
                "外在比较如何抬高幸福标准",
                "知己关系如何让生活重新有分量",
                "家人的平安如何成为真实的归处",
            ],
            "reference_article_analysis_expression_profile": [
                "先用幸福判断停住读者，再让日常愿望把主题落地",
                "中段用知己和家庭的细节错开推进，不堆砌道理",
                "结尾回到眼前生活的平安，留下明亮但克制的余味",
            ],
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-03T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    anchors = " ".join(result.strategy_card.scene_anchor_requirements)
    assert "表达入口" in anchors
    assert "动作、物件、场所或选择发生" not in anchors


def test_complete_analysis_contract_does_not_store_reference_shell_in_strategy_artifacts() -> None:
    result = build_strategy_package(
        project={
            "slug": "complete-contract-artifact-isolation",
            "topic_title": "把自己的分量拿回来",
            "topic_angle": "从一次具体的边界选择切入。",
            "source_type": "tracked_article",
            "trend_title": "参考文章 / 手动录入",
            "reference_article_title": "旧搪瓷饭盒和那场没有去成的游园会",
            "reference_article_summary": "旧摘要里写了那条碎花裙和反复回想。",
            "reference_article_structure_notes": "从旧物起笔，最后催人放下。",
            "reference_article_body_markdown": "旧搪瓷饭盒被放在桌边，旁边还有一条碎花裙。",
            "reference_article_analysis_structure_mode": "self_worth_rebuild",
            "reference_article_analysis_theme": "关系里总把自己放轻的人，怎样重新尊重自己。",
            "reference_article_analysis_core_conflict": "害怕失去让人一次次压低感受和边界。",
            "reference_article_analysis_emotional_exit": "把精力收回自己，按自己的标准生活。",
            "reference_article_analysis_opening_pattern": "从旧搪瓷饭盒被放回桌边的动作切入。",
            "reference_article_analysis_hook_trigger": "旧搪瓷饭盒上的磨痕让人停了一下。",
            "reference_article_analysis_progression_drive": "沿着旧搪瓷饭盒被放回桌边的动作推进到边界和标准回收。",
            "reference_article_analysis_share_reason": "让总在迁就里想起旧搪瓷饭盒的人重新确认分量。",
            "reference_article_analysis_do_not_turn_into": "不要写成旧物怀旧或泛泛放下稿。",
            "reference_article_analysis_content_pillars": [
                "害怕失去如何让人压低感受",
                "重新确认边界和标准如何带回分量",
            ],
            "reference_article_analysis_expression_profile": [
                "先从旧物停顿切入，再让判断从动作余波里出现",
                "中段沿着退让和边界的变化推进，不写成怀旧说明",
                "结尾回到自己的标准，留下清醒而具体的余味",
            ],
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-01T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    artifacts = "\n".join(
        [
            result.problem_brief.problem_statement_markdown,
            result.strategy_card.strategy_markdown,
            result.benchmarks[0].reference_label,
        ]
    )
    assert "旧搪瓷饭盒" not in artifacts
    assert "碎花裙" not in artifacts
    assert "旧摘要" not in artifacts
    assert result.benchmarks[0].reference_label == "上游分析合同"
    assert "上游分析合同已完成" in artifacts


def test_complete_analysis_contract_does_not_reuse_structure_profile_copy_fields() -> None:
    def build(slug: str, mode: str, theme: str, conflict: str, emotional_exit: str, opening: str, hook: str, progression: str, share: str, avoid: str):
        return build_strategy_package(
            project={
                "slug": slug,
                "topic_title": theme,
                "topic_angle": theme,
                "source_type": "tracked_article",
                "trend_title": "参考文章 / 手动录入",
                "reference_article_title": theme,
                "reference_article_summary": theme,
                "reference_article_structure_notes": opening,
                "reference_article_body_markdown": opening,
                "reference_article_analysis_structure_mode": mode,
                "reference_article_analysis_theme": theme,
                "reference_article_analysis_core_conflict": conflict,
                "reference_article_analysis_emotional_exit": emotional_exit,
                "reference_article_analysis_opening_pattern": opening,
                "reference_article_analysis_hook_trigger": hook,
                "reference_article_analysis_progression_drive": progression,
                "reference_article_analysis_share_reason": share,
                "reference_article_analysis_do_not_turn_into": avoid,
                "reference_article_analysis_content_pillars": [
                    f"{theme}的现实入口",
                    f"{conflict}带来的重新判断",
                ],
                "reference_article_analysis_expression_profile": [
                    "先从本篇自己的现实入口落笔，再让判断从具体余波里出现",
                    "中段按主题变化推进，不把观点排成整齐的并列说明",
                    "结尾回到前文已经出现的现实选择，留下正向但不喊话的余味",
                ],
            },
            problem_brief_version=1,
            strategy_version=1,
            created_at="2026-08-01T00:00:00Z",
            trust_complete_analysis_contract=True,
        )

    happiness = build(
        "complete-happiness-contract",
        "everyday_warmth_return",
        "幸福不在更多拥有，而在家人平安、知己还在",
        "把快乐押在外在拥有上，却忽略了身边已经有的安稳",
        "重新看见平凡日子里的知足和珍贵",
        "从一顿家常饭没有特别，却让人停下来切入",
        "饭桌上那句不用解释的关心",
        "从外在追逐推到家人知己与平安的重新排序",
        "让总在向外比较的人想起自己已有的生活",
        "成功学",
    )
    boundaries = build(
        "complete-boundary-contract",
        "self_worth_rebuild",
        "关系里总说都可以的人，怎样把自己的分量拿回来",
        "害怕失去让人一次次压低感受和边界",
        "把时间精力收回自己，按自己的标准生活",
        "从一次明明不舒服却仍说都可以切入",
        "那句都可以背后的不舒服",
        "从顺手退让推到边界和标准回收",
        "让总在迁就里放轻自己的人重新确认分量",
        "关系修复套路",
    )

    assert happiness.strategy_card.scene_anchor_requirements != boundaries.strategy_card.scene_anchor_requirements
    assert happiness.strategy_card.quotable_line_seeds != boundaries.strategy_card.quotable_line_seeds
    assert happiness.strategy_card.recomposition_recipe != boundaries.strategy_card.recomposition_recipe
    assert happiness.strategy_card.writing_texture_notes != boundaries.strategy_card.writing_texture_notes
    assert happiness.problem_brief.theme_axis == "幸福不在更多拥有，而在家人平安、知己还在"
    assert boundaries.problem_brief.theme_axis == "关系里总说都可以的人，怎样把自己的分量拿回来"
    assert "自我价值" not in " ".join(happiness.strategy_card.expression_constraints)
    assert "知足和珍贵" in " ".join(happiness.strategy_card.quotable_line_seeds)
    assert "边界" in " ".join(boundaries.strategy_card.quotable_line_seeds)


def test_complete_contract_execution_surface_separates_topic_jobs_and_drops_reference_shell() -> None:
    base = {
        "source_type": "tracked_article",
        "topic_title": "把自己的分量拿回来",
        "topic_angle": "从一次具体的边界选择切入。",
        "reference_article_body_markdown": "旧搪瓷饭盒被放在桌边，旁边还有一条碎花裙。",
        "reference_article_analysis_theme": "关系里总把自己放轻的人，怎样重新尊重自己。",
        "reference_article_analysis_core_conflict": "害怕失去让人一次次压低感受和边界。",
        "reference_article_analysis_emotional_exit": "把精力收回自己，按自己的标准生活。",
        "reference_article_analysis_opening_pattern": "从旧搪瓷饭盒被放回桌边的动作切入。",
        "reference_article_analysis_hook_trigger": "旧搪瓷饭盒上的磨痕让人停了一下。",
        "reference_article_analysis_progression_drive": "沿着旧搪瓷饭盒被放回桌边的动作推进到边界和标准回收。",
        "reference_article_analysis_share_reason": "让总在迁就里想起旧搪瓷饭盒的人重新确认分量。",
        "reference_article_analysis_do_not_turn_into": "不要写成旧物怀旧或泛泛放下稿。",
        "reference_article_analysis_content_pillars": [
            "害怕失去如何让人压低感受",
            "重新确认边界和标准如何带回分量",
        ],
    }
    boundary_surface = build_complete_contract_execution_surface(
        {**base, "reference_article_analysis_structure_mode": "self_worth_rebuild"}
    )
    happiness_surface = build_complete_contract_execution_surface(
        {
            **base,
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "幸福不在更多拥有，而在眼前生活重新有分量。",
            "reference_article_analysis_core_conflict": "人容易把幸福押在结果上，忽略已经拥有的日常。",
            "reference_article_analysis_emotional_exit": "重新看见平凡日子里的知足和珍贵。",
        }
    )

    boundary_text = " ".join(str(value) for value in boundary_surface.values())
    happiness_text = " ".join(str(value) for value in happiness_surface.values())
    assert "旧搪瓷饭盒" not in boundary_text
    assert "碎花裙" not in boundary_text
    assert boundary_surface["packaging_focus"] != happiness_surface["packaging_focus"]
    assert boundary_surface["recomposition_recipe"] != happiness_surface["recomposition_recipe"]
    assert boundary_surface["execution_checklist"] != happiness_surface["execution_checklist"]
    assert "边界" in boundary_text
    assert "幸福" in happiness_text


def test_complete_contract_execution_surface_keeps_distinct_theme_jobs() -> None:
    def build(mode: str, theme: str, conflict: str, exit_hint: str, pillars: list[str]) -> dict[str, object]:
        return build_complete_contract_execution_surface(
            {
                "source_type": "tracked_article",
                "topic_title": f"{theme}的新选题",
                "topic_angle": "从本篇自己的判断或选择切入。",
                "reference_article_body_markdown": "参考文章保留主题分析，不提供可复用的具体外壳。",
                "reference_article_analysis_structure_mode": mode,
                "reference_article_analysis_theme": theme,
                "reference_article_analysis_core_conflict": conflict,
                "reference_article_analysis_emotional_exit": exit_hint,
                "reference_article_analysis_opening_pattern": "从本篇自己的入口起笔。",
                "reference_article_analysis_hook_trigger": "一个现实反馈让主题显形。",
                "reference_article_analysis_progression_drive": "从核心矛盾推进到正向变化。",
                "reference_article_analysis_share_reason": "让读者在自己的生活里认出这件事。",
                "reference_article_analysis_do_not_turn_into": "不要写成另一个主题。",
                "reference_article_analysis_content_pillars": pillars,
            }
        )

    response = build(
        "response_priority",
        "真正的在乎会在注意力里显形",
        "表面互动和真正理解之间有落差",
        "把心力留给愿意认真停留的人",
        ["回应质量显出位置", "被理解后情绪重新落地"],
    )
    resilience = build(
        "resilience_reconstruction",
        "人的底气来自一次次重来",
        "限制和继续行动之间有张力",
        "用持续行动重建人生主动权",
        ["限制带来新方法", "重复行动累积主动权"],
    )

    assert response["packaging_focus"] != resilience["packaging_focus"]
    assert response["recomposition_recipe"] != resilience["recomposition_recipe"]
    assert "回应" in " ".join(str(item) for item in response["recomposition_recipe"])
    assert "训练" in " ".join(str(item) for item in resilience["recomposition_recipe"])
    assert "回得快" in " ".join(str(item) for item in response["divergence_axes"])
    assert "苦难" in " ".join(str(item) for item in resilience["divergence_axes"])


def test_complete_contract_execution_surface_rejects_semantic_source_mismatch() -> None:
    surface = build_complete_contract_execution_surface(
        {
            "source_type": "tracked_article",
            "topic_title": "把幸福放回日常",
            "topic_angle": "从一个普通愿望切入。",
            "reference_article_title": "信任很贵，请别辜负",
            "reference_article_summary": "文章讨论隐瞒怎样改变信任，以及坦诚如何重新托住关系。",
            "reference_article_body_markdown": (
                "一句谎言，一次隐瞒，那个叫信任的东西就裂了一道缝。"
                "真正的修复需要坦诚、交代和持续兑现。"
            ),
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "幸福来自普通日子的陪伴和安稳。",
            "reference_article_analysis_core_conflict": "外在拥有和生活踏实之间有落差。",
            "reference_article_analysis_emotional_exit": "重新看见家人、知己和日常的分量。",
            "reference_article_analysis_opening_pattern": "从一句关于幸福的判断起笔。",
            "reference_article_analysis_hook_trigger": "一个普通愿望让幸福坐标变化。",
            "reference_article_analysis_progression_drive": "从比较推进到知足和陪伴。",
            "reference_article_analysis_share_reason": "让忙着追赶的人重新看见眼前生活。",
            "reference_article_analysis_do_not_turn_into": "不要写成关系修复稿。",
            "reference_article_analysis_content_pillars": [
                "幸福标准从外在拥有转向知足",
                "家人的平安和日常温度构成归处",
            ],
        }
    )

    assert surface == {}


def test_resolve_tracked_article_structure_mode_prefers_response_priority_for_comment_followup_article() -> None:
    body_markdown = (
        "朋友圈里，是给你点赞的人更在意你，还是给你评论的人更在意你？\n\n"
        "而评论，却需要停下来，读懂你的言外之意，斟酌字句，再留下专属的痕迹。\n\n"
        "真正关心你的人，愿意努力去读懂你的每一份脆弱，在力所能及的范围内接住破碎的你。\n\n"
        "真正关心你的人，是哪怕相隔千里，也能透过你的一句“我没事”，听出你心底的“我有点累”。"
    )

    resolved = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary="文章不是讨论社交礼仪，而是借点赞和评论的差别，讨论什么才算真正把注意力和心力放在你身上。",
        structure_notes="开头先从点赞和评论的差别切入，中段拆表层互动和真正关心之间的落差，结尾落到谁会回来追问、谁会接住你没说完的话。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：在日常互动里，一个人是否真的在意你，往往不看热闹程度，而看他会不会停下来、追问你一句、读懂你没说完的话。",
        analysis_core_conflict="表面上大家都在互动、点赞、寒暄，可真正让人安定的，从来不是路过式回应，而是有人愿意停下来，把注意力和心力真正落到你这里。",
        analysis_emotional_exit="把心力慢慢收回那些愿意认真回应、愿意接住你情绪的人身上，不再替表层互动找补。",
        analysis_opening_pattern="从点赞和评论的差别起笔，再落到一句“我没事”背后其实藏着的疲惫。",
        analysis_do_not_turn_into="不要写成泛泛的高质量关系总论，也不要写成谁冷淡谁深情的空泛判断稿。",
    )

    assert resolved == "response_priority"


def test_resolve_tracked_article_structure_mode_prefers_trust_boundary_when_trust_core_word_is_single() -> None:
    body_markdown = (
        "信任很贵，请别辜负。\n\n"
        "一句谎言，一次隐瞒，那个叫信任的东西，就裂了一道缝。\n\n"
        "你以为撒一个谎没事，以为瞒一次小事无妨，却不知道对方要花多少个夜晚，才能说服自己再信你一次。\n\n"
        "每一次辜负，都是在对方的心上划一刀。后来他开始怀疑自己的判断，也变得敏感多疑。\n\n"
        "愿你不辜负任何一份赤诚的交付，好好守护那个敢把心交给你的人。"
    )

    resolved = resolve_tracked_article_structure_mode(
        article_title="信任很贵，请别辜负",
        body_markdown=body_markdown,
        summary="文章写一段关系里一次谎言、一次隐瞒怎样让放心裂开，也写赤诚交付需要被认真守护。",
        structure_notes="开头先写信任裂开的瞬间，中段写辜负带来的怀疑和敏感，结尾回到守护赤诚。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：亲密关系里最怕的不是一次解释不清，而是放心被含糊和隐瞒一点点耗掉。",
        analysis_core_conflict="表面冲突是一个谎言、一件隐瞒，真正的冲突是一个人交出的赤诚被辜负后，再也不敢像从前那样放心。",
        analysis_emotional_exit="让读者重新珍惜那份愿意交付的赤诚，也愿意用坦诚和守护把关系里的心安托住。",
        analysis_opening_pattern="从一句判断起笔，再落到谎言和隐瞒让人心里有疙瘩的现实瞬间。",
        analysis_do_not_turn_into="不要写成回消息、点赞评论或谁更在乎你的关系排序稿。",
    )

    assert resolved == "trust_boundary"


def test_resolve_tracked_article_structure_mode_prefers_everyday_warmth_return_for_responsibility_shelter_article() -> None:
    body_markdown = (
        "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
        "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。\n\n"
        "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气；"
        "深深爱着的伴侣，也能在风雨来临时有一处温暖的屋檐庇护。"
    )

    resolved = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary="文章借成年人常说的“我没事”，写父母养老、孩子缴费、家里开销和伴侣依靠一起压上来时，很多人怎样先把自己往后放。重点不在歌颂吃苦，而在说明很多硬撑后来真的会变成一家人的安稳。",
        structure_notes="先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳和这些辛苦没有白熬。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="",
        analysis_core_conflict="",
        analysis_emotional_exit="",
        analysis_opening_pattern="",
        analysis_do_not_turn_into="",
    )

    assert resolved == "everyday_warmth_return"


def test_resolve_tracked_article_structure_mode_prefers_everyday_warmth_return_for_simple_happiness_article_with_single_achievement_anchor() -> None:
    resolved = resolve_tracked_article_structure_mode(
        article_title="人生不求大富大贵，但求简单快乐",
        body_markdown=(
            "人活着，到底是为了什么？人生苦短，只求心情愉悦，家人安康，吃穿不愁，知己二三，四季平安。\n\n"
            "生活简单就迷人，人心简单就幸福。\n\n"
            "人这一辈子，谁也争不过朝夕，财富、名利、地位不过是过眼云烟。"
        ),
        summary="文章主线是幸福不一定在更大的拥有里，常常就在平凡日常和家人知己身边。",
        structure_notes="从幸福被误认成更大拥有切入，落到一餐一饭和陪伴。",
        analysis_structure_mode_hint="",
        analysis_theme="",
        analysis_core_conflict="",
        analysis_emotional_exit="",
        analysis_opening_pattern="",
        analysis_do_not_turn_into="",
    )

    assert resolved == "everyday_warmth_return"


def test_resolve_tracked_article_structure_mode_corrects_generic_partial_contract_from_source_evidence() -> None:
    resolved = resolve_tracked_article_structure_mode(
        article_title="万般辛苦，皆为序章，人间安稳，终会如愿",
        body_markdown=(
            "电话的那头，是父母、孩子和每个月如期而至的账单。"
            "电话的这头，你只能故作轻松地说：没事，有我。\n\n"
            "那些请假、缴费和多想一步的安排，后来慢慢换来一家人的安稳。"
        ),
        summary="文章写成年人先把父母、孩子和家里的安排理顺，后来这些辛苦变成一家人的安稳。",
        structure_notes="从电话、账单和没事有我切入，结尾落回家里的安稳。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="成年人如何把责任接住",
        analysis_core_conflict="部分分析合同字段存在，但模式可能只是通用判断",
        analysis_emotional_exit="让认真安排生活变成家里的安稳",
        analysis_opening_pattern="从电话和账单切入",
        analysis_hook_trigger="电话里的没事有我",
        analysis_progression_drive="从责任安排推进到家人安稳",
        analysis_share_reason="让承担家庭责任的人被看见",
        analysis_do_not_turn_into="不要写成泛泛的情绪释放",
        trust_complete_analysis_contract=True,
    )

    assert resolved == "everyday_warmth_return"


def test_resolve_tracked_article_structure_mode_recognizes_compact_reference_signals() -> None:
    response_priority = resolve_tracked_article_structure_mode(
        article_title="什么是没时间",
        body_markdown="红灯30秒也能回一条消息。忙不是借口，真正的在乎会体现在时间和顺序里。",
        summary="文章讨论一个人是否把你放在心上。",
    )
    simple_happiness = resolve_tracked_article_structure_mode(
        article_title="简单快乐就好",
        body_markdown="人生苦短，只求家人安康、知己二三、四季平安。幸福不在拥有更多，而在知足。",
        summary="幸福常常就在平凡日常里。",
    )
    self_compassion = resolve_tracked_article_structure_mode(
        article_title="你就是那个最需要的人",
        body_markdown="小时候没人安慰，长大后迟迟等不来的理解，可以自己给自己。做那个大人、朋友和爱人，把自己放在心上。",
        summary="文章写童年缺口如何通过自我安慰和自我照顾慢慢补回来。",
    )

    assert response_priority == "response_priority"
    assert simple_happiness == "everyday_warmth_return"
    assert self_compassion == "self_reliance_inward_support"


def test_resolve_tracked_article_structure_mode_rejects_response_priority_for_low_frequency_old_relationship() -> None:
    body_markdown = (
        "有些人，不是不想联系，只是后来各自生活，再也没有互相打扰。\n\n"
        "从经常联系，到偶尔联系，再到几乎不聊；我们也许不再见面，也许不再聊天。\n\n"
        "看到晚霞、听到旧歌，仍会想起那个人，牵挂只是安静地留在心里。"
    )

    resolved = resolve_tracked_article_structure_mode(
        article_title="有些旧关系，不必重启也能被好好安放",
        body_markdown=body_markdown,
        summary="旧关系从频繁相伴转为低频联系，联系减少并不等于感情消失。",
        structure_notes="写各自生活、互不打扰，以及旧歌和晚霞勾起的牵挂。",
        analysis_structure_mode_hint="response_priority",
        analysis_theme="旧关系如何从频繁相伴转为远距离牵挂。",
        analysis_core_conflict="想重新靠近又害怕打扰，不知道该以什么身份开口。",
        analysis_emotional_exit="允许彼此不常联系，也保留祝福和牵挂，各自把生活过好。",
        analysis_opening_pattern="从一处旧关系留下的生活余波切入。",
        analysis_hook_trigger="想联系却停在开口之前的那一下。",
        analysis_progression_drive="从身份困惑推进到联系减少，再回到低频关系里的安静牵挂。",
        analysis_share_reason="让曾经亲近、如今各自生活的人得到不必强行重启关系的安定感。",
        analysis_do_not_turn_into="不要写成必须挽回或必须彻底切断的二选一。",
        analysis_content_pillars=[
            "旧关系重启前的身份困惑",
            "生活迁移怎样让联系自然减少",
        ],
        trust_complete_analysis_contract=True,
    )

    assert resolved == "emotional_engine_direct"


def test_source_aligned_topic_rejects_reference_surface_for_low_frequency_relationship() -> None:
    source = {
        "source_title": "嗨，你最近还好吗",
        "source_summary": "旧关系从频繁相伴转为低频联系，牵挂仍然留在各自生活里。",
        "source_body_markdown": "有些人后来各自生活，联系从经常变成偶尔。看到晚霞和旧歌，仍会想起故人。",
        "analysis_structure_mode_hint": "response_priority",
        "analysis_theme": "旧关系如何从频繁相伴转为远距离牵挂。",
        "analysis_core_conflict": "想重新靠近又害怕打扰，不知道该以什么身份开口。",
        "analysis_emotional_exit": "允许彼此不常联系，也保留祝福和牵挂。",
        "analysis_opening_pattern": "从一处关系距离变化的现实接口切入。",
        "analysis_hook_trigger": "想联系却停在开口之前的那一下。",
        "analysis_progression_drive": "从身份困惑推进到联系减少，再回到低频关系里的安静牵挂。",
        "analysis_share_reason": "让曾经亲近、如今各自生活的人得到安定感。",
        "analysis_do_not_turn_into": "不要写成必须挽回或必须彻底切断的二选一。",
        "analysis_content_pillars": [
            "旧关系重启前的身份困惑",
            "生活迁移怎样让联系自然减少",
        ],
    }

    assert has_source_aligned_tracked_article_topic(
        **source,
        topic_title="那句最近还好吗，最后没有发出去",
        topic_angle="从输入框里的旧问候切入，写成年人如何面对渐远关系。",
    ) is False
    assert has_source_aligned_tracked_article_topic(
        **source,
        topic_title="旧友搬远以后，牵挂会换一种形状",
        topic_angle="从多年后偶然听见一首歌时的停顿切入，写联系减少后仍然保留的祝福与分寸。",
    ) is True


def test_complete_contract_surface_re_resolves_stale_mode_and_strips_low_frequency_shell() -> None:
    source = {
        "source_type": "tracked_article",
        "reference_article_title": "嗨，你最近还好吗",
        "reference_article_summary": "旧关系从频繁相伴转为低频联系，牵挂仍然留在各自生活里。",
        "reference_article_body_markdown": (
            "有些人，不是不想联系，只是该如何开口，又该以什么身份？"
            "看到晚霞和旧歌，仍会想起故人。"
        ),
        "reference_article_analysis_structure_mode": "response_priority",
        "reference_article_analysis_theme": "旧关系如何从频繁相伴转为远距离牵挂。",
        "reference_article_analysis_core_conflict": "想重新靠近又害怕打扰，不知道该以什么身份开口。",
        "reference_article_analysis_emotional_exit": "允许彼此不常联系，也保留祝福和牵挂。",
        "reference_article_analysis_opening_pattern": "从关系现场切入，以一条反复输入又删掉的问候起笔。",
        "reference_article_analysis_hook_trigger": "对话框里那句被反复修改、始终没有发出的近况问候。",
        "reference_article_analysis_progression_drive": "先写身份困惑，再通过晚霞、歌曲和故地说明低频联系中的牵挂。",
        "reference_article_analysis_share_reason": "让多年未联系的人得到安定感。",
        "reference_article_analysis_do_not_turn_into": "不要写成必须挽回或必须彻底切断的二选一。",
        "reference_article_analysis_content_pillars": [
            "未发出的问候呈现旧关系重启前的心理迟疑",
            "晚霞、歌曲和故地证明低频互动仍有牵挂",
        ],
    }

    surface = build_complete_contract_execution_surface(source)
    rendered = json.dumps(surface, ensure_ascii=False)

    assert surface["structure_mode"] == "emotional_engine_direct"
    assert "看似有人回应" not in rendered
    assert "对话框" not in rendered
    assert "问候" not in rendered
    assert "晚霞" not in rendered
    assert "歌曲" not in rendered
    assert "故地" not in rendered


def test_complete_contract_surface_drops_content_pillar_that_repeats_source_entry() -> None:
    source = {
        "source_type": "tracked_article",
        "reference_article_title": "得不到的巧克力，可能是命运的保护",
        "reference_article_summary": "文章借猫不能吃巧克力的寓言，讨论人如何接纳求不得。",
        "reference_article_body_markdown": "猫看见巧克力却不能吃，主人把它收起来，是为了保护它。",
        "reference_article_analysis_structure_mode": "emotional_engine_direct",
        "reference_article_analysis_theme": "停止把未得到当成命运亏欠。",
        "reference_article_analysis_core_conflict": "想追回失去，又需要承认某些东西并不适合自己。",
        "reference_article_analysis_emotional_exit": "把注意力收回当下正在经营的生活。",
        "reference_article_analysis_opening_pattern": "从寓言式故事切入，再转入人生判断。",
        "reference_article_analysis_hook_trigger": "被拒绝却不知道原因的错位感。",
        "reference_article_analysis_progression_drive": "从失去的反转推进到接纳。",
        "reference_article_analysis_share_reason": "给正在惦记失去的人一个重新安顿自己的角度。",
        "reference_article_analysis_do_not_turn_into": "不要把接纳写成对所有不公平的无条件服从。",
        "reference_article_analysis_content_pillars": [
            "用猫与巧克力的寓言呈现求不得者的认知盲区。",
            "把接纳落到对机会、关系和日常得失的重新排序。",
        ],
    }

    surface = build_complete_contract_execution_surface(source)
    rendered = json.dumps(surface, ensure_ascii=False)

    assert "猫与巧克力" not in rendered
    assert "吃巧克力" not in rendered
    assert "猫的困惑" not in rendered
    assert "求不得者的认知盲区" not in rendered
    assert "重新排序" in rendered


def test_observer_judgment_theme_is_not_trusted_as_trust_boundary_and_rejects_family_drift() -> None:
    source = {
        "source_title": "未经他人苦，莫劝他人善",
        "source_summary": "文章写旁观者不了解事实，却用轻飘的议论和大度要求覆盖当事人的伤痛。",
        "source_body_markdown": (
            "明明不懂你，却要对你说三道四；明明不了解发生了什么，却要劝你大度一点。"
            "有人把别人的难过当笑话，也有人没经历过他人的伤痛，却劝人算了、原谅。"
            "不必在意看客的眼光，把判断权留给自己。"
        ),
        "analysis_theme": "外界用无知的议论和廉价的宽容要求当事人消化伤害时，如何确认自己的感受。",
        "analysis_core_conflict": "受伤的人需要被理解，旁观者却用不了解事实的劝解替代支持。",
        "analysis_emotional_exit": "收回判断权，对不值得的人保留距离，把善意留给真正理解的人。",
        "analysis_opening_pattern": "从不了解却评价、没经历却劝解的现场切入。",
        "analysis_hook_trigger": "明明不懂你却急着替你下结论的那一下。",
        "analysis_progression_drive": "从轻飘议论与真实代价的落差推进到判断权回到当事人手里。",
        "analysis_share_reason": "让被劝大度的人知道，自己的感受不需要旁观者批准。",
        "analysis_do_not_turn_into": "不要写成单纯拒绝所有建议或鼓励以沉默对抗一切关系。",
        "analysis_content_pillars": [
            "旁观者如何把别人的处境当成轻松结论",
            "当事人如何从被评判里收回自己的判断权",
        ],
    }

    resolved = resolve_tracked_article_structure_mode(
        article_title=source["source_title"],
        body_markdown=source["source_body_markdown"],
        summary=source["source_summary"],
        analysis_structure_mode_hint="trust_boundary",
        **{key: source[key] for key in source if key.startswith("analysis_")},
        trust_complete_analysis_contract=True,
    )

    assert resolved == "observer_judgment_boundary"
    assert has_source_aligned_tracked_article_topic(
        **source,
        analysis_structure_mode_hint=resolved,
        topic_title="有些委屈，不必再向家人解释",
        topic_angle="从家庭群里一句都是一家人切入，写女性如何在不争吵中建立边界。",
    ) is False
    assert has_source_aligned_tracked_article_topic(
        **source,
        analysis_structure_mode_hint=resolved,
        topic_title="未经经历的人，别替你安排大度",
        topic_angle="从旁观者只看见结果的轻飘评价切入，写当事人如何把判断权收回自己手里。",
    ) is True


def test_build_strategy_package_rechecks_stale_generic_mode_against_observer_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "observer-strategy-mode-recheck",
            "topic_title": "被要求原谅时，先把判断权还给自己",
            "topic_angle": "从一次饭局上被要求和解的关系现场切入，写当事人如何拒绝轻率评价，把感受和判断权收回自己手里。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "未经他人苦，莫劝他人善",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章写旁观者不了解事实，却用轻飘的议论和大度要求覆盖当事人的伤痛。",
            "reference_article_structure_notes": "先写被议论和被劝大度的处境，再回到当事人收回判断权。",
            "reference_article_body_markdown": (
                "明明不懂你，却要对你说三道四；明明不了解发生了什么，却要劝你大度一点。"
                "有人把别人的难过当笑话，也有人没经历过他人的伤痛，却劝人算了、原谅。"
                "不必在意看客的眼光，把判断权留给自己。"
            ),
            # Simulate a persisted generic hint left by an older run.
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "人在遭遇痛苦时，如何拒绝未经了解的评价，重新把生活的判断权拿回自己手里。",
            "reference_article_analysis_core_conflict": "当事人正在承受真实代价，旁观者却用轻飘的劝解替他下结论。",
            "reference_article_analysis_emotional_exit": "不再被闲言碎语牵着走，把宽容留给值得的人，把注意力放回自己的生活。",
            "reference_article_analysis_opening_pattern": "从不了解却评价、没经历却劝解的现场切入。",
            "reference_article_analysis_hook_trigger": "明明不懂你却急着替你下结论的那一下。",
            "reference_article_analysis_progression_drive": "从轻率议论与真实代价的落差推进到判断权回到当事人手里。",
            "reference_article_analysis_share_reason": "让被劝大度的人知道，自己的感受不需要旁观者批准。",
            "reference_article_analysis_do_not_turn_into": "不要写成拒绝所有建议或鼓励以沉默对抗一切关系。",
            "reference_article_analysis_content_pillars": [
                "旁观者如何把别人的处境当成轻松结论",
                "当事人如何从被评判里收回自己的判断权",
            ],
            "reference_article_analysis_expression_profile": [
                "从关系现场切入，让判断从现实反馈里出现",
                "用短句和案例推进，不平铺抽象道理",
                "结尾回到自我确认和继续生活的动作",
            ],
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-08-05T00:00:00Z",
        trust_complete_analysis_contract=True,
    )

    assert result.strategy_card.structure_mode == "observer_judgment_boundary"


def test_build_strategy_package_simple_happiness_uses_updated_everyday_angle() -> None:
    result = build_strategy_package(
        project={
            "slug": "simple-happiness-strategy-project",
            "topic_title": "日子过到后来，有家人有知己就很踏实",
            "topic_angle": "人会一路追着更多拥有往前走，直到某个普通晚上被一顿热饭、一通惦记和一句到哪了轻轻接住，才重新看见家人平安、知己仍在的分量。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "人活着，不求大富大贵，但求简单快乐",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借幸福观的变化，讨论人到中年后对人生所求的重新排序：比起钱、排场和热闹，真正托住人的往往是健康、知己和家里的温度。",
            "reference_article_structure_notes": "开头先用人生发问和朴素愿望起势，中段分到知足、知己和一家温暖，结尾回到名利短暂、平安可贵。",
            "reference_article_body_markdown": (
                "人活着，到底是为了什么？家人安康，吃穿不愁，知己二三，四季平安。"
                "人生不求大富大贵，但求简单快乐。家人平安，知己仍在，饭桌上还有热气。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-12T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "everyday_warmth_return"
    combined = "\n".join(
        [
            result.problem_brief.problem_statement_markdown,
            result.strategy_card.strategy_markdown,
            result.strategy_card.body_shift,
            result.strategy_card.ending_move,
        ]
    )
    assert "一通惦记和一句到哪了轻轻接住" in combined
    assert "有人等你接回来" not in combined


def test_build_strategy_package_simple_happiness_keeps_reference_title_signal_when_body_is_lighter() -> None:
    result = build_strategy_package(
        project={
            "slug": "simple-happiness-light-body-project",
            "topic_title": "日子过到后来，有家人有知己就很踏实",
            "topic_angle": "人会一路追着更多拥有往前走，直到某个普通晚上被一顿热饭、一通惦记和一句到哪了轻轻接住，才重新看见家人平安、知己仍在的分量。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "人生不求大富大贵，但求简单快乐",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章主线是幸福不一定在更大的拥有里，常常就在平凡日常和家人知己身边。",
            "reference_article_structure_notes": "从幸福被误认成更大拥有切入，落到一餐一饭和陪伴。",
            "reference_article_body_markdown": (
                "人活着，到底是为了什么？人生苦短，只求心情愉悦，家人安康，吃穿不愁，知己二三，四季平安。\n\n"
                "生活简单就迷人，人心简单就幸福。\n\n"
                "人这一辈子，谁也争不过朝夕，财富、名利、地位不过是过眼云烟。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-15T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "everyday_warmth_return"
    assert "家人平安、知己仍在" in result.problem_brief.theme_axis
    assert "外在标准明明够了" in result.strategy_card.opening_move
    assert "朴素却很准确的生活愿望" in result.strategy_card.opening_move
    assert "继续投入" not in result.strategy_card.body_shift

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


def test_resolve_tracked_article_structure_mode_prefers_self_worth_rebuild_for_self_worth_article() -> None:
    body_markdown = (
        "有一段话说得很好：你爱自己的程度，决定了谁能走进你的人生。\n\n"
        "你越将就，遇见的人就对你越随便；你越讲究，遇见的人对你越认真。\n\n"
        "所以，要学会把自己养贵一点。把门槛抬高一点，把标准收紧一点，把精力多用来喂养自己。"
    )

    resolved = resolve_tracked_article_structure_mode(
        body_markdown=body_markdown,
        summary="文章真正想讨论的是：一个人在关系和生活里被怎样对待，往往和她是否尊重自己、是否守住边界与标准密切相关。",
        structure_notes="开头先借一句判断性引用立住前提，中段拆将就和贬值怎样慢慢发生，结尾回到尊重自己、抬高门槛和标准。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：很多轻慢并不是突然发生的，而是从一个人不断将就、不断放轻自己开始的。",
        analysis_core_conflict="一边是人总怕失去、总想证明自己值得被爱，另一边是边界、标准和体面在一次次迁就里被让出去。",
        analysis_emotional_exit="把精力从无效关系里收回来，重新尊重自己、守住边界，让日子慢慢变稳、变体面。",
        analysis_opening_pattern="从一句会让人停一下的判断性引语起笔，再落到现实里的将就接口。",
        analysis_do_not_turn_into="不要写成没时间回消息、谁先回头沟通或争吵后善后的关系表达稿。",
    )

    assert resolved == "self_worth_rebuild"


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


def test_resolve_tracked_article_structure_mode_promotes_scene_first_for_household_checklist_scene() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。\n\n"
            "很多家里的心事，不是不能说，只是总被那句‘明天再说吧’轻轻按住了。"
        ),
        summary="文章重点不是抽象讲放下，而是让读者先认出夜里回家、看见检查单、想问又收回去的那个晚上。",
        structure_notes="先把夜里回家、检查单、水壶、孩子睡了这些连续现场走完，再谈家里的沉默是怎么留下来的。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="这篇文章真正想讨论的是：家里的很多沉默，不是没有爱，而是总有人先把更重要的话往后压。",
        analysis_core_conflict="明明想问、也看见了对方的疲惫，可一回到那个晚上和那个家里的气氛里，人就先把更重要的话收回去。",
        analysis_emotional_exit="先让人认出自己是怎么把话一天天压后的，后面才谈家为什么要慢慢把心事说开。",
        analysis_opening_pattern="先从夜里回家和餐桌前的连续现场切入，再慢慢提判断。",
        analysis_do_not_turn_into="不要一开头就把它写成抽象关系道理。",
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
    assert result.strategy_card.point_of_view.startswith("不急着讲职场沟通技巧，先把一句话为什么总在会议室里被咽回去讲清楚。")
    assert "下笔时先围着这层矛盾推进" in result.strategy_card.point_of_view
    assert "表达需求压成了自我收缩" in result.strategy_card.point_of_view
    assert result.strategy_card.hook_trigger == "会还没散，你已经把那句更重要的话咽回去了。"
    assert "接口" not in result.strategy_card.hook_trigger
    assert result.strategy_card.packaging_hook.startswith("会还没散，你已经开始替那句没说出口的话收尾了。")
    assert "先抓" not in result.strategy_card.packaging_hook
    assert "包装优先" not in result.strategy_card.packaging_focus
    assert "会还没散" in result.strategy_card.packaging_focus
    assert all("接口" not in item for item in result.strategy_card.scene_anchor_requirements)
    assert "对外呈现：" in result.strategy_card.strategy_markdown
    assert "对外主钩子：" in result.strategy_card.strategy_markdown
    assert "画面锚点：" in result.strategy_card.strategy_markdown
    assert "包装抓手：" not in result.strategy_card.strategy_markdown
    assert "现实接口：" not in result.strategy_card.strategy_markdown
    assert result.strategy_card.body_shift.startswith("中段先拆那句话为什么在当场没说出口，再写散会后补邮件、补解释、自己兜底这套动作怎样把需求表达训练得越来越晚。")
    assert "中段优先把这层矛盾拆开" in result.strategy_card.body_shift
    assert "表达需求压成了自我收缩" in result.strategy_card.body_shift
    assert "从会议现场里那句想说又咽回去的话切入，重点写人为什么总在会上先替气氛和秩序让路，事后又把需求和补救一起揽回自己身上。" in result.problem_brief.problem_statement_markdown
    assert "越想稳住越累" not in result.problem_brief.problem_statement_markdown
    assert "不要把场景优先稿写成泛内耗、单人稳情绪或勇敢发声技巧稿。" in result.strategy_card.expression_constraints
    assert any("起笔方式" in item for item in result.strategy_card.writing_texture_notes)
    assert any("现场" in item or "动作" in item for item in result.strategy_card.writing_texture_notes)


def test_build_strategy_package_keeps_generic_scene_first_relationship_semantics() -> None:
    result = build_strategy_package(
        project={
            "slug": "scene-first-relationship-strategy-project",
            "topic_title": "没问出口的那句话，最容易把关系拖远",
            "topic_angle": "从地铁口等车、看见不对劲却还是先没问、上车后话题彻底沉下去这一段连续现场切入，写关系怎样在一次次没追问里慢慢把靠近让掉。",
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
    assert result.strategy_card.point_of_view.startswith("不急着给关系道理或沟通答案，先把那句为什么总在现场里被压回去讲清楚。")
    assert "下笔时先围着这层矛盾推进" in result.strategy_card.point_of_view
    assert "人还是先把更重要的话压后" in result.strategy_card.point_of_view
    assert result.strategy_card.hook_trigger == "明明就差一句，话到嘴边时，人还是先沉默了。"
    assert "接口" not in result.strategy_card.hook_trigger
    assert "标题、导语和封面先沿着这句起笔往前走" in result.strategy_card.packaging_focus
    assert all("接口" not in item for item in result.strategy_card.scene_anchor_requirements)
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


def test_resolve_tracked_article_structure_mode_detects_stage_restart_reference() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "过去的这半年，你过得好吗？年初定下的目标又实现了多少呢？若事与愿违，一定另有安排。\n\n"
            "下半年，多腾点时间和精力，去做好眼前之事，珍惜身边所爱之人。\n\n"
            "人生的每个阶段，其实都有得有失，有好有坏。我们能做的，就是接受并努力爱每一个阶段的自己。"
        ),
        summary="文章围绕半年节点回望、事与愿违另有安排、珍惜身边人和接纳每个阶段的自己，给人重新出发的勇气。",
        structure_notes="先写阶段节点上的自我盘点和遗憾，再转到珍惜眼前与接纳每个阶段的自己。",
        analysis_structure_mode_hint="emotional_engine_direct",
        analysis_theme="文章真正讨论的是：人为什么一到阶段节点就容易先否定自己。",
        analysis_core_conflict="很多人会把没完成、没拥有和没赶上一起算成失败。",
        analysis_emotional_exit="把遗憾安放好，把力气收回到眼前的人和接下来的生活里。",
        analysis_opening_pattern="从半年节点的自我盘点切入。",
        analysis_do_not_turn_into="不要改写成失恋复盘或泛泛心安稿。",
    )

    assert resolved == "inner_settlement"


def test_resolve_tracked_article_structure_mode_keeps_endings_acceptance_out_of_pressure_shell() -> None:
    resolved = resolve_tracked_article_structure_mode(
        body_markdown=(
            "很喜欢汪曾祺先生的一段话：逝去的从容逝去，重来的依旧重来。\n\n"
            "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。\n\n"
            "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
        ),
        summary="文章讨论关系结束后如何把失去从亏欠叙事里松开，重点不是劝人立刻忘记，而是接纳离开、保存相遇意义，并把留下来的温暖内化成继续往前的力量。",
        structure_notes="开头先借一句引文点出聚散有时，中段拆为什么人会替一段关系追讨完整定义，结尾回到感谢相遇、不谈亏欠和继续前行。",
        analysis_structure_mode_hint="pressure_interface_direct",
        analysis_theme="这篇文章真正想讨论的是：成年人如何把一段关系的结束，从失去和亏欠的叙事，转化为对相遇意义的接纳与内在消化。",
        analysis_core_conflict="真正让人反复受困的，不只是关系结束，而是对必须长久、必须有结果的执念，与关系本就会阶段性结束的现实之间的冲突。",
        analysis_emotional_exit="承认离别会疼，但不再把自己困在追问里，而是把关系中留下的温暖内化成继续前行的力量。",
        analysis_opening_pattern="以引语起笔，再从年轻时执着永远、后来才懂聚散有时切入主题。",
        analysis_do_not_turn_into="不要改写成劝人立刻放下的鸡汤安慰，也不要写成所有离开都值得感恩的强行升华。",
    )

    assert resolved == "emotional_engine_direct"


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
    assert "等外面的安慰" not in result.problem_brief.writing_goal
    assert "想求助" in result.problem_brief.writing_goal
    assert "别人的难处" in result.problem_brief.writing_goal
    assert "恢复判断和行动" in result.problem_brief.writing_goal
    assert "求助、分担" in result.problem_brief.writing_goal
    assert "自救自渡不是硬扛" in result.problem_brief.problem_statement_markdown
    assert "低谷里" in result.strategy_card.reader_situation
    assert "安顿住" in result.strategy_card.reader_situation
    assert "想解释，却越来越不想开口" not in result.strategy_card.reader_situation
    assert "越想解释越说不出口" not in result.problem_brief.writing_goal
    assert "真正把关系拖住的" not in result.strategy_card.conflict_frame
    assert "刚好有空的位置" not in result.strategy_card.body_shift
    assert "想求助" in result.strategy_card.body_shift
    assert "别人的难处" in result.strategy_card.body_shift
    assert "恢复判断" in result.strategy_card.emotional_path
    assert "求助分担" in result.strategy_card.emotional_path
    assert "想求助" in result.strategy_card.opening_move
    assert "真实接口" in result.strategy_card.opening_move
    assert "帮助未必赶得上" not in result.strategy_card.opening_move
    assert any("参考文章真正给出的现实触发点" in item for item in result.strategy_card.recomposition_recipe)
    assert any("主镜头更早落到当事人的判断、行动或回稳细节" in item for item in result.strategy_card.recomposition_recipe)
    assert any("正向动作、选择或判断" in item for item in result.strategy_card.recomposition_recipe)
    assert any("求助处境" in axis for axis in result.strategy_card.divergence_axes)
    assert all("无人帮忙" not in item for item in result.strategy_card.recomposition_recipe)
    assert all("求助落空" not in item for item in result.strategy_card.recomposition_recipe)
    assert all("关系误解" not in item for item in result.strategy_card.recomposition_recipe)
    assert all("无人帮忙" not in axis for axis in result.strategy_card.divergence_axes)
    assert all("关系误会" not in axis for axis in result.strategy_card.divergence_axes)
    assert any("回稳动作必须更早出现" in axis for axis in result.strategy_card.divergence_axes)


def test_build_strategy_package_keeps_self_worth_theme_out_of_response_priority_sink() -> None:
    result = build_strategy_package(
        project={
            "slug": "self-worth-strategy-project",
            "topic_title": "把自己养贵一点，不是高傲，而是别再把自己一再放轻",
            "topic_angle": "从一个人总说都可以、总先迁就、总怕让别人不高兴切入，写自我价值感偏低、边界一退再退时，人为什么会越来越容易被轻慢；也写怎样把尊重、标准和体面重新收回自己手里。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "把自己养贵一点，日子才能过好一点",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章真正想讨论的是：别人怎么对你，很多时候都和你是否尊重自己、是否守住边界和标准紧密相关。",
            "reference_article_structure_notes": "开头先从一句带判断性的引语立住前提，中段拆将就和降级怎样慢慢发生，结尾回到把自己养贵、立起边界和标准。",
            "reference_article_body_markdown": (
                "有一段话说得很好：你爱自己的程度，决定了谁能走进你的人生。\n\n"
                "你越将就，遇见的人就对你越随便；你越讲究，遇见的人对你越认真。\n\n"
                "所以，要学会把自己养贵一点。把门槛抬高一点，把标准收紧一点，把精力多用来喂养自己。"
            ),
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "文章真正想讨论的是：很多轻慢并不是突然发生的，而是从一个人不断将就、不断放轻自己开始的。",
            "reference_article_analysis_core_conflict": "一边是人总怕失去、总想证明自己值得被爱，另一边是边界、标准和体面在一次次迁就里被让出去。",
            "reference_article_analysis_emotional_exit": "把精力从无效关系里收回来，重新尊重自己、守住边界，让日子慢慢变稳、变体面。",
            "reference_article_analysis_opening_pattern": "从一句带判断性的引语起笔，再落到现实里的将就接口。",
            "reference_article_analysis_do_not_turn_into": "不要写成没时间回消息、谁先回头沟通或争吵后善后的关系表达稿。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "self_worth_rebuild"
    assert "边界" in result.problem_brief.writing_goal
    assert "标准" in result.problem_brief.writing_goal
    assert "尊重自己" in result.strategy_card.point_of_view
    assert "体面" in result.strategy_card.conflict_frame
    assert "重新收回自己这边" in result.strategy_card.emotional_path
    assert "边界、标准和体面" in result.strategy_card.body_shift
    assert "边界重新立住" in result.strategy_card.ending_move
    assert "精力终于收回自己手里" in result.strategy_card.ending_move
    assert "门槛被抬高" not in result.strategy_card.ending_move
    assert "顺序" not in result.strategy_card.conflict_frame
    assert "回消息" not in result.strategy_card.body_shift
    assert "善后" not in result.strategy_card.ending_move
    assert any("消息悬停" in item or "沟通表达" in item for item in result.strategy_card.expression_constraints)
    assert result.strategy_card.hook_trigger == "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。"
    assert "都可以" in result.strategy_card.opening_move


def test_build_strategy_package_turns_comment_followup_article_to_seen_and_understood_variant() -> None:
    result = build_strategy_package(
        project={
            "slug": "comment-followup-strategy-project",
            "topic_title": "真正让人踏实的，不是有人路过你，而是有人愿意停下来读懂你",
            "topic_angle": "从点赞、评论和一句“我没事”背后的分量差别切入，写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "真正关心你的人，会停下来读懂你没说完的话",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借点赞和评论的差别，讨论真正的在乎为什么不在热闹，而在有没有人愿意停下来、多问一句、读懂你没说完的话。",
            "reference_article_structure_notes": "开头先拆点赞和评论的差别，中段写表层互动和真正关心之间的落差，结尾落到谁会回来追问、谁会接住你没说完的话。",
            "reference_article_body_markdown": (
                "朋友圈里，是给你点赞的人更在意你，还是给你评论的人更在意你？\n\n"
                "而评论，却需要停下来，读懂你的言外之意。\n\n"
                "真正关心你的人，是哪怕相隔千里，也能透过你的一句“我没事”，听出你心底的“我有点累”。"
            ),
            "reference_article_analysis_structure_mode": "response_priority",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：在轻互动里，真正让人踏实的，不是热闹，而是有人愿意停下来读懂你。",
            "reference_article_analysis_core_conflict": "表面上大家都在互动，可真正让人安稳的，从来不是路过式回应，而是有人愿意把注意力和心力真正落到你这里。",
            "reference_article_analysis_emotional_exit": "让人重新认出真正的关心长什么样，也更愿意珍惜那些肯停下来理解自己的人。",
            "reference_article_analysis_opening_pattern": "从点赞和评论的差别起笔，再落到一句“我没事”背后其实藏着的疲惫。",
            "reference_article_analysis_do_not_turn_into": "不要写成谁更在乎你、谁把你排在前面的关系排序稿。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "response_priority"
    combined = "\n".join(
        [
            result.problem_brief.clarified_problem,
            result.problem_brief.writing_goal,
            result.problem_brief.problem_explanation,
            result.strategy_card.point_of_view,
            result.strategy_card.conflict_frame,
            result.strategy_card.emotional_path,
            result.strategy_card.opening_move,
            result.strategy_card.body_shift,
            result.strategy_card.ending_move,
            result.strategy_card.positive_direction,
        ]
    )

    assert "读懂" in combined or "理解" in combined
    assert "追问" in combined or "补问" in combined
    assert "安稳" in combined or "踏实" in combined or "珍惜" in combined
    assert "没时间" not in combined
    assert "红灯30秒" not in combined
    assert "优先级" not in combined
    assert "位置感" not in combined
    assert any("轻描淡写的话" in item or "被听懂" in item for item in result.strategy_card.scene_anchor_requirements)
    assert any("真正的关心" in item or "被理解" in item for item in result.strategy_card.quotable_line_seeds)


def test_build_strategy_package_trust_boundary_uses_trust_contract_fields() -> None:
    result = build_strategy_package(
        project={
            "slug": "trust-boundary-strategy-project",
            "topic_title": "信任一旦裂开，最该补上的不是解释，而是坦诚",
            "topic_angle": "从一句谎言、一次隐瞒让信任裂开那一下切入，写为什么信任不是不问不查，而是把心安交给了对方；也写一段关系想走得长久，最该靠坦诚、交代和说到做到把这份赤诚守住。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "信任很贵，请别辜负",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "信任很贵，请别辜负\n\n"
                "从前，他晚归，你不会多想；他手机响，你不会多看一眼。\n\n"
                "可是后来，一句谎言，一次隐瞒，那个叫信任的东西，就裂了一道缝。\n\n"
                "他不查你手机，是因为相信你；他不追问行踪，是因为不想给你压力。\n\n"
                "别把他的信任当成你任性的资本，更别辜负这份赤诚。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-12T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "trust_boundary"
    combined = "\n".join(
        [
            result.problem_brief.clarified_problem,
            result.problem_brief.observed_phenomenon,
            result.problem_brief.writing_goal,
            result.problem_brief.problem_explanation,
            result.strategy_card.reader_situation,
            result.strategy_card.point_of_view,
            result.strategy_card.conflict_frame,
            result.strategy_card.emotional_path,
            result.problem_brief.theme_axis,
            result.strategy_card.positive_direction,
            result.strategy_card.packaging_focus,
            result.strategy_card.packaging_hook,
            result.strategy_card.opening_move,
            result.strategy_card.body_shift,
            result.strategy_card.ending_move,
        ]
    )

    for required in ("信任", "坦诚", "隐瞒", "说到做到"):
        assert required in combined
    for forbidden in ("点赞", "评论", "读懂", "回消息", "没时间", "执念", "先抓一个具体入口", "自我亏欠"):
        assert forbidden not in combined
    assert result.strategy_card.hook_trigger == "听见前后两个版本时，手里的筷子会先停一下。"
    assert "真正卡住人的现实和情绪重心" not in result.problem_brief.theme_axis
    assert any("谎言" in item or "隐瞒" in item for item in result.strategy_card.scene_anchor_requirements)
    assert any("坦诚" in item or "说到做到" in item for item in result.strategy_card.quotable_line_seeds)


def test_build_strategy_package_exposes_positive_payoff_and_packaging_targets() -> None:
    result = build_strategy_package(
        project={
            "slug": "simple-happiness-positive-targets",
            "topic_title": "人到中年才懂，真正重要的，往往不是大事",
            "topic_angle": "从人为什么总被成就叙事推着走切入，写很多人是怎样在走了很远之后，才重新认出普通生活的分量。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "这些不起眼的小事，才是我们一生最重要的事",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章先写年轻时为什么总想做大事，中段让事业和身体的代价显出来，结尾回到人间烟火和家人陪伴。",
            "reference_article_structure_notes": "开头先拆成就叙事的吸引力，中段写大事祛魅，结尾回到小事与陪伴的重量。",
            "reference_article_body_markdown": (
                "年轻时，我们总觉得人生要轰轰烈烈。可走过半生才发现，真正重要的，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "世界很大，大到我们只是尘埃；世界也很小，小到一顿饭就能温暖两个人。"
            ),
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：很多人前半生被成就叙事推着走，后来才重新认出普通生活和身边人的分量。",
            "reference_article_analysis_core_conflict": "人一边相信大事才值得追，一边又在真正让自己热起来的小日常里后知后觉地回神。",
            "reference_article_analysis_emotional_exit": "把人从宏大执念里轻轻放回当下生活，重新珍惜已经拥有的陪伴与温度。",
            "reference_article_analysis_opening_pattern": "先从年轻时对大事和成就的想象切入。",
            "reference_article_analysis_do_not_turn_into": "不要写成泛心灵鸡汤或空泛知足文。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-03T00:00:00Z",
    )

    assert "不只明白道理" in result.problem_brief.emotional_value_goal
    assert "重新珍惜已经拥有的陪伴与温度" in result.strategy_card.positive_direction
    assert "贴着日常长出来的短判断" in result.strategy_card.quotable_line_goal
    assert "标题" in result.strategy_card.packaging_focus
    assert "普通生活" in result.strategy_card.packaging_focus
    assert "成就叙事" in result.problem_brief.theme_axis
    assert "空泛知足文" in result.problem_brief.anti_drift_axis
    assert any("家里日常接口" in item for item in result.strategy_card.scene_anchor_requirements)
    assert "前六段至少保住 2 个现实接口" in result.strategy_card.realism_texture_goal
    assert any("普通日常重新有分量" in item for item in result.strategy_card.quotable_line_seeds)
    assert "更大目标" in result.strategy_card.packaging_hook or "饭桌" in result.strategy_card.packaging_hook


def test_build_strategy_package_everyday_warmth_keeps_home_and_weather_sources_distinct() -> None:
    home_result = build_strategy_package(
        project={
            "slug": "simple-happiness-home-fingerprint",
            "topic_title": "人到中年才懂，真正重要的，往往不是大事",
            "topic_angle": "从人为什么总被成就叙事推着走切入，写很多人是怎样在走了很远之后，才重新认出普通生活的分量。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "这些不起眼的小事，才是我们一生最重要的事",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章先写年轻时为什么总想做大事，中段让事业和身体的代价显出来，结尾回到人间烟火和家人陪伴。",
            "reference_article_structure_notes": "开头先拆成就叙事的吸引力，中段写大事祛魅，结尾回到小事与陪伴的重量。",
            "reference_article_body_markdown": (
                "年轻时，我们总觉得人生要轰轰烈烈。可走过半生才发现，真正重要的，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "加完班回家，门一推开，屋里要是还有灯、还有热气、还有一句‘回来了’，心就会慢慢松下来。"
            ),
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：很多人前半生被成就叙事推着走，后来才重新认出普通生活和身边人的分量。",
            "reference_article_analysis_core_conflict": "人一边相信大事才值得追，一边又在真正让自己热起来的小日常里后知后觉地回神。",
            "reference_article_analysis_emotional_exit": "把人从宏大执念里轻轻放回当下生活，重新珍惜已经拥有的陪伴与温度。",
            "reference_article_analysis_opening_pattern": "先从年轻时对大事和成就的想象切入。",
            "reference_article_analysis_do_not_turn_into": "不要写成泛心灵鸡汤或空泛知足文。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )
    weather_result = build_strategy_package(
        project={
            "slug": "grandpa-weather-fingerprint",
            "topic_title": "真正能把人撑下去的，常常不是大道理，是那一点点被惦记",
            "topic_angle": "从人在异乡疲惫时，突然被一句叮嘱、一个惦记重新托住切入，写普通温暖为什么比空泛安慰更有力量。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "生活很苦，但总有一点甜能把人重新托住",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借爷爷每天看广州天气、提醒孙女暴雨天走路小心这件小事，写人在异乡承压时，为什么会被一句很普通的牵挂重新安慰到。",
            "reference_article_structure_notes": "先给异乡承压和坏天气，再落到天气预报、来电叮嘱和被惦记，最后写人为什么会被这种小温暖重新托住。",
            "reference_article_body_markdown": (
                "前阵子的广州，三天两头地下着暴雨，她心情也跟着天气一起变得很丧。\n\n"
                "这天，老家的爷爷打电话来叮嘱：这几天有暴雨，你出门走路千万当心点。我每天也看广州的天气预报呢。\n\n"
                "即使是坏天气，但只要想到爷爷的爱，心也就变得晴朗起来。"
            ),
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：人在很疲惫的时候，真正能把自己托住的，往往不是大而空的道理，而是那些很普通却很真切的牵挂和惦记。",
            "reference_article_analysis_core_conflict": "生活很苦、现实很重，可人真正重新有力气走下去的时候，常常是因为某个很小的被爱瞬间突然照亮了自己。",
            "reference_article_analysis_emotional_exit": "把读者从疲惫和发丧里带回一句普通叮嘱、一份被人惦记的踏实感，再慢慢走回生活里。",
            "reference_article_analysis_opening_pattern": "先从坏天气和异乡承压的现实处境切入，再落到那通电话和一句叮嘱。",
            "reference_article_analysis_do_not_turn_into": "不要改写成泛泛感恩文、家庭鸡汤或抽象正能量宣言。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )

    assert any("回家" in item and "家里日常接口" in item for item in home_result.strategy_card.scene_anchor_requirements)
    assert any("天气预报" in item and "被惦记接口" in item for item in weather_result.strategy_card.scene_anchor_requirements)
    assert any("回到家那一刻" in item or "小安稳" in item for item in home_result.strategy_card.quotable_line_seeds)
    assert any("惦记天气" in item or "坏天气里" in item for item in weather_result.strategy_card.quotable_line_seeds)
    assert "回家" in home_result.strategy_card.packaging_focus or "饭桌" in home_result.strategy_card.packaging_hook
    assert "天气预报" in weather_result.strategy_card.packaging_focus or "叮嘱" in weather_result.strategy_card.packaging_hook
    assert home_result.strategy_card.scene_anchor_requirements != weather_result.strategy_card.scene_anchor_requirements


def test_build_strategy_package_everyday_warmth_responsibility_shelter_variant() -> None:
    result = build_strategy_package(
        project={
            "slug": "responsibility-shelter-strategy-project",
            "topic_title": "中年人最深的安慰，不是有人替你扛，而是你扛住以后，家还在",
            "topic_angle": "从成年人总把“我没事”说得很轻切入，重点写中年责任为什么会让人咽下委屈、撑住疲惫，也写那些辛苦最后为什么会变成一家人的安稳。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "万般辛苦，皆为序章，人间安稳，终会如愿",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章围绕成年人把辛苦咽下去、把父母孩子伴侣的安稳顶在前面展开，重点不在控诉生活难，而在那些熬过去的夜后来怎样变成一个家的底气。",
            "reference_article_structure_notes": "先从一句“没事，有我”和账单电话这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳、有人被护住和这些辛苦没有白熬。",
            "reference_article_body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "白天的时候，你是父母的拐杖，是孩子的雨伞，是伴侣的靠山。你熬过的每一个黑夜，都在为身边所爱之人撑起一片晴空。\n\n"
                "人间安稳，从来不是没有风雨，而是风雨再大，你知道家在哪里，路再难走，你知道有人在爱你。"
            ),
            "reference_article_analysis_structure_mode": "everyday_warmth_return",
            "reference_article_analysis_theme": "文章真正想讨论的是：很多成年人把辛苦和委屈先往后收，不是因为不累，而是因为身后站着父母、孩子、伴侣和一个家。",
            "reference_article_analysis_core_conflict": "人明明已经很疲惫了，还是会把“我没事”顶在前面，把一家人的安稳先护住。",
            "reference_article_analysis_emotional_exit": "把读者从硬撑和发紧里带回家里仍被护住的安稳，也让人知道这些辛苦没有白熬。",
            "reference_article_analysis_opening_pattern": "先从一句轻描淡写的“没事，有我”和电话账单这些现实重量切入。",
            "reference_article_analysis_hook_trigger": "一句“没事，有我”背后那点喉咙发紧、却还得继续撑住的当场。",
            "reference_article_analysis_progression_drive": "责任怎样把人往前推，又怎样在父母、孩子、伴侣和家里的安稳里慢慢把辛苦说值。",
            "reference_article_analysis_share_reason": "它写出了很多成年人不会明说的辛苦，也给了继续撑下去的安慰。",
            "reference_article_analysis_do_not_turn_into": "不要改成放下执念、关系回应排序或泛中年励志稿。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-07T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "responsibility_shelter"
    assert "辛苦" in result.problem_brief.theme_axis or "家里" in result.problem_brief.theme_axis
    assert "疲惫先放到后面" not in result.problem_brief.theme_axis
    assert "我没事" not in result.problem_brief.theme_axis
    assert "安稳" in result.strategy_card.positive_direction
    assert "没事，有我" not in result.strategy_card.hook_trigger
    assert "理清" in result.strategy_card.hook_trigger or "家里临时有事" in result.strategy_card.hook_trigger
    assert "责任" in result.strategy_card.progression_drive
    assert "安慰" in result.strategy_card.share_reason
    assert any("来电" in item or "日历" in item or "请假" in item for item in result.strategy_card.scene_anchor_requirements)
    assert any("责任" in item or "家里" in item or "托稳" in item for item in result.strategy_card.quotable_line_seeds)
    assert "没事，有我" not in result.strategy_card.packaging_focus
    assert "没事，有我" not in result.strategy_card.packaging_hook
    assert "家里安稳" in result.strategy_card.packaging_focus or "家里" in result.strategy_card.packaging_hook
    assert "更大目标" not in result.strategy_card.packaging_focus

    combined = json.dumps(result.model_dump(), ensure_ascii=False)
    for forbidden in (
        "长期扛压",
        "不能倒",
        "不能倒下",
        "扛事",
        "多能扛",
        "白扛",
        "暂时不能倒",
        "为什么这么苦还要撑",
        "苦情赞歌",
        "辛苦没有白扛",
        "没事，有我",
        "硬撑",
        "硬扛",
    ):
        assert forbidden not in combined
    assert "更大目标" not in result.strategy_card.packaging_hook
    assert all("幸福被误判" not in item for item in result.strategy_card.quotable_line_seeds)
    assert "硬撑" not in result.strategy_card.quotable_line_goal
    assert "安稳" in result.strategy_card.quotable_line_goal or "踏实" in result.strategy_card.quotable_line_goal
    assert "放下执念" in result.problem_brief.anti_drift_axis
    assert "责任托家回温推进" in result.strategy_card.strategy_markdown
    assert "更大目标为什么会慢慢失重" not in result.strategy_card.strategy_markdown
    assert "成年人为什么会先把家里的事理顺" in result.problem_brief.problem_statement_markdown


def test_build_strategy_package_stage_restart_exposes_restart_specific_contract_and_structure() -> None:
    result = build_strategy_package(
        project={
            "slug": "stage-restart-strategy-project",
            "topic_title": "翻到年中清单时，别把几种遗憾算成同一种失败",
            "topic_angle": "从阶段节点上的自我清算切入，写人怎样重新安放遗憾、看见支撑，继续往前。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "这半年没按你想的那样来，也不代表你白走了一程",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借半年节点、事与愿违和身边仍在的牵挂，讨论人为什么总会在阶段回望里先否定自己。主线落在遗憾怎样被安放、眼前的人怎样把人托住，以及怎样重新接纳这个阶段的自己。",
            "reference_article_structure_notes": "先写阶段节点上的自我盘点和遗憾，再转到珍惜眼前与接纳每个阶段的自己。",
            "reference_article_body_markdown": (
                "过去的这半年，你过得好吗？年初定下的目标又实现了多少呢？若事与愿违，一定另有安排。\n\n"
                "下半年，多腾点时间和精力，去做好眼前之事，珍惜身边所爱之人。\n\n"
                "人生的每个阶段，其实都有得有失，有好有坏。我们能做的，就是接受并努力爱每一个阶段的自己。"
            ),
            "reference_article_analysis_structure_mode": "inner_settlement",
            "reference_article_analysis_theme": "文章真正讨论的是：人为什么一到阶段节点就容易先否定自己，后来又怎样把遗憾从自我定性里拆开，并被眼前生活和仍在身边的支撑慢慢托住。",
            "reference_article_analysis_core_conflict": "很多人会把没完成、没拥有和没赶上一起算成失败。",
            "reference_article_analysis_emotional_exit": "把遗憾安放好，把力气收回到眼前的人和接下来的生活里。",
            "reference_article_analysis_opening_pattern": "从半年节点的自我盘点切入。",
            "reference_article_analysis_do_not_turn_into": "不要改写成失恋复盘或泛心安稿。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "inner_settlement"
    assert "把遗憾安放好" in result.problem_brief.emotional_value_goal
    assert "阶段节点" in result.problem_brief.theme_axis
    assert "失恋复盘" in result.problem_brief.anti_drift_axis
    assert "继续" in result.strategy_card.positive_direction
    assert "下一步" in result.strategy_card.positive_direction
    assert "阶段节点上的自我误判" in result.strategy_card.packaging_focus
    assert "阶段误判" in result.strategy_card.quotable_line_goal
    assert any("阶段误判被认出来的那一下" in item for item in result.strategy_card.quotable_line_seeds)
    assert "阶段回望再出发推进" in result.strategy_card.strategy_markdown
    assert any("阶段节点" in item for item in result.strategy_card.writing_texture_notes)


def test_build_strategy_package_inner_settlement_keeps_stage_restart_and_daily_return_distinct() -> None:
    daily_return_result = build_strategy_package(
        project={
            "slug": "inner-settlement-daily-return-fingerprint",
            "topic_title": "很多事迟迟过不去，往往不是事情本身，而是那颗一直没松下来的心",
            "topic_angle": "从人为什么总想把过去想透、把未来想稳切入，写外界未必最糟时，那颗心为什么还是一直悬着。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "此心安处，才是一个人最好的归宿",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "reference_article_structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "reference_article_body_markdown": (
                "心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂。"
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
        created_at="2026-07-05T00:00:00Z",
    )
    stage_restart_result = build_strategy_package(
        project={
            "slug": "stage-restart-fingerprint",
            "topic_title": "翻到年中清单时，别把几种遗憾算成同一种失败",
            "topic_angle": "从阶段节点上的自我清算切入，写人怎样重新安放遗憾、看见支撑，继续往前。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "这半年没按你想的那样来，也不代表你白走了一程",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借半年节点、事与愿违和身边仍在的牵挂，讨论人为什么总会在阶段回望里先否定自己。主线落在遗憾怎样被安放、眼前的人怎样把人托住，以及怎样重新接纳这个阶段的自己。",
            "reference_article_structure_notes": "先写阶段节点上的自我盘点和遗憾，再转到珍惜眼前与接纳每个阶段的自己。",
            "reference_article_body_markdown": (
                "过去的这半年，你过得好吗？年初定下的目标又实现了多少呢？若事与愿违，一定另有安排。\n\n"
                "下半年，多腾点时间和精力，去做好眼前之事，珍惜身边所爱之人。\n\n"
                "人生的每个阶段，其实都有得有失，有好有坏。我们能做的，就是接受并努力爱每一个阶段的自己。"
            ),
            "reference_article_analysis_structure_mode": "inner_settlement",
            "reference_article_analysis_theme": "文章真正讨论的是：人为什么一到阶段节点就容易先否定自己，后来又怎样把遗憾从自我定性里拆开，并被眼前生活和仍在身边的支撑慢慢托住。",
            "reference_article_analysis_core_conflict": "很多人会把没完成、没拥有和没赶上一起算成失败。",
            "reference_article_analysis_emotional_exit": "把遗憾安放好，把力气收回到眼前的人和接下来的生活里。",
            "reference_article_analysis_opening_pattern": "从半年节点的自我盘点切入。",
            "reference_article_analysis_do_not_turn_into": "不要改写成失恋复盘或泛心安稿。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )

    assert any("一餐一饮" in item or "一呼一吸" in item for item in daily_return_result.strategy_card.scene_anchor_requirements)
    assert any("阶段节点" in item and ("清单" in item or "目标进度" in item) for item in stage_restart_result.strategy_card.scene_anchor_requirements)
    assert any("把心放回今天" in item or "今晚不必把所有事想明白" in item for item in daily_return_result.strategy_card.quotable_line_seeds)
    assert any("这一程白走" in item or "把力气收回眼前" in item for item in stage_restart_result.strategy_card.quotable_line_seeds)
    assert "一餐一饮" in daily_return_result.strategy_card.packaging_focus or "把心放回今天" in daily_return_result.strategy_card.packaging_hook
    assert "阶段清单" in stage_restart_result.strategy_card.packaging_focus or "几项空着" in stage_restart_result.strategy_card.packaging_hook
    assert daily_return_result.strategy_card.quotable_line_seeds != stage_restart_result.strategy_card.quotable_line_seeds


def test_build_strategy_package_endings_acceptance_stays_on_goodbye_meaning() -> None:
    result = build_strategy_package(
        project={
            "slug": "endings-acceptance-strategy-project",
            "topic_title": "总想要一个交代的人，最后最难收回的是自己的生活",
            "topic_angle": "很多人迟迟走不出来，并非失去本身太重，而是一直把每次离开当成失败处理；这篇稿子要拆开这种“必须有交代”的执念，帮读者把得到过的部分重新认领回来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "感谢相遇，不谈亏欠",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章讨论关系结束后如何把失去从亏欠叙事里松开，重点不是劝人立刻忘记，而是接纳离开、保存相遇意义，并把留下来的温暖内化成继续往前的力量。",
            "reference_article_structure_notes": "开头先借引语点出聚散有时，中段拆为什么人会替一段关系追讨完整定义，结尾回到感谢相遇、不谈亏欠和继续前行。",
            "reference_article_body_markdown": (
                "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。\n\n"
                "真正的成熟，不是变得麻木，而是允许一切发生，也允许一切结束。\n\n"
                "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
            ),
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：成年人如何把一段关系的结束，从失去和亏欠的叙事，转化为对相遇意义的接纳与内在消化。",
            "reference_article_analysis_core_conflict": "真正让人反复受困的，不只是关系结束，而是对必须长久、必须有结果的执念，与关系本就会阶段性结束的现实之间的冲突。",
            "reference_article_analysis_emotional_exit": "承认离别会疼，但不再把自己困在追问里，而是把关系中留下的温暖内化成继续前行的力量。",
            "reference_article_analysis_opening_pattern": "以引语起笔，再从年轻时执着永远、后来才懂聚散有时切入主题。",
            "reference_article_analysis_do_not_turn_into": "不要改写成劝人立刻放下的鸡汤安慰，也不要写成所有离开都值得感恩的强行升华。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-01T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "emotional_engine_direct"
    assert any(token in result.problem_brief.writing_goal for token in ("交代", "完整说法", "白费", "相遇"))


def test_build_strategy_package_enriches_same_structure_mode_with_analysis_specific_guidance() -> None:
    acceptance_result = build_strategy_package(
        project={
            "slug": "endings-acceptance-analysis-contract",
            "topic_title": "总想要一个交代的人，最后最难收回的是自己的生活",
            "topic_angle": "很多人迟迟走不出来，并非失去本身太重，而是一直把每次离开当成失败处理；这篇稿子要拆开这种“必须有交代”的执念，帮读者把得到过的部分重新认领回来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "感谢相遇，不谈亏欠",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章讨论关系结束后如何把失去从亏欠叙事里松开。",
            "reference_article_structure_notes": "开头先借引语点出聚散有时，中段拆为什么人会替一段关系追讨完整定义，结尾回到感谢相遇、不谈亏欠和继续前行。",
            "reference_article_body_markdown": (
                "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。\n\n"
                "真正的成熟，不是变得麻木，而是允许一切发生，也允许一切结束。\n\n"
                "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
            ),
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "这篇文章真正想讨论的是：成年人如何把一段关系的结束，从失去和亏欠的叙事，转化为对相遇意义的接纳与内在消化。",
            "reference_article_analysis_core_conflict": "真正让人反复受困的，不只是关系结束，而是对必须长久、必须有结果的执念，与关系本就会阶段性结束的现实之间的冲突。",
            "reference_article_analysis_emotional_exit": "承认离别会疼，但不再把自己困在追问里，而是把关系中留下的温暖内化成继续前行的力量。",
            "reference_article_analysis_opening_pattern": "以引语起笔，再从年轻时执着永远、后来才懂聚散有时切入主题。",
            "reference_article_analysis_do_not_turn_into": "不要改写成劝人立刻放下的鸡汤安慰，也不要写成所有离开都值得感恩的强行升华。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )
    regret_result = build_strategy_package(
        project={
            "slug": "regret-release-analysis-contract",
            "topic_title": "有些遗憾，不是拿来一直回头的",
            "topic_angle": "从人为什么总被‘如果当初’困住切入，写遗憾如何被安放，心力如何回到仍在继续的生活里。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "旧裙子收起来了，路还是要往前走",
            "reference_article_source_name": "manual-originality-check",
            "reference_article_summary": "文章借一位老人反复看旧裙子的细节，讨论人为什么总被‘如果当初’困住。",
            "reference_article_structure_notes": "开头从生活场景切入，用旧裙子的细节带出对过往遗憾的停留；中段扩展到普遍心理；结尾回到阿婆买新裙子的后续。",
            "reference_article_body_markdown": (
                "傍晚下楼扔垃圾，撞见邻居阿婆正蹲在垃圾桶旁，对着一袋旧衣物发呆。\n\n"
                "原来我们都一样，总爱攥着过去的遗憾不放，盯着没走成的路反复设想。\n\n"
                "你看，放下从来都不是遗忘，而是给心找一个更轻盈的去处。"
            ),
            "reference_article_analysis_structure_mode": "emotional_engine_direct",
            "reference_article_analysis_theme": "这篇文章真正想谈的是：人该怎样和已经无法更改的遗憾相处，才能不再被过去持续消耗。",
            "reference_article_analysis_core_conflict": "一边是人对错过的人、事、选择反复设想、迟迟不肯松手；另一边是现实已经无法回退，继续沉溺只会占用当下和未来的生活感受。",
            "reference_article_analysis_emotional_exit": "不必否认曾经在意过，也不必逼自己立刻忘掉，而是允许过去被安放，再把心力转回新的日常、新的关系和新的期待里。",
            "reference_article_analysis_opening_pattern": "从生活接口里的偶遇场景起笔，以邻居阿婆对旧衣物发呆的细节切入遗憾与回头心理。",
            "reference_article_analysis_do_not_turn_into": "不要改写成单纯鼓吹立刻断舍离、彻底忘掉过去的励志口号文。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-07-05T00:00:00Z",
    )

    assert acceptance_result.strategy_card.structure_mode == "emotional_engine_direct"
    assert regret_result.strategy_card.structure_mode == "emotional_engine_direct"
    assert "以引语起笔" in acceptance_result.strategy_card.opening_move
    assert "偶遇场景" in regret_result.strategy_card.opening_move
    assert "阶段性结束的现实之间的冲突" in acceptance_result.strategy_card.body_shift
    assert "现实已经无法回退" in regret_result.strategy_card.body_shift
    assert "继续前行的力量" in acceptance_result.strategy_card.packaging_focus
    assert "新的日常、新的关系和新的期待" in regret_result.strategy_card.packaging_focus
    assert acceptance_result.strategy_card.opening_move != regret_result.strategy_card.opening_move
    assert acceptance_result.strategy_card.body_shift != regret_result.strategy_card.body_shift
    assert any(token in acceptance_result.strategy_card.conflict_frame for token in ("相遇", "意义", "阶段性结束"))
    assert "身体告警" not in acceptance_result.strategy_card.opening_move
    assert "把自己排回前面" not in acceptance_result.strategy_card.ending_move
    assert "温暖" in acceptance_result.strategy_card.body_shift or "成长" in acceptance_result.strategy_card.body_shift


def test_build_strategy_package_removes_author_meta_voice_from_strategy_surfaces() -> None:
    result = build_strategy_package(
        project={
            "slug": "meta-voice-cleanup-project",
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
        created_at="2026-07-27T00:00:00Z",
    )

    combined = json.dumps(
        {
            "problem_brief": result.problem_brief.model_dump(),
            "strategy_card": result.strategy_card.model_dump(),
        },
        ensure_ascii=False,
    )

    for forbidden in (
        "这篇稿子要解释",
        "真正需要被看见",
        "如果这篇稿子成立",
        "这说的就是我现在的卡点",
        "## 这篇稿子真正要解释什么",
        "## 这篇稿子站在什么位置说话",
        "## 这篇要给读者什么情绪回报",
    ):
        assert forbidden not in combined

    assert "自救自渡不是硬扛" in combined
    assert "具体行动" in combined or "具体判断" in combined or "求助处境" in combined

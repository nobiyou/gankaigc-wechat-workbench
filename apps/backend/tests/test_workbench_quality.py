from types import SimpleNamespace

from app.services.ai_flavor import evaluate_ai_flavor_risk, extract_short_judgment_paragraphs
from app.services.workbench import (
    AssetItem,
    _apply_tracked_article_topic_rewrites,
    _build_local_generic_tracked_article_draft,
    _build_local_publish_package_fallback,
    _build_local_responsibility_shelter_draft,
    _resolve_local_generic_mode_closing,
    _has_author_meta_commentary,
    _has_obvious_repeated_character,
    _looks_like_explanatory_responsibility_shelter_title,
    _normalize_responsibility_shelter_draft_title,
    _sanitize_responsibility_shelter_result_fields,
    _has_unfinished_dialogue_sentence,
    _positive_payoff_candidate_rank,
    _repair_repeated_phrase_typo_residue,
    _sanitize_assets_packaging_result,
    _sanitize_responsibility_shelter_output_text,
    _sanitize_publish_packaging_result,
    _soften_not_ab_residue,
    _strip_draft_response_wrappers,
    _should_retry_assets_for_packaging,
    _should_retry_for_positive_payoff,
    _should_retry_publish_package_for_packaging,
    extract_not_ab_skeletons,
)


def _strategy(*, structure_mode: str, positive_direction: str) -> dict[str, object]:
    return {
        "problem_brief": {
            "emotional_value_goal": "让读者读完以后心里更有力量",
            "theme_axis": positive_direction,
            "anti_drift_axis": "不要写成泛泛的人生安慰",
        },
        "strategy_card": {
            "structure_mode": structure_mode,
            "positive_direction": positive_direction,
            "quotable_line_goal": "",
            "scene_anchor_requirements": [],
            "quotable_line_seeds": [],
            "realism_texture_goal": "",
            "packaging_hook": "",
        },
    }


def test_positive_payoff_requires_theme_specific_landing_for_everyday_warmth() -> None:
    strategy = _strategy(
        structure_mode="everyday_warmth_return",
        positive_direction="把人带回家人和普通生活的温暖",
    )

    assert _should_retry_for_positive_payoff(
        strategy_bundle_payload=strategy,
        candidate_markdown="日子还会继续，生活也会慢慢变好。",
    )


def test_positive_payoff_accepts_concrete_landing_without_external_quote() -> None:
    strategy = _strategy(
        structure_mode="everyday_warmth_return",
        positive_direction="把人带回家人和普通生活的温暖",
    )

    assert not _should_retry_for_positive_payoff(
        strategy_bundle_payload=strategy,
        candidate_markdown="饭还热着，家人就在身边。日子没有喧闹，却有很实在的安稳。",
    )


def test_local_everyday_warmth_draft_avoids_short_judgment_cadence() -> None:
    title, body_markdown = _build_local_generic_tracked_article_draft(
        {
            "source_type": "tracked_article",
            "article_title": "人生不求大富大贵，但求简单快乐",
            "topic_title": "日子过到后来，有家人有知己就很踏实",
            "topic_angle": "从人为什么总把幸福押在更大的拥有上切入，写一路追着体面和更多往前赶，最后却被家人平安、知己仍在和一顿热饭轻轻劝回来的过程。",
            "reference_article_body_markdown": (
                "人活着，到底是为了什么？人生苦短，只求心情愉悦，家人安康，吃穿不愁，知己二三，四季平安。"
                "人生不求大富大贵，但求简单快乐。生活简单就迷人，人心简单就幸福。"
            ),
            "strategy_card": {"structure_mode": "everyday_warmth_return"},
        }
    )

    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)

    assert len(extract_short_judgment_paragraphs(body_markdown)) <= 2
    assert all("单句敲钟段偏多" not in hit for hit in summary.hits)
    assert all("短促判断段偏多" not in hit for hit in summary.hits)
    assert summary.score < 30


def test_local_self_reliance_draft_avoids_cliche_and_slogan_finish() -> None:
    title, body_markdown = _build_local_generic_tracked_article_draft(
        {
            "source_type": "tracked_article",
            "topic_title": "成年人最清醒的底气，是能把自己稳稳托住",
            "topic_angle": "从想倾诉却发现大家都在各自负重切入，写成年人怎样把力气收回自己手里，用具体行动接住眼前生活。",
            "reference_article_body_markdown": (
                "心情不好的时候想找朋友倾诉，却发现朋友也在为你不知道的事情担忧焦虑。"
                "工作上遇到麻烦想找人商量，却发现身边的人也都在焦头烂额。"
                "只有向内求，才能自我疗愈，生生不息。即使没有帮助，也不会孤立无援，而是能够自救自渡。"
            ),
            "analysis_structure_mode": "self_reliance_inward_support",
        }
    )

    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)

    assert "愿你" not in body_markdown
    assert any(anchor in body_markdown for anchor in ("向内求", "自救", "求助", "分担", "判断回来了"))
    for stale in ("主心骨", "人心里有了光", "日子才会一点点变亮", "很多事就有了下一步"):
        assert stale not in body_markdown
    assert all("万能成长套话" not in hit for hit in summary.hits)
    assert all("结尾口号感" not in hit for hit in summary.hits)
    assert summary.score == 0


def test_local_generic_mode_closing_uses_action_instead_of_wish_slogans() -> None:
    closings = {
        mode: _resolve_local_generic_mode_closing(mode)
        for mode in (
            "resilience_reconstruction",
            "emotional_engine_direct",
            "scene_first_progression",
            "unknown_mode",
        )
    }
    combined = "\n\n".join(closings.values())

    assert "愿你" not in combined
    assert "愿我们" not in combined
    assert "从今天开始" not in combined
    assert "第二天还肯站回起点" in closings["resilience_reconstruction"]
    assert "这一页合上" in closings["emotional_engine_direct"]
    assert "真话留在当场" in closings["scene_first_progression"]


def test_local_relationship_aftercare_draft_avoids_not_ab_and_short_judgment_cadence() -> None:
    title, body_markdown = _build_local_generic_tracked_article_draft(
        {
            "source_type": "tracked_article",
            "topic_title": "吵完以后，愿意回来把话说完",
            "reference_article_body_markdown": (
                "在生活中，无论多么相爱的人也免不了会吵架。"
                "有些人吵着吵着就散了，有些人则越吵越爱。"
                "好的关系，不是永远不吵架，而是争吵以后还想要继续走下去。"
            ),
            "strategy_card": {"structure_mode": "relationship_aftercare"},
        }
    )

    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)

    assert title == "吵完以后，愿意回来把话说完"
    assert len(extract_short_judgment_paragraphs(body_markdown)) <= 2
    assert all("不是A，是B" not in hit for hit in summary.hits)
    assert all("单句敲钟段偏多" not in hit for hit in summary.hits)
    assert "这不是输赢" not in body_markdown
    assert "心里有这段关系的人，不会让你独自站在那阵冷气里。" not in body_markdown
    assert summary.score < 20


def test_local_self_worth_luxury_draft_avoids_not_ab_skeleton() -> None:
    title, body_markdown = _build_local_generic_tracked_article_draft(
        {
            "source_type": "tracked_article",
            "topic_title": "把自己看重一点，关系里的分寸才会回来",
            "topic_angle": "从把自己养贵一点、把门槛和标准收回来切入。",
            "reference_article_body_markdown": (
                "你不贵重，就容易被忽略；你不自爱，就是会被辜负。"
                "总把时间贱卖给不值得的人和事，只会越忙越廉价。"
                "把自己养贵一点，日子才能过好一点。"
            ),
            "strategy_card": {"structure_mode": "self_worth_rebuild"},
        }
    )

    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)

    assert title == "把自己看重一点，关系里的分寸才会回来"
    assert all("不是A，是B" not in hit for hit in summary.hits)
    assert "不是突然端着" not in body_markdown
    assert "门槛不是拿来为难别人的" not in body_markdown
    assert "不是高傲，是清醒" not in body_markdown
    assert summary.score < 20


def test_local_response_priority_time_draft_avoids_not_ab_skeleton() -> None:
    title, body_markdown = _build_local_generic_tracked_article_draft(
        {
            "source_type": "tracked_article",
            "topic_title": "愿意把时间留给你的人，才是真的把你放在心上",
            "reference_article_body_markdown": (
                "红灯30秒，我喝了一口水，拍了张照片，回了条消息。"
                "忙不是借口，没时间也不是理由。人对在乎的人，永远都有时间。"
            ),
            "strategy_card": {"structure_mode": "response_priority"},
        }
    )

    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)

    assert title == "愿意把时间留给你的人，才是真的把你放在心上"
    assert all("不是A，是B" not in hit for hit in summary.hits)
    assert "不是嘴上说出来的" not in body_markdown
    assert "不是催谁" not in body_markdown
    assert summary.score < 20


def test_local_response_priority_followup_publish_package_keeps_theme_and_avoids_not_ab() -> None:
    assets = AssetItem(
        project_slug="response-followup-project",
        draft_version=1,
        version=1,
        title_options=["你轻轻带过的话，值得有人认真接下去"],
        recommended_title="你轻轻带过的话，值得有人认真接下去",
        cover_prompt="16:9横版封面",
        cover_copy="你轻轻带过的话，有人真的听进去了。",
        social_teaser="那条晚霞发出去以后，最暖的不是那排点赞，是有人从“终于下班了”里听出了你的累。",
        social_teaser_options=["那条晚霞发出去以后，最暖的不是那排点赞，是有人从“终于下班了”里听出了你的累。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="你轻轻带过的话，值得有人认真接下去",
        draft_body_markdown=(
            "你发了一张晚霞照，本来只想轻轻带过一天。\n\n"
            "别人顺手点了赞，只有一个人问你：是不是项目又出岔子了？\n\n"
            "被这样追问一次，人就会知道什么叫被放在心上。"
        ),
        assets=assets,
    )
    combined = "\n\n".join(str(result.get(key) or "") for key in ("publish_lead", "abstract", "cover_title"))
    summary = evaluate_ai_flavor_risk(title=str(result["publish_title"]), body_markdown=combined)

    assert "晚霞" in str(result["publish_lead"])
    assert "多问一句" in str(result["publish_lead"])
    assert "主心骨" not in combined
    assert "眼前的路" not in combined
    assert all("不是A，是B" not in hit for hit in summary.hits)


def test_positive_payoff_keeps_relationship_theme_separate_from_home_warmth() -> None:
    strategy = _strategy(
        structure_mode="relationship_aftercare",
        positive_direction="把争执后的情绪带回沟通和继续走下去",
    )

    assert not _should_retry_for_positive_payoff(
        strategy_bundle_payload=strategy,
        candidate_markdown="吵过以后，愿意回来把话说完，关系才有修复的可能。",
    )


def test_packaging_does_not_let_a_generic_title_pass_on_cover_copy_alone() -> None:
    strategy = _strategy(
        structure_mode="everyday_warmth_return",
        positive_direction="把人带回家人和普通生活的温暖",
    )

    assert _should_retry_assets_for_packaging(
        strategy_bundle_payload=strategy,
        ai_result={
            "title_options": ["后来才懂，平淡最珍贵"],
            "recommended_title": "后来才懂，平淡最珍贵",
            "social_teaser": "电话一响，家里的安排就要重新排一遍。",
            "social_teaser_options": [],
            "cover_copy": "家人平安，就是最实在的日子",
        },
    )


def test_packaging_accepts_a_title_with_the_current_theme_entry() -> None:
    strategy = _strategy(
        structure_mode="relationship_aftercare",
        positive_direction="把争执后的情绪带回沟通和继续走下去",
    )

    assert not _should_retry_assets_for_packaging(
        strategy_bundle_payload=strategy,
        ai_result={
            "title_options": ["吵完以后，愿意回来把话说完"],
            "recommended_title": "吵完以后，愿意回来把话说完",
            "social_teaser": "关系真正的分量，常常落在争执后的那一步。",
            "social_teaser_options": [],
            "cover_copy": "愿意修复，才有继续走下去的可能",
        },
    )


def test_positive_payoff_retries_when_action_cues_have_become_a_fixed_rhythm() -> None:
    strategy = _strategy(
        structure_mode="self_reliance_inward_support",
        positive_direction="把力气慢慢收回自己身上，重新把今天过好",
    )
    repeated = "\n\n".join(
        [
            "先把事情记下来。",
            "先把电话打过去。",
            "先把饭吃完。",
            "先把明天安排好。",
            "先把情绪放一放。",
            "先把手里的事收一收。",
            "后来你才发现，自己已经走了很远。",
            "家里没有那么乱了。",
            "窗外的天也亮了一点。",
            "今天总算被你接住了。",
            "你终于能坐下来喘口气，也把自己稳住了。",
        ]
    )

    assert _should_retry_for_positive_payoff(
        strategy_bundle_payload=strategy,
        candidate_markdown=repeated,
    )


def test_unfinished_dialogue_sentence_is_detected_without_rejecting_normal_dialogue() -> None:
    assert _has_unfinished_dialogue_sentence("她只说了一句“我尽量”")
    assert not _has_unfinished_dialogue_sentence("她说：“我尽量。”")


def test_obvious_repeated_character_is_rejected_but_natural_repetition_is_allowed() -> None:
    assert _has_obvious_repeated_character("这句话把人接住住了。")
    assert not _has_obvious_repeated_character("日子慢慢稳下来，心也渐渐放松。")


def test_responsibility_shelter_packaging_requires_a_real_entry_in_the_title() -> None:
    strategy = _strategy(
        structure_mode="responsibility_shelter",
        positive_direction="把辛苦带回家里的灯和安稳",
    )

    assert _should_retry_assets_for_packaging(
        strategy_bundle_payload=strategy,
        ai_result={
            "title_options": ["万般辛苦，终会换来人间安稳"],
            "recommended_title": "万般辛苦，终会换来人间安稳",
            "social_teaser": "电话一响，家里的安排就要重新排一遍。",
            "social_teaser_options": [],
            "cover_copy": "家里有灯，辛苦就有了落点",
        },
    )


def test_publish_lead_rejects_editorial_meta_language() -> None:
    strategy = _strategy(
        structure_mode="responsibility_shelter",
        positive_direction="把辛苦带回家里的灯和安稳",
    )

    assert _should_retry_publish_package_for_packaging(
        strategy_bundle_payload=strategy,
        ai_result={
            "publish_title": "家里一有事，先把顺序理清",
            "publish_lead": "晚饭刚摆上，电话就响了。文章写的正是中年人的责任和安稳。",
            "abstract": "电话、日历和饭桌，把一个家的日子慢慢接住。",
            "intro_options": [],
        },
    )


def test_positive_payoff_retries_a_draft_far_below_the_active_length_target() -> None:
    strategy = _strategy(
        structure_mode="responsibility_shelter",
        positive_direction="把辛苦带回家里的灯和安稳",
    )
    short_but_positive = "\n\n".join(
        [
            "电话响起时，她先翻开日历，把家里的安排重新排了一遍。",
            "父母复查有人陪，孩子放学有人接，桌上的饭也还热着。",
            "这些认真最后落成了家里的安稳，也让她知道辛苦没有白费。",
        ]
    )

    assert _should_retry_for_positive_payoff(
        strategy_bundle_payload=strategy,
        candidate_markdown=short_but_positive,
        target_word_count=1400,
    )


def test_positive_payoff_rank_prefers_the_cleaner_candidate_closer_to_target_length() -> None:
    strategy = _strategy(
        structure_mode="responsibility_shelter",
        positive_direction="把辛苦带回家里的灯和安稳",
    )
    short = "家里一有事，她就翻开日历。最后，灯还亮着，饭还热着，日子也有了安稳。"
    expanded = "\n\n".join([short] * 14)

    assert _positive_payoff_candidate_rank(
        strategy_bundle_payload=strategy,
        candidate_markdown=expanded,
        target_word_count=1400,
    ) < _positive_payoff_candidate_rank(
        strategy_bundle_payload=strategy,
        candidate_markdown=short,
        target_word_count=1400,
    )


def test_body_rejects_author_meta_commentary() -> None:
    assert _has_author_meta_commentary("所以这篇不是想夸谁特别能吃苦，只是想说这些辛苦有人懂。")
    assert not _has_author_meta_commentary("饭桌上的灯还亮着，那些辛苦终于有了落点。")


def test_persistence_cleanup_strips_code_fence_and_duplicate_body_heading() -> None:
    body = "```markdown\n# 家里一有事，先把顺序理清\n\n电话响起时，她翻开了日历。\n```"

    assert _strip_draft_response_wrappers(
        title="家里一有事，先把顺序理清",
        body_markdown=body,
    ) == "电话响起时，她翻开了日历。"


def test_draft_cleanup_handles_no_feeling_reversal_and_repeated_phrase_typo() -> None:
    body = (
        "不是她没有感觉，是事情一来，她总得先把眼前这摊事安顿住。\n\n"
        "那个瞬间，心里的不容易和不容易未必能立刻讲清。"
    )

    softened = _soften_not_ab_residue(title="", body_markdown=body)
    repaired = _repair_repeated_phrase_typo_residue(title="", body_markdown=softened)

    assert extract_not_ab_skeletons(repaired) == []
    assert "不容易和不容易" not in repaired
    assert "事情一来，她总得先把眼前这摊事安顿住。" in repaired


def test_responsibility_shelter_output_cleanup_rewrites_awkward_residue_to_natural_text() -> None:
    body = (
        "这不是把苦说得多重，而是很多安排压在一起。"
        "有时候还会心里的不容易，觉得怎么总是自己在补位。"
    )

    cleaned = _sanitize_responsibility_shelter_output_text(body)

    assert "有时候还会心里的不容易" not in cleaned
    assert "觉得怎么总是自己在补位" not in cleaned
    assert "有时候还会觉得心里一紧" in cleaned
    assert "忍不住想：怎么总是自己在补位" in cleaned


def test_responsibility_shelter_output_cleanup_removes_symptomized_residue() -> None:
    cleaned = _sanitize_responsibility_shelter_output_text(
        "睡眠变浅、心里的不容易不说、情绪硬吞、身体先报警，这些都是一个人先顶着留下来的痕迹。"
    )

    assert "睡眠变浅" not in cleaned
    assert "情绪硬吞" not in cleaned
    assert "身体先报警" not in cleaned
    assert "话少了、安排更满了" in cleaned
    assert "也该给自己留一点余地" in cleaned


def test_responsibility_shelter_result_fields_rewrite_stale_local_titles() -> None:
    result = _sanitize_responsibility_shelter_result_fields(
        ai_result={
            "recommended_title": "家里一有事，你总会先把家稳住",
            "title_options": [
                "家里一有事，总是你先把顺序理出来",
                "家里一有事，你总先把顺序理出来",
            ],
            "social_teaser": "电话一响，你先想到父母那边谁陪、孩子这边谁接。",
        },
        title="中年人的世界，半生风雨，半生奔波",
        body_markdown=(
            "电话一响，你先把手里的事停了一下。还没接起来，心里已经在想爸妈那边谁去跑，孩子这周怎么接，"
            "这个月哪笔开销得先留出来。"
        ),
        reference_source_markdown=(
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，"
            "是每个月如期而至的各种账单。"
        ),
        text_fields=("recommended_title", "social_teaser"),
        list_fields=("title_options",),
    )

    assert result["recommended_title"] == "那通电话后，你先把家安顿好"
    assert result["title_options"] == ["那通电话后，你先把家安顿好", "那通电话后，你先把家安顿好"]


def test_responsibility_shelter_result_fields_prefer_already_normalized_short_title() -> None:
    result = _sanitize_responsibility_shelter_result_fields(
        ai_result={
            "recommended_title": "电话一响，先看日历的人",
            "title_options": [
                "电话一响，先看日历的人",
                "那通电话打来时，你先看的总是日历",
            ],
            "social_teaser": "电话响起来的时候，顾不上慌，先想的是哪件事能挪。",
        },
        title="电话一响，你先翻日历",
        body_markdown=(
            "电话响起来的时候，你常常顾不上慌。哪天能请假，哪个会得往后挪，谁去校门口，医院预约还能不能改。"
            "家里一有动静，你总会先把顺序理出来。"
        ),
        reference_source_markdown=(
            "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
        text_fields=("recommended_title", "social_teaser"),
        list_fields=("title_options",),
    )

    assert result["recommended_title"] == "电话一响，你先翻日历"
    assert result["title_options"][0] == "电话一响，你先翻日历"


def test_responsibility_shelter_result_fields_prefer_short_title_for_flip_calendar_person_variant() -> None:
    result = _sanitize_responsibility_shelter_result_fields(
        ai_result={
            "recommended_title": "先翻日历的人，还在把家托稳",
            "title_options": [
                "先翻日历的人，还在把家托稳",
                "电话一响，先想的是今天还能怎么挪",
            ],
            "social_teaser": "电话一响，先想的不是接不接，而是今天的安排还能怎么挪。",
        },
        title="电话一响，你先翻日历",
        body_markdown=(
            "电话一响，先想的不是接不接，而是今天的安排还能怎么挪。会议、回复、接送、看病、家里的开销与安稳，"
            "都挤在一张日历里。"
        ),
        reference_source_markdown=(
            "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
        text_fields=("recommended_title", "social_teaser"),
        list_fields=("title_options",),
    )

    assert result["recommended_title"] == "电话一响，你先翻日历"


def test_responsibility_shelter_result_fields_normalize_gendered_flip_calendar_title_to_you() -> None:
    result = _sanitize_responsibility_shelter_result_fields(
        ai_result={
            "recommended_title": "电话一响，他先翻日历",
            "title_options": ["电话一响，他先翻日历"],
            "social_teaser": "电话一响，先想的不是接不接，而是今天的安排还能怎么挪。",
        },
        title="电话一响，你先翻日历",
        body_markdown=(
            "电话一响，先想的不是接不接，而是今天的安排还能怎么挪。会议、回复、接送、看病、家里的开销与安稳，"
            "都挤在一张日历里。"
        ),
        reference_source_markdown=(
            "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
        text_fields=("recommended_title", "social_teaser"),
        list_fields=("title_options",),
    )

    assert result["recommended_title"] == "电话一响，你先翻日历"


def test_responsibility_shelter_result_fields_normalize_bare_flip_calendar_title_to_you() -> None:
    result = _sanitize_responsibility_shelter_result_fields(
        ai_result={
            "recommended_title": "电话一响，先翻日历",
            "title_options": ["电话一响，先翻日历"],
            "social_teaser": "电话刚响两声，脑子里已经把接送、复诊、缴费和请假排了一遍。",
        },
        title="电话一响，你先翻日历",
        body_markdown=(
            "电话刚响两声，脑子里已经把接送、复诊、缴费和请假排了一遍。"
            "家里临时有事时，最累人的往往不只是那件事本身，而是你总得先把人稳住、把顺序理清。"
        ),
        reference_source_markdown=(
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
        text_fields=("recommended_title", "social_teaser"),
        list_fields=("title_options",),
    )

    assert result["recommended_title"] == "电话一响，你先翻日历"


def test_explanatory_responsibility_title_flags_short_drifting_title_variant() -> None:
    assert _looks_like_explanatory_responsibility_shelter_title("电话一响，才懂自己认真走着什么")


def test_tracked_article_topic_rewrite_sanitizes_responsibility_shelter_long_title_and_meta_angle() -> None:
    payload = {
        "article_title": "中年人的世界，半生风雨，半生奔波",
        "summary": "",
        "structure_notes": "",
        "body_markdown": (
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，"
            "是每个月如期而至的各种账单。电话这头，你扛住压力，喉咙发紧，却只能说一句没事，有我。"
        ),
        "reference_article_body_markdown": (
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，"
            "是每个月如期而至的各种账单。电话这头，你扛住压力，喉咙发紧，却只能说一句没事，有我。"
        ),
    }

    result = _apply_tracked_article_topic_rewrites(
        payload,
        {
            "title": "你总把自己的难受往后排，家里为什么反而更稳了",
            "angle": "这篇想拆开你一接到父母、孩子、账单的消息就先排顺序的那一刻：很多责任感不是逞强。",
        },
    )

    assert result["title"] == "那通电话后，你先把家安顿好"
    assert "这篇想拆开" not in result["angle"]
    assert "电话那头是父母、孩子和账单" in result["angle"]


def test_normalize_responsibility_shelter_draft_title_prefers_scene_first_topic_title() -> None:
    title = _normalize_responsibility_shelter_draft_title(
        title="电话一响，你又把自己的事往后放了：原来你先顾家的那一下，不只是因为能扛",
        topic_title="电话一响，你先翻日历",
        project_title="电话一响，你先翻日历",
        body_markdown=(
            "下午还没到四点，电话就来了。你看了一眼日历里的安排，心里已经开始重新排序："
            "哪件能往后挪，谁那边要先顾，家里这一头怎么先稳住。"
        ),
        reference_source_markdown=(
            "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
    )

    assert title == "电话一响，你先翻日历"


def test_normalize_responsibility_shelter_draft_title_prefers_short_scene_title_when_candidate_is_longer() -> None:
    title = _normalize_responsibility_shelter_draft_title(
        title="那通电话打来时，你先看的总是日历",
        topic_title="电话一响，你先翻日历",
        project_title="电话一响，你先翻日历",
        body_markdown=(
            "母亲电话打来时，你多半还在工位上。那边声音压得很平，只说下周要去复查，问你哪天能陪一下。"
            "你嗯了一声，电脑上的表格还没关，手已经把日历往后翻了。"
            "周三下午那场会能不能挪，孩子放学谁去接，伴侣那天能不能早走半小时，医院上午还有没有号。"
        ),
        reference_source_markdown=(
            "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
    )

    assert title == "电话一响，你先翻日历"


def test_explanatory_responsibility_title_is_flagged_as_drift() -> None:
    assert _looks_like_explanatory_responsibility_shelter_title(
        "总把“先把家里理顺”挂在嘴边的人，后来为什么更不敢说自己累"
    )
    assert _looks_like_explanatory_responsibility_shelter_title(
        "你总想先把家里安顿好，代价其实是把自己的累一再往后放"
    )
    assert _looks_like_explanatory_responsibility_shelter_title(
        "你总说“我来处理”，后来家里安稳了，累却都留在你身上"
    )


def test_responsibility_shelter_output_cleanup_fixes_broken_continue_forward_phrase() -> None:
    cleaned = _sanitize_responsibility_shelter_output_text(
        "走到这一步才会明白，认真走着中年人继续往前的，除了肩上的责任，还有回头时那句踏实的回应。"
    )

    assert "认真走着中年人继续往前的" not in cleaned
    assert "支撑中年人继续往前的" in cleaned


def test_responsibility_shelter_output_cleanup_removes_meta_this_piece_language() -> None:
    cleaned = _sanitize_responsibility_shelter_output_text(
        "电话一响，先翻日历；事情一来，先想家里怎么安排。这份辛苦，往往是责任一直放不下。这篇写给今晚也在先把事情接住的你。"
    )

    assert "这篇写给" not in cleaned
    assert cleaned.endswith("这份辛苦，往往是责任一直放不下。")


def test_assets_packaging_sanitizer_drops_meta_teaser_options() -> None:
    result = _sanitize_assets_packaging_result(
        {
            "title_options": ["她越来越晚说累，是家里还需要她稳住"],
            "recommended_title": "她越来越晚说累，是家里还需要她稳住",
            "cover_prompt": "16:9横版封面",
            "cover_copy": "她不是不累\n只是还想先把家稳住",
            "social_teaser": "午休快结束的时候，手机响了，日历上的安排还没挪开。",
            "social_teaser_options": [
                "这篇文章想说的，是辛苦背后真正托住人的东西。",
                "日历越排越满，能说累的时候却越来越晚。",
            ],
        }
    )

    values = [str(result["social_teaser"]), *[str(item) for item in result["social_teaser_options"]]]
    assert all("这篇文章想说" not in value for value in values)
    assert result["social_teaser_options"] == [
        "午休快结束的时候，手机响了，日历上的安排还没挪开。",
        "日历越排越满，能说累的时候却越来越晚。",
    ]


def test_assets_packaging_sanitizer_strips_editorial_meta_from_primary_teaser() -> None:
    result = _sanitize_assets_packaging_result(
        {
            "title_options": ["电话一响，你先翻日历"],
            "recommended_title": "电话一响，你先翻日历",
            "cover_prompt": "16:9横版封面",
            "cover_copy": "电话响了 先看一眼日历",
            "social_teaser": (
                "母亲电话打来时，人还在工位上，手却先去翻日历。"
                "这篇想写的，是那种不能轻易停下的辛苦，也想认真说一句：累和苦都是真的，但这些奔忙，没有白费。"
            ),
            "social_teaser_options": [],
        }
    )

    assert "这篇想写的" not in str(result["social_teaser"])
    assert "想认真说一句" not in str(result["social_teaser"])
    assert str(result["social_teaser"]).endswith("累和苦都是真的，但这些奔忙，没有白费。")


def test_assets_packaging_sanitizer_strips_not_but_is_editorial_frame() -> None:
    result = _sanitize_assets_packaging_result(
        {
            "title_options": ["电话一响，你先翻日历"],
            "recommended_title": "电话一响，你先翻日历",
            "cover_prompt": "16:9横版封面",
            "cover_copy": "不是怕电话响 是怕日历排不开",
            "social_teaser": (
                "母亲的电话，偏偏是在你刚坐下那一下打来。"
                "这篇写的不是先把事情接住有多伟大，而是那些把家里安稳一点点托住的人，也该被看见、被理解。"
            ),
            "social_teaser_options": [],
        }
    )

    assert "这篇写的不是" not in str(result["social_teaser"])
    assert str(result["social_teaser"]).endswith("那些把家里安稳一点点托住的人，也该被看见、被理解。")


def test_assets_packaging_sanitizer_strips_write_through_explainer_language() -> None:
    result = _sanitize_assets_packaging_result(
        {
            "title_options": ["电话一响，你先翻日历"],
            "recommended_title": "电话一响，你先翻日历",
            "cover_prompt": "16:9横版封面",
            "cover_copy": "肩上有事，家里要稳",
            "social_teaser": "电话一响先看日历的人，往往不是怕麻烦，而是怕哪一头顾不上。文章写透中年人为什么一直扛，也写清楚：家里的安稳，原来真是这样一点点换来的。",
            "social_teaser_options": [],
        }
    )

    assert "文章写透" not in str(result["social_teaser"])
    assert "写清楚" not in str(result["social_teaser"])


def test_publish_packaging_sanitizer_replaces_meta_abstract() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["家里一有事，先稳住的人是你"],
        recommended_title="家里一有事，先稳住的人是你",
        cover_prompt="16:9横版封面",
        cover_copy="你先把顺序理出来\n家就稳了一点",
        social_teaser="电话一响，心里已经开始排顺序了。",
        social_teaser_options=["日历上的安排还没处理完，家里的电话又进来了。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "家里一有事，先把顺序理出来的人是你",
            "publish_lead": "电话一响，心里已经开始排顺序了。",
            "abstract": "文章写的是把责任说得多伟大，而是那些安排怎样托住家里。",
            "intro_options": ["这篇文章想说的是辛苦没有白费。"],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话一响，心里已经开始排顺序了。\n\n家里的安稳，就是这样一点点被托住。",
        assets=assets,
        fallback_title="家里一有事，先把顺序理出来的人是你",
    )

    assert "文章写的是" not in str(result["abstract"])
    assert "这篇文章想说" not in "".join(str(item) for item in result["intro_options"])
    assert result["abstract"] == "电话一响，心里已经开始排顺序了。"


def test_publish_packaging_sanitizer_strips_editorial_meta_abstract_clause() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话响了 先看一眼日历",
        social_teaser="母亲来电时，人还在工位上，手已经先去翻日历了。",
        social_teaser_options=["很多时候，顺序一乱，人就会下意识先把家里接住。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "母亲来电时，人还在工位上，手已经先去翻日历了。",
            "abstract": (
                "母亲来电、工位未离、手先去翻日历，这个细节里藏着中年人最真实的处境。"
                "文章从这份下意识的认真写起，落到一个更实在的答案——那些停不下来的辛苦，并不只是消耗自己。"
            ),
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="母亲来电时，人还在工位上，手已经先去翻日历了。\n\n那些停不下来的辛苦，也在一点点托住家里的安稳。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "文章从" not in str(result["abstract"])
    assert "写起" not in str(result["abstract"])
    assert str(result["abstract"]).endswith("那些停不下来的辛苦，并不只是消耗自己。")


def test_publish_packaging_sanitizer_strips_editorial_meta_from_lead() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话响了 先看一眼日历",
        social_teaser="电话响起来的时候，顾不上慌，先想的是哪件事能挪。",
        social_teaser_options=["真正压人的，往往是你得先把人稳住，再把顺序理清。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": (
                "电话响起来的时候，顾不上慌，先想的是哪件事能挪。"
                "文章想写的，正是这种不声张的承担：它有代价，也不是一句“懂事”就能带过。"
            ),
            "abstract": "一通电话打进来，先翻的不是情绪，而是日历、路程、孩子和今晚能不能按时到家。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话响起来的时候，顾不上慌，先想的是哪件事能挪。\n\n真正压人的，往往是你得先把人稳住，再把顺序理清。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "文章想写的" not in str(result["publish_lead"])
    assert "不声张的承担" in str(result["publish_lead"])


def test_publish_packaging_sanitizer_strips_meta_from_abstract_with_this_draft_phrase() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话响了 先看一眼日历",
        social_teaser="电话响起来的时候，顾不上慌，先想的是哪件事能挪。",
        social_teaser_options=["真正压人的，往往是你得先把人稳住，再把顺序理清。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "电话响起来的时候，顾不上慌，先想的是哪件事能挪。",
            "abstract": "电话在下午四点多打来，家里临时有事。这篇稿子要写的，不是逞强式的牺牲，而是你怎样把这个家接住。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话响起来的时候，顾不上慌，先想的是哪件事能挪。\n\n真正压人的，往往是你得先把人稳住，再把顺序理清。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "这篇稿子要写的" not in str(result["abstract"])


def test_publish_packaging_sanitizer_strips_write_to_the_end_editorial_phrase() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="不是怕电话响 是怕日历排不开",
        social_teaser="母亲的电话，偏偏是在你刚坐下那一下打来。",
        social_teaser_options=["你不是不想歇，只是先要看一眼日历：今天还能挪出什么，明天还能接住谁。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "母亲的电话，偏偏是在你刚坐下那一下打来。",
            "abstract": (
                "母亲的电话偏偏在你刚坐下那一下打来。"
                "这篇文章写的不是苦情，而是中年人那种无人可说的辛苦感。"
                "写到最后，会落回一个并不煽情的答案——那些及时接住的时刻，没有白费。"
            ),
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="母亲的电话，偏偏是在你刚坐下那一下打来。\n\n那些及时接住的时刻，没有白费。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "这篇文章写的不是" not in str(result["abstract"])
    assert "写到最后" not in str(result["abstract"])
    assert str(result["abstract"]).endswith("那些及时接住的时刻，没有白费。")


def test_publish_packaging_sanitizer_strips_this_article_written_is_phrase() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="肩上有安排，心里有家",
        social_teaser="电话打进来的那个瞬间，先冒出来的往往不是接不接，而是今天的会怎么调。",
        social_teaser_options=["先把顺序理清、再把日子托住的认真，会让家里的安稳继续运转。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "电话打进来的那个瞬间，先冒出来的往往不是接不接，而是今天的会怎么调。",
            "abstract": "电话打进来的那个瞬间，先冒出来的往往不是接不接，而是今天的会怎么调。这篇文章写的，是中年人那份先把顺序理清、再把日子托住的认真。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话打进来的那个瞬间，先冒出来的往往不是接不接，而是今天的会怎么调。\n\n先把顺序理清、再把日子托住的认真，会让家里的安稳继续运转。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "这篇文章写的" not in str(result["abstract"])


def test_publish_packaging_sanitizer_strips_write_clear_explainer_language() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="肩上有事，家里要稳",
        social_teaser="电话一响，先翻日历、先排顺序、先想哪一头不能耽误。",
        social_teaser_options=[],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "电话一响，先翻日历、先排顺序、先想哪一头不能耽误。",
            "abstract": "电话一响，先翻日历、先排顺序、先想哪一头不能耽误。这种下意识的动作，文章写的不是怕麻烦，而是中年人把责任扛在肩上的日常。讲清楚为什么真正沉的往往不是事情本身，而是要先稳住人、稳住家、稳住接下来每一步。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话一响，先翻日历、先排顺序、先想哪一头不能耽误。\n\n真正沉的往往不是事情本身，而是要先稳住人、稳住家、稳住接下来每一步。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "文章写的不是" not in str(result["abstract"])
    assert "讲清楚" not in str(result["abstract"])


def test_publish_packaging_sanitizer_strips_how_explainer_after_real_first_sentence() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话一响 你先翻日历",
        social_teaser="一天里最沉的那一下，常常不是忙，而是电话亮起的那一刻。",
        social_teaser_options=[],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "一天里最沉的那一下，常常不是忙，而是电话亮起的那一刻。",
            "abstract": "电话亮起的一刻，压下来的不只是临时状况，还有你脑子里立刻排开的时间、安排和家里的轻重缓急。讲成年人如何在一次次被需要里，把辛苦慢慢撑成一家人的安稳：稳住眼前的事，也稳住彼此可依靠的生活。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话亮起的一刻，压下来的不只是临时状况，还有你脑子里立刻排开的时间、安排和家里的轻重缓急。\n\n稳住眼前的事，也稳住彼此可依靠的生活。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "讲成年人如何" not in str(result["abstract"])
    assert str(result["abstract"]).endswith("稳住眼前的事，也稳住彼此可依靠的生活。")


def test_publish_packaging_sanitizer_rebuilds_abstract_when_using_article_borrowed_frame() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="你把不容易，换成了家里的安心",
        social_teaser="电话一响，先翻的不是消息，是日历。那些没说出口的为难，最后都变成了家里的安稳。",
        social_teaser_options=[],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "电话打进来的那个瞬间，你顾不上先回什么，手已经去翻日历了。",
            "abstract": "手机那头一句“没什么，你先上班”，真正让人紧起来的，往往不是事情本身，而是脑子里立刻排开的请假、车票、医院、孩子、父母和今天不能乱掉的安排。文章借“先翻日历”这个动作，写中年人如何在家里临时有事时先把人稳住、把顺序理清。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话打进来的那个瞬间，你顾不上先回什么，手已经去翻日历了。\n\n那些没说出口的为难，最后都变成了家里的安稳。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "文章借" not in str(result["abstract"])
    assert "写中年人如何" not in str(result["abstract"])


def test_publish_packaging_sanitizer_strips_write_midlife_meaning_frame() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话刚响两声，你心里已经开始过日子了",
        social_teaser="电话刚响两声，脑子里已经把接送、复诊、缴费和请假排了一遍。",
        social_teaser_options=[],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "电话刚响两声，脑子里已经把接送、复诊、缴费和请假排了一遍。",
            "abstract": "电话刚响两声，心里先排的不是情绪，而是接送、复诊、缴费、请假和谁先去顶上。写中年人先把事情接住的真正意义：未必是做出多大成绩，而是在家里临时有事时，能把人稳住、把日子接住。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="电话刚响两声，心里先排的不是情绪，而是接送、复诊、缴费、请假和谁先去顶上。\n\n能把人稳住、把日子接住。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "写中年人先把事情接住的真正意义" not in str(result["abstract"])


def test_publish_packaging_sanitizer_strips_not_just_a_phrase_intro() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话一响 先想安排的人 也被一盏灯接住",
        social_teaser="中年最让人发紧的几秒，常常出现在手机亮起以后。",
        social_teaser_options=[],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "电话一响，你先翻日历",
            "publish_lead": "中年最让人发紧的几秒，常常出现在手机亮起以后。",
            "abstract": "手机一亮，心里先紧一下；不是一句“中年不易”，而是那份总想先把家里稳住的认真，以及回到家看见灯亮着、饭热着时，辛苦终于有了着落。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="手机一亮，心里先紧一下。\n\n那份总想先把家里稳住的认真，以及回到家看见灯亮着、饭热着时，辛苦终于有了着落。",
        assets=assets,
        fallback_title="电话一响，你先翻日历",
    )

    assert "不是一句" not in str(result["abstract"])


def test_publish_packaging_sanitizer_keeps_abstract_as_complete_sentence() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["家里一有事，先稳住的人是你"],
        recommended_title="家里一有事，先稳住的人是你",
        cover_prompt="16:9横版封面",
        cover_copy="你先把顺序理出来\n家就稳了一点",
        social_teaser=(
            "手机那头还是那句“没事，你先忙”，可你已经开始想接下来该联系谁、先办哪件、哪一步不能乱。"
            "中年以后，真正托住人的，往往不是把难处扛得多漂亮，而是一次次把家里的慌乱理成秩序。"
            "那些认真过日子的年头，最后都会慢慢变成家里人的确定感。"
        ),
        social_teaser_options=[],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _sanitize_publish_packaging_result(
        {
            "publish_title": "家里一有事，先把顺序理出来的人是你",
            "publish_lead": "",
            "abstract": "文章写的是把责任说得多伟大，而是那些安排怎样托住家里。",
            "intro_options": [],
            "tags": ["家庭责任"],
            "publish_checklist": [],
            "editor_note": "",
        },
        draft_body_markdown="家里的安稳，就是这样一点点被托住。",
        assets=assets,
        fallback_title="家里一有事，先把顺序理出来的人是你",
    )

    assert result["abstract"].endswith("。")
    assert not str(result["abstract"]).endswith("托住。")
    assert "那些认真过日子的年头" not in str(result["abstract"])
    assert result["abstract"] == (
        "手机那头还是那句“没事，你先忙”，可你已经开始想接下来该联系谁、先办哪件、哪一步不能乱。"
        "中年以后，真正托住人的，往往不是把难处扛得多漂亮，而是一次次把家里的慌乱理成秩序。"
    )


def test_local_responsibility_publish_package_fallback_stays_scene_first() -> None:
    assets = AssetItem(
        project_slug="responsibility-project",
        draft_version=1,
        version=1,
        title_options=["电话一响，你先翻日历"],
        recommended_title="电话一响，你先翻日历",
        cover_prompt="16:9横版封面",
        cover_copy="电话一响，你先翻日历",
        social_teaser="电话刚响，心里已经开始排顺序了。",
        social_teaser_options=["电话一响，先翻的不是消息，是日历。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="电话一响，你先翻日历",
        draft_body_markdown=(
            "电话一响，你先翻日历。\n\n"
            "父母那边要陪，孩子这边要接，账单和请假也得一起挪。家里的顺序一乱，你就得先把人稳住。"
        ),
        assets=assets,
    )

    assert "电话" in str(result["publish_lead"])
    assert "家里的安排" in str(result["publish_lead"])
    assert "父母" in str(result["publish_lead"])
    assert "孩子" in str(result["publish_lead"])
    assert "家里临时有事" in str(result["abstract"]) or "电话" in str(result["abstract"])
    assert "写给" not in str(result["abstract"])


def test_local_response_priority_publish_package_fallback_keeps_abstract_distinct() -> None:
    assets = AssetItem(
        project_slug="response-project",
        draft_version=1,
        version=1,
        title_options=["谁对你有时间"],
        recommended_title="谁对你有时间",
        cover_prompt="16:9横版封面",
        cover_copy="谁对你有时间，谁就在心上",
        social_teaser="红灯30秒，他已经够回你一句话。",
        social_teaser_options=["有人把时间留给你，心就不会一直悬着。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="谁对你有时间",
        draft_body_markdown="红灯30秒，我喝了一口水，拍了张照片，回了条消息。\n\n真正的在乎，不会总让你一直等。没时间，只是有些人没把你排在前面。",
        assets=assets,
    )

    assert str(result["publish_lead"]) != str(result["abstract"])
    assert "把手机扣在桌上" in str(result["publish_lead"])
    assert "认真听完" in str(result["abstract"])


def test_local_response_priority_generic_publish_package_uses_a_quieter_care_scene() -> None:
    assets = SimpleNamespace(
        recommended_title="评论的分量",
        title_options=["评论的分量"],
        cover_copy="有人把你的话听完了。",
        social_teaser="有些回应只是路过，真正的在意会停下来。",
        social_teaser_options=["有人把你的话听完了。"],
    )

    result = _build_local_publish_package_fallback(
        draft_title="评论的分量",
        draft_body_markdown="有些回应只是路过，真正的在意会停下来。",
        assets=assets,
    )

    assert "把手机扣在桌上" in str(result["publish_lead"])
    assert "把你当成一个具体的人在珍惜" in str(result["abstract"])


def test_local_response_priority_publish_package_fallback_shortens_long_explanatory_title() -> None:
    assets = AssetItem(
        project_slug="response-project",
        draft_version=1,
        version=1,
        title_options=[
            "红灯30秒，我喝了一口水，拍了张照片，回了条消息，所以你告诉我，什么是没时间",
        ],
        recommended_title="红灯30秒，我喝了一口水，拍了张照片，回了条消息，所以你告诉我，什么是没时间",
        cover_prompt="16:9横版封面",
        cover_copy="谁对你有时间，谁就在心上",
        social_teaser="红灯30秒，他已经够回你一句话。",
        social_teaser_options=["有人把时间留给你，心就不会一直悬着。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="红灯30秒，我喝了一口水，拍了张照片，回了条消息，所以你告诉我，什么是没时间",
        draft_body_markdown="红灯30秒，我喝了一口水，拍了张照片，回了条消息。\n\n真正的在乎，不会总让你一直等。没时间，只是有些人没把你排在前面。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "真正在意你的人，会把话接下去"


def test_local_response_priority_time_priority_publish_package_fallback_uses_time_variant() -> None:
    assets = AssetItem(
        project_slug="response-time-project",
        draft_version=1,
        version=1,
        title_options=["愿意把时间留给你的人，才是真的把你放在心上"],
        recommended_title="愿意把时间留给你的人，才是真的把你放在心上",
        cover_prompt="16:9横版封面",
        cover_copy="愿意把时间留给你的人，心里早给你留了位置。",
        social_teaser="红灯30秒，他已经够回你一句话。",
        social_teaser_options=["有人把时间留给你，心就不会一直悬着。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="愿意把时间留给你的人，才是真的把你放在心上",
        draft_body_markdown="红灯30秒，我喝了一口水，拍了张照片，回了条消息。忙不是借口，没时间也不是理由。\n\n不是非要每条消息秒回，只是那句忙完找你，最好真的能补回来。",
        assets=assets,
    )

    assert "忙完以后回来找你" in str(result["publish_lead"])
    assert "你把在意递过去" in str(result["abstract"])
    assert "忙完找你" in str(result["abstract"])


def test_local_inner_settlement_publish_package_fallback_keeps_abstract_distinct() -> None:
    assets = AssetItem(
        project_slug="settle-project",
        draft_version=1,
        version=1,
        title_options=["把心放回今天"],
        recommended_title="把心放回今天",
        cover_prompt="16:9横版封面",
        cover_copy="把心放回今天",
        social_teaser="别急着把所有事今晚想完。",
        social_teaser_options=["心慢慢落回今天，日子就会稳一点。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="把心放回今天",
        draft_body_markdown="心若不安，到哪里都是流浪。\n\n先把饭吃好，把灯关好，把今天过完。",
        assets=assets,
    )

    assert str(result["publish_lead"]) != str(result["abstract"])
    assert "夜里屋里已经安静下来" in str(result["publish_lead"])
    assert "心先落回今天" in str(result["abstract"])
    assert "没那么吵了" in str(result["abstract"])


def test_local_pressure_interface_publish_package_fallback_routes_legacy_pressure_positive() -> None:
    assets = AssetItem(
        project_slug="pressure-project",
        draft_version=1,
        version=1,
        title_options=[
            "外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转",
        ],
        recommended_title="外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转",
        cover_prompt="16:9横版封面",
        cover_copy="先把那口气松下来，人才能回到自己身上",
        social_teaser="体检往后改一次，晚饭往后拖一次，复查提醒顺手划掉一次。",
        social_teaser_options=["白天还能把事做完，晚上先让心缓一缓。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转",
        draft_body_markdown="体检往后改一次，晚饭往后拖一次，复查提醒顺手划掉一次。\n\n外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转。白天还能把事做完、把话接住，可一回到安静里，那股累就会一下子冒出来。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "把被挪走的生活顺序，一点点调回来"
    assert "复查提醒弹出来" in str(result["publish_lead"])
    assert "把自己重新排回今天" in str(result["publish_lead"])
    assert "体检照约" in str(result["abstract"])
    assert "人先回稳" in str(result["abstract"])
    assert any("把复查约回日历" in item for item in result["intro_options"])
    forbidden = "耗空 身体先开始交代 胃口 睡眠变浅 孤立无援 外援 先把那口气松下来".split()
    combined = "\n".join(str(result[key]) for key in ("publish_title", "publish_lead", "abstract"))
    assert all(token not in combined for token in forbidden)

    generic_assets = SimpleNamespace(
        recommended_title="外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转",
        title_options=["外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转"],
        cover_copy="给自己留一个不必完成任何事的晚上。",
        social_teaser="日程表上的每一格都填满了，只有休息总被往后挪。",
        social_teaser_options=["给自己留一个不必完成任何事的晚上。"],
    )

    generic_result = _build_local_publish_package_fallback(
        draft_title="外面看着一切照常，真正先开始吃力的，往往是心里那套一直紧绷的运转",
        draft_body_markdown="工作和休息都被往后放，疲惫一直跟着你。后来你看起来还在照常生活，也该给自己留一个不必完成任何事的晚上。",
        assets=generic_assets,
    )

    assert "复查提醒弹出来" in str(generic_result["publish_lead"])
    assert "生活的顺序" in str(generic_result["abstract"])
    assert any("照顾自己不是暂停责任" in item for item in generic_result["intro_options"])
    generic_combined = "\n".join(str(generic_result[key]) for key in ("publish_title", "publish_lead", "abstract"))
    assert all(token not in generic_combined for token in forbidden)


def test_local_inner_settlement_publish_package_fallback_shortens_long_explanatory_title() -> None:
    assets = AssetItem(
        project_slug="settle-title-project",
        draft_version=1,
        version=1,
        title_options=["杨绛先生说，人生最曼妙的风景，是内心的淡定与从容"],
        recommended_title="杨绛先生说，人生最曼妙的风景，是内心的淡定与从容",
        cover_prompt="16:9横版封面",
        cover_copy="把心放回今天",
        social_teaser="别急着把所有事今晚想完。",
        social_teaser_options=["心慢慢落回今天，日子就会稳一点。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="杨绛先生说，人生最曼妙的风景，是内心的淡定与从容",
        draft_body_markdown="心若不安，到哪里都是流浪。\n\n先把饭吃好，把灯关好，把今天过完。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "把心放回今天，日子才会慢慢安稳"
    assert "人到后来才明白" not in str(result["publish_lead"])
    assert "忙完一天回到家" in str(result["publish_lead"])


def test_local_everyday_publish_package_fallback_shortens_long_explanatory_title_and_separates_summary() -> None:
    assets = AssetItem(
        project_slug="everyday-title-project",
        draft_version=1,
        version=1,
        title_options=["人活着，到底是为了什么？有一个最打动我的回答是这么说的"],
        recommended_title="人活着，到底是为了什么？有一个最打动我的回答是这么说的",
        cover_prompt="16:9横版封面",
        cover_copy="家里人平安，知己还在，平淡日子也很值得。",
        social_teaser="回家时那盏灯还亮着。",
        social_teaser_options=["家里人平安，爱的人在身边，日子就已经很值得。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="人活着，到底是为了什么？有一个最打动我的回答是这么说的",
        draft_body_markdown="回家时那盏灯还亮着，饭也还热着。\n\n家里人平安，知己还在，想说的话还有人听。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "有家人惦记，有知己可说，日子就很值得"
    assert str(result["publish_lead"]) != str(result["abstract"])
    assert "人活到后来" not in str(result["publish_lead"])
    assert "再普通的一天也会让人心里发暖" in str(result["abstract"])
    assert "一顿热饭、一句惦记" in str(result["abstract"])


def test_local_self_reliance_publish_package_fallback_shortens_long_explanatory_title() -> None:
    assets = AssetItem(
        project_slug="self-reliance-title-project",
        draft_version=1,
        version=1,
        title_options=["相信你也有过这样的时刻，想找人倾诉，却发现每个人都在各自扛事"],
        recommended_title="相信你也有过这样的时刻，想找人倾诉，却发现每个人都在各自扛事",
        cover_prompt="16:9横版封面",
        cover_copy="先把自己从慌里带出来",
        social_teaser="不是所有时候都有人腾得出手。",
        social_teaser_options=["先把这一晚过稳，很多事就会慢慢有了下一步。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="相信你也有过这样的时刻，想找人倾诉，却发现每个人都在各自扛事",
        draft_body_markdown="你不是不想开口，只是一回头，发现每个人手里都压着自己的事。\n\n先把饭吃完，把灯打开，把明天要用的东西放到手边。",
        assets=assets,
    )

    assert any(anchor in str(result["publish_title"]) for anchor in ("稳住", "求助", "自救", "扶稳", "眼前事"))
    assert any(anchor in str(result["publish_lead"]) for anchor in ("求助", "分担", "扶稳", "处理", "判断"))
    assert any(anchor in str(result["abstract"]) for anchor in ("求助", "自救", "分担", "判断", "行动", "扶稳"))
    assert "分担" in str(result["abstract"])
    for stale in ("先倒杯热水", "热水倒上", "桌面清出", "明天要用的东西", "主心骨", "重新有光", "下一步", "人心里有了光"):
        assert stale not in str(result["publish_lead"])
        assert stale not in str(result["abstract"])


def test_local_self_reliance_draft_removes_external_absence_template() -> None:
    title, body = _build_local_generic_tracked_article_draft(
        {
            "source_type": "tracked_article",
            "topic_title": "把力气收回自己手里，日子会慢慢变亮",
            "reference_article_title": "即使没有帮助，也要学会自救自渡",
            "reference_article_body_markdown": (
                "相信你也有过这样的时刻：心情不好的时候想找朋友倾诉，却发现朋友也愁眉不展。\n\n"
                "只有向内求，才能自我疗愈，生生不息。\n\n"
                "即使没有帮助，也不会孤立无援，而是能够自救自渡。"
            ),
        }
    )

    combined = f"{title}\n{body}"
    assert any(anchor in title for anchor in ("稳住", "求助", "自救", "扶稳"))
    assert "话到嘴边会先停一下" in combined or "聊天框打开又关上" in combined
    assert "照顾自己" in combined
    assert "请别人一起分担" in combined
    assert "求助不丢人，自救也不丢人" in combined
    for stale in (
        "别人赶来之前",
        "先把自己从慌里带出来",
        "外面的帮扶",
        "没人能",
        "没有人能",
        "每个人都在各自扛事",
        "想找人倾诉",
        "孤立无援",
        "主心骨",
        "人心里有了光",
        "日子也会一点点亮起来",
    ):
        assert stale not in combined


def test_local_responsibility_publish_package_fallback_shortens_long_explanatory_title() -> None:
    assets = AssetItem(
        project_slug="responsibility-title-project",
        draft_version=1,
        version=1,
        title_options=["中年人的世界，半生风雨，半生奔波"],
        recommended_title="中年人的世界，半生风雨，半生奔波",
        cover_prompt="16:9横版封面",
        cover_copy="肩上有责任，心里也要留一盏灯。",
        social_teaser="电话一响，你先翻日历。",
        social_teaser_options=["家里一有事，最先动起来的人，往往也是最晚说累的。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="中年人的世界，半生风雨，半生奔波",
        draft_body_markdown="电话一响，你先翻日历。\n\n父母那边要陪，孩子这边要接，账单和请假也得一起挪。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "那通电话后，你先把家安顿好"
    assert "电话刚响，脑子里就先把日历翻了一遍" not in result["intro_options"]


def test_local_responsibility_publish_package_fallback_uses_scene_specific_entry() -> None:
    assets = AssetItem(
        project_slug="responsibility-bill-scene-project",
        draft_version=1,
        version=1,
        title_options=["中年人的世界，半生风雨，半生奔波"],
        recommended_title="中年人的世界，半生风雨，半生奔波",
        cover_prompt="16:9横版封面",
        cover_copy="肩上有责任，心里也要留一盏灯。",
        social_teaser="账单摊开时，你先把今天排稳。",
        social_teaser_options=["账单摊开时，你先把今天排稳。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="中年人的世界，半生风雨，半生奔波",
        draft_body_markdown="账单摊在桌上时，你先把能调的地方调一调。\n\n父母那边要陪，孩子这边要接，今天也要一点点排稳。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "账单摊开时，你先把日子排稳"
    assert str(result["publish_lead"]).startswith("账单摊在桌上时")
    assert all("电话一响" not in str(item) for item in result["intro_options"])


def test_local_responsibility_publish_package_prefers_medical_scene_over_payment_word() -> None:
    assets = AssetItem(
        project_slug="responsibility-medical-scene-project",
        draft_version=1,
        version=1,
        title_options=["医院走廊里，你先让家人安心"],
        recommended_title="医院走廊里，你先让家人安心",
        cover_prompt="16:9横版封面",
        cover_copy="肩上有责任，心里也要留一盏灯。",
        social_teaser="医院走廊里，你先让家人安心。",
        social_teaser_options=["医院走廊里，你先让家人安心。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="医院走廊里，你先让家人安心",
        draft_body_markdown=(
            "父母在医院复查，缴费窗口前人很多。\n\n"
            "你先问医生，再看孩子放学谁去接，伴侣那边也要提前说一声。"
        ),
        assets=assets,
    )

    assert str(result["publish_title"]) == "医院走廊里，你先让家人安心"
    assert str(result["publish_lead"]).startswith("医院走廊")
    assert "复查" in str(result["abstract"])
    assert "账单摊" not in str(result["publish_lead"])
    assert "账单和开销" not in str(result["abstract"])


def test_local_responsibility_draft_uses_scene_entry_instead_of_phone_template() -> None:
    title, body = _build_local_responsibility_shelter_draft(
        {
            "source_type": "tracked_article",
            "topic_title": "账单摊开时，你先把日子排稳",
            "reference_article_body_markdown": (
                "孩子越来越高的补习费用，是每个月如期而至的各种账单。\n\n"
                "现实开销一项项摆到眼前，你还是先把能调整的地方重新排了一遍。\n\n"
                "桌上给你留着一口热饭，屋里有人问你累不累。"
            ),
        }
    )

    combined = f"{title}\n{body}"
    assert title == "账单摊开时，你先把日子排稳"
    assert "账单" in body
    assert any(token in body for token in ("开销", "缴费", "单子", "能调整"))
    assert "电话一响" not in combined
    assert "电话挂断" not in combined


def test_local_supportive_publish_package_fallback_shortens_long_explanatory_title() -> None:
    assets = AssetItem(
        project_slug="supportive-title-project",
        draft_version=1,
        version=1,
        title_options=["有一种人，习惯了燃烧自己，去照亮别人"],
        recommended_title="有一种人，习惯了燃烧自己，去照亮别人",
        cover_prompt="16:9横版封面",
        cover_copy="会先顾别人感受的人，也该被认真接住。",
        social_teaser="她不是没有脾气，只是每次都先把语气放轻一点。",
        social_teaser_options=["真正难得的，是有人看见她这一步。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="有一种人，习惯了燃烧自己，去照亮别人",
        draft_body_markdown="太好说话的人，不是天生就该让着谁。\n\n她愿意翻篇、愿意和好，很多时候只是把情分看得比一时的输赢更重。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "心软的人，值得被认真珍惜"
    assert "给这段关系一次机会" in str(result["abstract"])
    assert "没有让同一件事再发生" in str(result["abstract"])
    assert "愿意翻篇，是在给关系一次机会，不是在允许同一件事重来。" in result["intro_options"]


def test_local_resilience_publish_package_fallback_shortens_long_explanatory_title() -> None:
    assets = AssetItem(
        project_slug="resilience-title-project",
        draft_version=1,
        version=1,
        title_options=["《菜根谭》有云：士人有百折不回之真心，才有万变不穷之妙用"],
        recommended_title="《菜根谭》有云：士人有百折不回之真心，才有万变不穷之妙用",
        cover_prompt="16:9横版封面",
        cover_copy="熬过最难的那段路，你会重新长出自己的力量。",
        social_teaser="那段最难走的路，后来会慢慢长成你身上的力量。",
        social_teaser_options=["那些被生活按下去又重新起身的日子，会把人的筋骨慢慢养出来。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="《菜根谭》有云：士人有百折不回之真心，才有万变不穷之妙用",
        draft_body_markdown="真正的韧性，不是嘴上说不怕，而是被生活按回去很多次以后，还肯一次次把自己接起来。\n\n那些被生活按下去又重新起身的日子，会把人的筋骨慢慢养出来。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "熬过那段路，你会重新长出力量"
    assert "把鞋带系紧" in str(result["publish_lead"])
    assert "慢慢长成你自己的力量" in str(result["abstract"])
    assert "生活留下的缺口，不会替你决定余生。" in result["intro_options"]


def test_local_relationship_aftercare_publish_package_fallback_keeps_aftercare_specific_abstract() -> None:
    assets = AssetItem(
        project_slug="aftercare-project",
        draft_version=1,
        version=1,
        title_options=["吵完还愿意回来，才是关系里的温柔"],
        recommended_title="吵完还愿意回来，才是关系里的温柔",
        cover_prompt="16:9横版封面",
        cover_copy="吵完以后，屋里还冷着，可他还是回来了，把那句没说完的话接上。",
        social_teaser="吵完以后，屋里还冷着，可他还是回来了，把那句没说完的话接上。",
        social_teaser_options=["门口那一下回头，往往比争吵本身更能决定关系往哪走。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="吵完还愿意回来，才是关系里的温柔",
        draft_body_markdown="吵架停下来了，屋里却更冷了。\n\n如果每次都靠一个人回头、一个人缓和，那份想继续走下去的心，也会慢慢被耗掉。",
        assets=assets,
    )

    assert "把热水放到你手边" in str(result["publish_lead"])
    assert "把下次要改的地方记在心里" in str(result["abstract"])
    assert "热水放到手边的那一刻，关系已经开始往回走。" in result["intro_options"]


def test_local_scene_first_transit_publish_package_fallback_avoids_response_priority_wording() -> None:
    assets = AssetItem(
        project_slug="scene-project",
        draft_version=1,
        version=1,
        title_options=["很多关系不是输在大事上，而是输在那句当时没说出口的话上"],
        recommended_title="很多关系不是输在大事上，而是输在那句当时没说出口的话上",
        cover_prompt="16:9横版封面",
        cover_copy="很多距离，都是从一句话没说出口开始的。",
        social_teaser="她抬手拢了拢围巾，只说这阵子事多。",
        social_teaser_options=["那句该问的话，别总留到车开以后。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="很多关系不是输在大事上，而是输在那句当时没说出口的话上",
        draft_body_markdown="她抬手拢了拢围巾，只说这阵子事多。你听得出那句话后面还有东西，可嘴边那句真正想问的，还是被你自己按住了。\n\n关系不是在这一晚突然远掉的。更多时候，是你明明想再靠近一点，却还是先替对方把台阶铺好。",
        assets=assets,
    )

    assert "多问一句" not in str(result["abstract"])
    assert "那句该在当场说的话" in str(result["abstract"])


def test_local_publish_package_fallback_avoids_title_only_lead_and_abstract() -> None:
    assets = AssetItem(
        project_slug="memory-project",
        draft_version=1,
        version=1,
        title_options=["那段相遇还在"],
        recommended_title="那段相遇还在",
        cover_prompt="16:9横版封面",
        cover_copy="那段相遇还在",
        social_teaser="有些人走远了，还是会回来一下。",
        social_teaser_options=["有些人离开很久了，还是会在某个时刻想起。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="那段相遇还在",
        draft_body_markdown="有些人离开很久了，你还是会在某个普通时刻想起。感谢相遇，不谈亏欠。\n\n认真过的相遇，最后都会留下些什么。",
        assets=assets,
    )

    assert str(result["publish_lead"]) != "那段相遇还在"
    assert str(result["abstract"]) != "那段相遇还在"
    assert str(result["publish_lead"]) != str(result["abstract"])
    assert "被照亮过的那一下" in str(result["abstract"])
    assert "陪你去过后面的日子" in str(result["abstract"])


def test_local_emotional_presence_publish_package_fallback_uses_presence_title_and_abstract() -> None:
    assets = AssetItem(
        project_slug="memory-presence-project",
        draft_version=1,
        version=1,
        title_options=["有些人明明走远了，还是会在一个背影里轻轻回来"],
        recommended_title="有些人明明走远了，还是会在一个背影里轻轻回来",
        cover_prompt="16:9横版封面",
        cover_copy="有些人走远了，还是会在你的日常缝隙里轻轻回来一下。",
        social_teaser="灯火阑珊的街头，你只是多看了那个背影一眼，心里就忽然空了一下。",
        social_teaser_options=["原来有些人走远以后，并不会彻底消失，而是会在你最普通的日常里，轻轻回来一下。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="有些人明明走远了，还是会在一个背影里轻轻回来",
        draft_body_markdown="灯火阑珊的街头，你只是多看了那个背影一眼，心里就忽然空了一下。\n\n原来有些人走远以后，并不会彻底消失，而是会在你最普通的日常里，轻轻回来一下。",
        assets=assets,
    )

    assert str(result["publish_title"]) == "有些人走远了，还是会在一个背影里轻轻回来"
    assert "日常里留了个位置" in str(result["abstract"])
    assert "照常去赴约、去上班、去吃晚饭" in str(result["abstract"])


def test_local_emotional_reflux_publish_package_fallback_rewrites_template_summary() -> None:
    assets = AssetItem(
        project_slug="memory-reflux-project",
        draft_version=1,
        version=1,
        title_options=["你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉"],
        recommended_title="你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉",
        cover_prompt="16:9横版封面",
        cover_copy="那个突然想起的瞬间，是心里那段旧关系在轻轻回潮。",
        social_teaser="你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。",
        social_teaser_options=["反复回来的，常常是那段没说完的话和没被接住的自己。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉",
        draft_body_markdown="你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。\n\n反复回来的，常常是那段没说完的话和没被接住的自己。",
        assets=assets,
    )

    assert "停在半路的话" in str(result["abstract"])
    assert "不会总那么重" in str(result["abstract"])
    assert "想起并不丢人" not in str(result["abstract"])


def test_local_self_worth_publish_package_fallback_uses_self_worth_branch() -> None:
    assets = AssetItem(
        project_slug="worth-project",
        draft_version=1,
        version=1,
        title_options=["把自己看重一点"],
        recommended_title="把自己看重一点",
        cover_prompt="16:9横版封面",
        cover_copy="把自己看重一点",
        social_teaser="把自己看重一点，别再总往后退。",
        social_teaser_options=["总把自己往后让，别人也会顺着这个位置来对待你。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="把自己看重一点",
        draft_body_markdown="你越轻易把自己放低，别人越容易把你的体面当成可商量。\n\n把自己看重一点，关系里的分寸才会回来。",
        assets=assets,
    )

    assert "这次不行" in str(result["publish_lead"])
    assert "尊重你的不愿意" in str(result["abstract"])
    assert "能留下来的人，也会尊重你的不愿意。" in result["intro_options"]


def test_local_self_worth_luxury_publish_package_fallback_uses_luxury_branch() -> None:
    assets = AssetItem(
        project_slug="worth-luxury-project",
        draft_version=1,
        version=1,
        title_options=["把自己养贵一点，日子才能过好一点"],
        recommended_title="把自己养贵一点，日子才能过好一点",
        cover_prompt="16:9横版封面",
        cover_copy="把自己看重一点，关系里的分寸才会回来。",
        social_teaser="把自己养贵一点，日子才能过好一点。",
        social_teaser_options=["别总怕自己要求太多。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="把自己养贵一点，日子才能过好一点",
        draft_body_markdown="你越轻易把自己放低，别人越容易把你的体面当成可商量。\n\n门槛不是摆给别人看的，是用来提醒自己：什么该答应，什么不该将就。",
        assets=assets,
    )

    assert "什么能答应、什么不能退" in str(result["abstract"])
    assert "不会嫌你麻烦" in str(result["abstract"])
    assert "真正珍惜你的人，不会嫌你的边界麻烦。" in result["intro_options"]


def test_local_trust_publish_package_fallback_uses_less_template_summary() -> None:
    assets = AssetItem(
        project_slug="trust-project",
        draft_version=1,
        version=1,
        title_options=["信任很贵，请别辜负"],
        recommended_title="信任很贵，请别辜负",
        cover_prompt="16:9横版封面",
        cover_copy="信任很贵，别让赤诚输给含糊。",
        social_teaser="他不查你手机，是因为相信你。",
        social_teaser_options=["一句谎话落下来，当下也许还能把饭吃完，可心里那一下停顿，很久都过不去。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="信任很贵，请别辜负",
        draft_body_markdown="一句谎话落下来，当下也许还能把饭吃完，可心里那一下停顿，很久都过不去。\n\n信任不是一下碎掉的，是你后来每次听见差不多的话，心里都会先紧一下。",
        assets=assets,
    )

    assert "对方不用猜，也不用查" in str(result["abstract"])
    assert "比多少情话都难得" in str(result["abstract"])
    assert "坦荡认真守住" in str(result["abstract"])
    assert "一句话有人放心地信，胜过很多遍反复解释。" in result["intro_options"]
    assert all("不是不爱了" not in item for item in result["intro_options"])
    assert "信任不是一下碎掉的" not in str(result["abstract"])


def test_local_everyday_publish_package_fallback_prefers_home_scene_and_warmth_tags() -> None:
    assets = AssetItem(
        project_slug="everyday-project",
        draft_version=1,
        version=1,
        title_options=["有家人惦记的日子"],
        recommended_title="有家人惦记的日子",
        cover_prompt="16:9横版封面",
        cover_copy="晚饭热着，灯还亮着",
        social_teaser="回家时那盏灯还亮着。",
        social_teaser_options=["家里人平安，爱的人在身边，日子就已经很值得。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="有家人惦记的日子",
        draft_body_markdown="晚饭热着，灯还亮着。\n\n有家可回，有人可爱，日子就已经很值得。",
        assets=assets,
    )

    assert "灯还亮着" in str(result["publish_lead"]) or "饭也还热着" in str(result["publish_lead"])
    assert "人到后来才明白" not in str(result["publish_lead"])
    assert result["tags"] == ["生活温度", "家人相伴", "平凡幸福"]


def test_local_supportive_publish_package_fallback_stays_person_first() -> None:
    assets = AssetItem(
        project_slug="support-project",
        draft_version=1,
        version=1,
        title_options=["愿意包容你的人"],
        recommended_title="愿意包容你的人",
        cover_prompt="16:9横版封面",
        cover_copy="愿意包容你的人，也会累",
        social_teaser="她总是先把语气放轻。",
        social_teaser_options=["会先顾别人感受的人，也该被认真接住。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="愿意包容你的人",
        draft_body_markdown="她不是没有脾气，只是每次都先把话放轻一点。\n\n能让步的人，也想被人好好珍惜。",
        assets=assets,
    )

    assert "饭桌上的气氛刚有点僵" in str(result["publish_lead"])
    assert "把关系放在了输赢前面" in str(result["abstract"])
    assert "你也往前走一步，很多误会就能停在今晚。" in result["intro_options"]


def test_local_supportive_discernment_publish_package_fallback_avoids_template_summary() -> None:
    assets = AssetItem(
        project_slug="support-discernment-project",
        draft_version=1,
        version=1,
        title_options=["总把别人感受放在前面的人，其实最该被人好好珍惜"],
        recommended_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        cover_prompt="16:9横版封面",
        cover_copy="心软的人，也看得很清。",
        social_teaser="他不是没看出来，只是先把语气放软了。",
        social_teaser_options=["明明看得清，却还是想给关系留一点余地。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        draft_body_markdown="谁是真心，谁在敷衍，他其实都分得清。很多事他不是没看出来，只是关系摆在面前时，他总习惯先把语气放软。\n\n他愿意把那点难受先放一放，也想给关系留一次回来的机会。",
        assets=assets,
    )

    assert "看得清" in str(result["publish_lead"])
    assert "语气放软" in str(result["publish_lead"])
    assert "认真珍惜" in str(result["publish_lead"])
    assert "给关系留一点暖意" in str(result["abstract"])
    assert "听出你话里的敷衍" not in str(result["publish_lead"])
    assert "顺口应付" not in str(result["abstract"])


def test_local_trust_publish_package_fallback_uses_broken_trust_scene() -> None:
    assets = AssetItem(
        project_slug="trust-project",
        draft_version=1,
        version=1,
        title_options=["信任很贵，请别辜负"],
        recommended_title="信任很贵，请别辜负",
        cover_prompt="16:9横版封面",
        cover_copy="信任碎了，很难回到原样",
        social_teaser="信任这种东西，裂过一次，心里就会留下声响。",
        social_teaser_options=["不是不爱了，是怕了。"],
        cover_image_path="",
        cover_image_url="",
        cover_image_status="ready",
        cover_image_error=None,
        cover_image_route_label="primary",
        cover_image_route_model="gpt-image-2",
        cover_image_route_base_url="https://example.test/v1",
        created_at="2026-07-19T00:00:00Z",
        origin="generate",
        tone_profile_id=None,
        tone_profile_name=None,
    )

    result = _build_local_publish_package_fallback(
        draft_title="信任很贵，请别辜负",
        draft_body_markdown="一句谎言，一次隐瞒，那个叫信任的东西，就裂了一道缝。\n\n不是不爱了，是怕了。",
        assets=assets,
    )

    assert "谎话落下来" in str(result["publish_lead"])
    assert "对方不用猜，也不用查" in str(result["abstract"])
    assert "坦荡认真守住" in str(result["abstract"])

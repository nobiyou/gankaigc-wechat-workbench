from __future__ import annotations

from app.services.ai_flavor import (
    build_ai_flavor_polish_instruction,
    evaluate_ai_flavor_risk,
    extract_generic_reflective_openers,
    extract_growth_cliches,
    extract_not_ab_skeletons,
)


def test_evaluate_ai_flavor_risk_flags_templated_emotional_draft() -> None:
    summary = evaluate_ai_flavor_risk(
        title="你赌我不敢走，我赌你再也遇不到真诚的人",
        body_markdown=(
            "# 标题\n\n"
            "不是不爱，而是太久没有被看见。其实很多时候，关系崩塌不是从争吵开始，而是从一次赌气开始。\n\n"
            "你以为他懂，他以为你不在乎，所以两个人都在等对方先低头。换句话说，真正受伤的不是面子，而是那颗还想靠近的心。\n\n"
            "很多人会这样，一点委屈、一个沉默、一些误会，最后都变成一种谁也不肯先开口的僵持。\n\n"
            "从今天开始，别再赌气，愿你有话直说，成为不靠试探也能被懂的人。"
        ),
    )

    assert summary.level == "高"
    assert summary.score >= 60
    assert any("不是A，是B" in hit for hit in summary.hits)
    assert any("解释连接词偏多" in hit for hit in summary.hits)
    assert any("结尾口号感" in hit for hit in summary.hits)


def test_evaluate_ai_flavor_risk_flags_wishful_ending_slogans() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=(
            "# 标题\n\n"
            "前文。\n\n"
            "生活从不会倒带重演，但每个清晨都是新的开始。愿我们都能在时光的长河里，不错过健康，不辜负所爱。"
        ),
    )

    assert any("结尾口号感" in hit for hit in summary.hits)


def test_extract_generic_reflective_openers_returns_paragraph_level_hits() -> None:
    openers = extract_generic_reflective_openers(
        "# 标题\n\n"
        "很多时候，我们以为问题已经过去了。\n\n"
        "说到底，人真正舍不得的，还是那一点旧期待。\n\n"
        "最后回到具体动作。"
    )

    assert openers == ["很多时候", "说到底"]


def test_evaluate_ai_flavor_risk_flags_generic_reflective_transitions() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=(
            "# 标题\n\n"
            "很多时候，我们总以为明天还来得及。\n\n"
            "说到底，人最容易高估的，是自己还能再等等。\n\n"
            "最后回到一句平静收束。"
        ),
    )

    assert any("泛感慨过渡句偏多" in hit for hit in summary.hits)
    assert any("删掉部分“很多时候”“说到底”式过渡句" in suggestion for suggestion in summary.suggestions)


def test_extract_not_ab_skeletons_dedupes_sentence_bones() -> None:
    skeletons = extract_not_ab_skeletons(
        "# 标题\n\n"
        "不是你不想停下来，而是你总觉得还能再撑一阵。\n\n"
        "不是你不想停下来，而是你总觉得还能再撑一阵。\n\n"
        "不是记忆，是那种“以后再说”的底气。"
    )

    assert skeletons == [
        "不是你不想停下来，而是你总觉得还能再撑一阵",
        "不是记忆，是那种“以后再说”的底气",
    ]


def test_extract_growth_cliches_finds_retry_targets() -> None:
    cliches = extract_growth_cliches(
        "# 标题\n\n"
        "从今天开始，别再把重要的东西推到以后。愿你慢慢把生活接回来。"
    )

    assert cliches == ["从今天开始", "愿你"]


def test_evaluate_ai_flavor_risk_ignores_narrative_not_ab_sentences() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=(
            "# 标题\n\n"
            "后来见面，他说那一刻脑子里很空，先想到的甚至不是工作会不会耽误，而是原来身体真的会突然停下来，不会先跟你商量。\n\n"
            "真正卡住人的，往往也不是忙，而是总把活着放在后面，把以后想得太可靠。"
        ),
    )

    assert not any("不是A，是B" in hit for hit in summary.hits)


def test_evaluate_ai_flavor_risk_ignores_non_leading_yi_phrases_in_natural_prose() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别让赌气毁掉关系",
        body_markdown=(
            "# 标题\n\n"
            "看到一句话：“你赌我，没有当断则断的勇气；我赌你，再也遇不到一个像我这么真诚的人！”\n\n"
            "读到这句时，心里会沉一下。\n\n"
            "表面看，是在争谁先低头。真到了心里，其实是在等一句确认：你会不会来哄我。\n\n"
            "感情里真正让人松一口气的，从来不是谁压过了谁，而是至少彼此用的是同一种方式：沟通，不是较劲。\n\n"
            "如果你现在就在一段发僵的关系里，也许先不用急着判断值不值得。"
        ),
    )

    assert not any("一”字节奏偏密" in hit for hit in summary.hits)


def test_evaluate_ai_flavor_risk_flags_clause_leading_yi_cadence() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别让赌气毁掉关系",
        body_markdown=(
            "# 标题\n\n"
            "很多人会这样，一点委屈、一个沉默、一些误会，最后都被拖成僵持。\n\n"
            "消息停在那儿，一下删掉，一遍重写，一个字一个字往回吞。"
        ),
    )

    assert any("一”字节奏偏密" in hit for hit in summary.hits)


def test_evaluate_ai_flavor_risk_ignores_non_leading_connectors_in_natural_prose() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别让赌气毁掉关系",
        body_markdown=(
            "# 标题\n\n"
            "赌气的人，表面在撑住姿态，其实是在等一个回应。\n\n"
            "我一直觉得，赌气其实很消耗人。\n\n"
            "是对方答应的事没做到，还是你其实很怕，怕自己认真了却没有被同样认真地对待？\n\n"
            "到最后，累的还是自己。\n\n"
            "有些关系最后没散在原则上，只是散在一口气里。"
        ),
    )

    assert not any("解释连接词偏多" in hit for hit in summary.hits)


def test_build_ai_flavor_polish_instruction_anchors_rewrite_to_source_material() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=(
            "# 标题\n\n"
            "不是失败，而是我本可以。\n\n"
            "愿我们都能珍惜当下。"
        ),
    )

    instruction = build_ai_flavor_polish_instruction(summary)

    assert "不要另起原稿没有的人物、职业、病症、时间地点或故事支线" in instruction
    assert "不要硬改成虚构故事开场" in instruction
    assert "不要为了把段落接顺，额外补“很多时候”“说到底”“人总是这样”这类泛感慨过渡句" in instruction
    assert "不要把原稿抹成统一的成熟公众号成稿腔" in instruction

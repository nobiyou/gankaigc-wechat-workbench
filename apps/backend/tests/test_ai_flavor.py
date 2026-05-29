from __future__ import annotations

from app.services.ai_flavor import evaluate_ai_flavor_risk


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

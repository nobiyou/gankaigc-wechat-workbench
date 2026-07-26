from app.services.ai_flavor import evaluate_ai_flavor_risk
from app.services.draft_quality_summary import build_draft_quality_summary


def test_build_draft_quality_summary_flags_stale_self_reliance_diagnostic_voice() -> None:
    title = "即使没有帮助，也不会孤立无援，而是能够自救自渡"
    body_markdown = (
        "外面的帮扶一时赶不上，自己先要把今天接过去的那一下。\n\n"
        "你回头一看，朋友有朋友的难，家里有家里的事，连一句“我能不能先说说”都得先在心里转两圈。"
        "很多人也想开口，可一回头，周围每个人手里都压着自己的事。\n\n"
        "越把希望全压在外面的安慰上，心就越容易一直悬着；真正让人慢慢站稳的，往往是先把今天过完，"
        "再把力气一点点收回自己身上。等不到整只手伸过来的时候，人最先能做的，往往是先把饭吃完，"
        "洗个澡，再把明天要用的东西收一收。\n\n"
        "那些没说出口的委屈、没来得及消化的压力，最后都会落进睡眠、胃口和每天的心气里。"
        "它不会一下子闹得很大，可会先把一天里最细的那点劲慢慢磨钝。\n\n"
        "一个人先把自己安顿住，等于先给自己留住继续往前的底子。你不用一下子变得很强，只要先别把自己丢下。"
    )

    ai_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    quality_summary = build_draft_quality_summary(
        draft_version=1,
        draft_title=title,
        draft_body_markdown=body_markdown,
    )

    assert ai_summary.score > 0
    assert any("旧自救诊断模板" in hit for hit in ai_summary.hits)
    assert quality_summary.ai_flavor_score == ai_summary.score
    assert quality_summary.ai_flavor_level == ai_summary.level
    assert any("旧自救诊断模板" in finding for finding in quality_summary.key_findings)


def test_build_draft_quality_summary_accepts_positive_self_reliance_voice() -> None:
    title = "先把眼前这一步走稳，心里就会有光"
    body_markdown = (
        "早上出门前，她把桌上的便签重新排了一遍。最急的那件事放左边，能晚点处理的放右边，"
        "中间留给自己一杯热水的时间。\n\n"
        "不是每个难关都会立刻有人替你解围，可人也不是只能站在原地等。她先把最小的那一步做完："
        "电话打给负责的人，资料重新归档，午饭认真吃完。\n\n"
        "事情没有一下子变轻，但顺序回来了。\n\n"
        "真正托住人的，常常不是一句漂亮安慰，而是你知道自己还能安排、还能判断、还能把今天接住。"
        "等傍晚风吹进来，她发现心里那根线松了一点。\n\n"
        "往后的日子也许仍有难处，可她不再只盯着难处看。能做的事摆到眼前，能珍惜的人认真珍惜，"
        "能让自己变好的路，就一步一步走。"
    )

    ai_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    quality_summary = build_draft_quality_summary(
        draft_version=2,
        draft_title=title,
        draft_body_markdown=body_markdown,
    )

    assert not any("旧自救诊断模板" in hit for hit in ai_summary.hits)
    assert quality_summary.ai_flavor_score == ai_summary.score


def test_ai_flavor_detects_abstract_responsibility_diagnosis_voice() -> None:
    title = "肩上有责任的人，心里也要留一盏灯"
    body_markdown = (
        "责任集中落在一个人身上，往往不是因为他更强，而是因为家庭分工、经济压力和长期习惯，"
        "慢慢把能把事情接住的人推成了默认的承担者。\n\n"
        "表面上日子还在往前走，实际上被透支的是睡眠、耐心、身体和自我感受，"
        "很多人不是突然崩的，而是在长期压缩自己之后变得麻木。"
    )

    ai_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    quality_summary = build_draft_quality_summary(
        draft_version=1,
        draft_title=title,
        draft_body_markdown=body_markdown,
    )

    assert ai_summary.score > 0
    assert any("抽象机制标签" in hit for hit in ai_summary.hits)
    assert quality_summary.ai_flavor_score == ai_summary.score
    assert any("抽象机制标签" in finding for finding in quality_summary.key_findings)

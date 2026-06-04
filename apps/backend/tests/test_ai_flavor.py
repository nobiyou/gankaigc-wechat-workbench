from __future__ import annotations

from app.services.ai_flavor import (
    build_ai_flavor_polish_instruction,
    extract_explanatory_bridge_paragraphs,
    evaluate_ai_flavor_risk,
    extract_generic_reflective_openers,
    extract_growth_cliches,
    extract_embedded_banner_paragraphs,
    extract_isolated_quote_paragraphs,
    extract_not_ab_skeletons,
    extract_bridging_summary_paragraphs,
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
        "事情常常就是这样变成现在的。\n\n"
        "最后回到具体动作。"
    )

    assert openers == ["很多时候", "说到底", "事情常常就是这样"]


def test_evaluate_ai_flavor_risk_flags_generic_reflective_transitions() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=(
            "# 标题\n\n"
            "很多时候，我们总以为明天还来得及。\n\n"
            "身体的提醒通常不响亮。\n\n"
            "说到底，人最容易高估的，是自己还能再等等。\n\n"
            "最后回到一句平静收束。"
        ),
    )

    assert any("泛感慨过渡句偏多" in hit for hit in summary.hits)
    assert any("删掉部分“很多时候”“说到底”式过渡句" in suggestion for suggestion in summary.suggestions)


def test_extract_bridging_summary_paragraphs_flags_fragment_chain_announcing_lines() -> None:
    hits = extract_bridging_summary_paragraphs(
        "# 标题\n\n"
        "身体的提醒通常不响亮。\n\n"
        "很少有人会在某个整点突然意识到自己不行了，更常见的是凌晨醒来一回，或者洗完澡站着发空。\n\n"
        "事情常常就是这样变成现在的。\n\n"
        "最早只是顺延一次，后来发现自己也扛住了，就默认还能再拖，再往后，连休息和检查也都被塞进以后。"
    )

    assert hits == ["身体的提醒通常不响亮。", "事情常常就是这样变成现在的。"]


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


def test_evaluate_ai_flavor_risk_flags_short_judgment_cadence() -> None:
    summary = evaluate_ai_flavor_risk(
        title="她后来没再把真心话都留到夜里",
        body_markdown=(
            "# 标题\n\n"
            "电梯快合上的时候，她低头看了眼手机。\n\n"
            "置顶对话里躺着两条昨晚没回完的消息。朋友问她这周要不要见面，妈妈发来一张家里阳台新开的花。她的手指停在屏幕上方，楼层往下跳，她先回了工作群里的“收到”，又把那两个对话按灭。\n\n"
            "白天的她并没有闲着。\n\n"
            "消息很多，页面一直在跳。确认排期、对接流程、改表格、补一句“辛苦了”、再接住新的安排。她能回的大多是这种话：明确，简短，不需要情绪，也不需要把自己放进去。\n\n"
            "聊天框也会变得很难打开。\n\n"
            "她不是没话说，是那种要把心思拿出来、把语气放软、把一句普通回复变成真正的交流，这件事忽然很重。光是想一想，就已经觉得累。\n\n"
            "后来她有过个很小的变化。\n\n"
            "午休快结束时，她没有先去刷工作群，而是靠在茶水间窗边，回了朋友那条约见面的消息。没写很多，只是认真定了个周六下午。\n\n"
            "这一步很难。\n\n"
            "因为她清楚，一旦停下来，很多被压着的东西会一起冒头。委屈、烦躁、亏空感，还有那种说不出口的失望。"
        ),
    )

    assert any("单句敲钟段偏多" in hit for hit in summary.hits)
    assert any("固定节拍" in hit for hit in summary.hits)


def test_evaluate_ai_flavor_risk_flags_time_chain_shell_and_uniform_scene_layout() -> None:
    body_markdown = (
        "# 标题\n\n"
        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
        "手指往上一划，门开了，外面已经有人在喊投屏连不上。那条短信很快被新的通知压下去，和群消息、日程提醒叠在一起。\n\n"
        "楼梯口那次也很直白。同事走了两级，回头看见她扶着栏杆，问今天怎么这么慢。她笑了笑，只接了句，昨晚没睡好。\n\n"
        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑，把白天掉下去的进度补回来。\n\n"
        "饭局那回，声音更吵。杯子碰杯子，勺子刮盘子，过道上来回有人走。她坐在靠外侧的位置，菜转到面前，夹了口南瓜，就停那儿了。\n\n"
        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。\n\n"
        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，像内衣肩带勒久了，摘掉以后那道印子还留着。\n\n"
        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。\n\n"
        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。\n\n"
        "夜里十一点多，洗完澡的发尾还在滴水，睡衣领口湿了一小片。手机又亮了，还是那个朋友：你最近还好吗？\n\n"
        "她把输入框点开，打了两个字，又删掉。屏幕白着，下面压着那条复诊改期的确认短信。"
    )
    summary = evaluate_ai_flavor_risk(
        title="收件箱里那条改期短信，她一直没点开",
        body_markdown=body_markdown,
    )

    assert summary.level == "中"
    assert summary.score >= 30
    assert any("时间节点串珠式单线推进" in hit for hit in summary.hits)
    assert any("中长段匀速排布" in hit for hit in summary.hits)

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in instruction
    assert "不要一段一个职责地匀速排布" in instruction


def test_extract_bridging_summary_paragraphs_finds_announcing_anchor_paragraphs() -> None:
    paragraphs = extract_bridging_summary_paragraphs(
        "# 标题\n\n"
        "她把消息发出去了。\n\n"
        "这里面有条很清楚的线。\n\n"
        "待办一项项堆上来，她最先做的不是分辨自己累到哪了，而是把那点不舒服往里折，先做完再说。眼前这关要过，明天那项不能拖，周会材料还差最后两页。\n\n"
        "有些代价是延迟出现的。\n\n"
        "过了很久，终于约出来吃饭。餐厅里灯偏黄，汤上来时还冒着热气，对面的人问她，最近还好吗。"
    )

    assert paragraphs == ["这里面有条很清楚的线。", "有些代价是延迟出现的。"]


def test_evaluate_ai_flavor_risk_flags_announcing_anchor_paragraphs_and_repeated_starters() -> None:
    summary = evaluate_ai_flavor_risk(
        title="凉掉的咖啡、没回的邀约，和一个人慢慢失去电量的样子",
        body_markdown=(
            "# 标题\n\n"
            "她把消息发出去了。\n\n"
            "这里面有条很清楚的线。\n\n"
            "她坐着没动，连起身去洗那个杯子都像要先攒一会儿力气。她盯着桌边的水印，脑子里却还在想明天那份材料。她知道自己该洗漱、该收东西、该睡，可整个人像先被按在原地。\n\n"
            "她不是突然不爱说话的。\n\n"
            "她早上出门前，口红拿起来又放下。她午休时本来想去楼下走走，结果坐在工位上发呆。她深夜洗漱，牙刷含在嘴里，眼睛看着镜子里的人，脑子却是空的。\n\n"
            "有些代价是延迟出现的。\n\n"
            "先是把见面改成改天。后来电话变成文字。再后来，长回复缩成表情。"
        ),
    )

    assert any("宣布式锚句偏多" in hit for hit in summary.hits)
    assert any("连续同主语起段" in hit for hit in summary.hits)
    assert any("先是后来再后来的整齐梳理" in hit for hit in summary.hits)


def test_extract_embedded_banner_paragraphs_finds_long_paragraph_banner_leads() -> None:
    paragraphs = extract_embedded_banner_paragraphs(
        "# 标题\n\n"
        "这条线常常就是这么出来的。休息往后挪，情绪往后挪，身体给的提醒也往后挪。困了，先把表格做完；胃空着，先把会开完；体检预约改了又改，心里想着下周总能腾出空。\n\n"
        "关系也是这样淡下去的。朋友问近况，本来只是想听你说两句真的；家里来消息，也未必是催你做什么。可聊天框停在“改天见”后面太久，下一次点开时，里面会多出层生分。\n\n"
        "真正磨人的，往往不在最忙的那几天。忙的时候，人是被推着走的，顾不上细想。后面反复冒出来的，是那些原本能当时回掉、当时照顾、当时在场的时刻，被自己轻轻推开了。"
    )

    assert paragraphs == [
        "这条线常常就是这么出来的。",
        "关系也是这样淡下去的。",
        "真正磨人的，往往不在最忙的那几天。",
    ]


def test_evaluate_ai_flavor_risk_flags_embedded_banner_paragraphs() -> None:
    summary = evaluate_ai_flavor_risk(
        title="她不是突然不回消息的",
        body_markdown=(
            "# 标题\n\n"
            "她回工作消息还是很快，真正拖着不想点开的，反而是那些要带情绪、要接回应的话。\n\n"
            "这条线常常就是这么出来的。休息往后挪，情绪往后挪，身体给的提醒也往后挪。困了，先把表格做完；胃空着，先把会开完；体检预约改了又改，心里想着下周总能腾出空。\n\n"
            "关系也是这样淡下去的。朋友问近况，本来只是想听你说两句真的；家里来消息，也未必是催你做什么。可聊天框停在“改天见”后面太久，下一次点开时，里面会多出层生分。\n\n"
            "真正磨人的，往往不在最忙的那几天。忙的时候，人是被推着走的，顾不上细想。后面反复冒出来的，是那些原本能当时回掉、当时照顾、当时在场的时刻，被自己轻轻推开了。"
        ),
    )

    assert any("长段前置总括句偏多" in hit for hit in summary.hits)
    assert any("先总括再展开" in suggestion for suggestion in summary.suggestions)
    assert summary.score >= 20


def test_evaluate_ai_flavor_risk_flags_over_segmented_shell_layout() -> None:
    summary = evaluate_ai_flavor_risk(
        title="她没有突然垮掉，只是把自己排到了最后",
        body_markdown=(
            "# 标题\n\n"
            "包带还挂在肩上，勒得锁骨发酸。她站在洗手台前，把牙膏挤到牙刷上，白色膏体歪歪地停在刷毛边缘，快要掉下来。镜子里那张脸有点灰，额前碎发贴着，耳边像还残留着消息提示音。\n\n"
            "她没动。\n\n"
            "水龙头没有开，手也没抬起来。就那么站了十几秒，脑子里先冒出来的是：明天不能再这样了。接着，空了。后面该想什么，怎么改，先处理哪件事，她都接不上。像走到楼梯口，突然忘了自己是上楼还是下楼。\n\n"
            "很多人的累，不是那种轰一下压下来的累。更像这类时刻：睡前流程还在继续，身体会自动去做那些熟悉的动作，人却没有真正收回来。肩膀沉，后槽牙咬得发紧，眼睛盯着镜子，又像什么都没看见。情绪也不算大，甚至没有力气委屈。连崩溃都得往后排。真往前倒，不是从凌晨开始的。\n\n"
            "白天就已经有痕迹了。回同事消息时，她把打好的那行字删掉重来，来回看两遍，还是觉得哪里不对。会议里有人问到她，她明明听见了，反应却慢半拍，先是心里空白，接着才仓促补上几句。午饭摆在工位边上，饭吃了大半，才发现自己没尝出味道，嘴里只有温热和咀嚼。\n\n"
            "还有些更小的地方，零碎得不值得专门拿出来说。电梯到了她常去的楼层，她晚了半秒才迈腿；下楼取外卖，站在门口想了会儿，忘记自己拿没拿钥匙；朋友发来语音，她点开听完，没有不高兴，也没有想回，手机屏幕暗下去，她就让它那么躺着。\n\n"
            "那天开会前，同事问她要不要喝咖啡，她说，都行。中午订餐，别人问你吃什么，她还是那句，都行。晚上家里人发来消息，说周末怎么安排，她盯着对话框看了会儿，回：先这样吧。\n\n"
            "“我想吃什么”“我想休息”“我现在不太行”，这些话没有突然消失。只是慢慢地，很少再从嘴里出来了。\n\n"
            "她也没请假，没哭，没跟谁吵起来。工作照常交，消息照常回，见到人也会笑。表面看不出什么大问题，她自己也更容易把这些小卡顿压成一句：最近状态不好。\n\n"
            "这句解释太顺手了，没睡好，过两天就好了；这阵子忙完，应该能缓过来；周末多睡会儿，别多想。她拿这些话安顿自己，也拿它们把那些更细的感觉挡回去。毕竟待办还在往上跳，群里有人艾特，家里还有人等回复，连下班路上都塞着“顺手处理一下”的事。一个人被推着往前走时，能留给自己分辨的空间其实很窄。\n\n"
            "有时她也会察觉到不对。原来十分钟能做完的表格，现在坐了半小时还没进入状态；以前能接住的话题，现在听别人说话都觉得费劲；有人关心她一句“你最近还好吗”，她喉咙发紧，差点就想说实话了，到头来还是习惯性回：挺好的。\n\n"
            "先别问为什么。很多时候，那句“挺好的”几乎是弹出来的。\n\n"
            "因为停下来很麻烦。工作会乱，别人会等，答应过的事要重新解释。更麻烦的是，她得承认自己已经不像平时那样了。那个原本利落、能扛、反应快的人，现在做什么都发沉，说两句话都嫌累。这件事不好受。甚至有点刺人。\n\n"
            "她更容易用力把自己往“正常”里推。困了就灌咖啡，迟钝了就逼自己集中，想安静会儿又怕显得消极。明明已经拧巴得厉害，脸上还得维持平常的表情。该回的话照回，该笑的时候照笑，该出现的场合照出现。\n\n"
            "真正耗人的，常常不是事情本身有多大，而是人已经听见身体里的报警声，还要假装办公室里什么都没响。\n\n"
            "这种消耗有点阴，它不壮烈，也不戏剧化，不会给你一个明确的瞬间，告诉你“好，你现在撑不住了”。它更像电量被很多后台程序慢慢拖走。你照旧开着页面，照旧切任务，照旧回复别人，直到夜里站在洗手台前，才发现自己连“我现在到底怎么了”都组织不出来。\n\n"
            "这也是为什么，越着急恢复成原来那个样子，越容易看不见自己已经透支。她想赶快追平进度，赶快找回效率，赶快证明自己没事，于是那些变慢、变钝、不想说话的信号，就又被归到“短期失控”里。忍忍，顶顶，睡一觉再说。"
        ),
    )

    assert len(summary.hits) >= 1
    assert len(summary.suggestions) >= 1
    assert summary.score >= 10


def test_evaluate_ai_flavor_risk_flags_anchor_step_ladder_shell() -> None:
    summary = evaluate_ai_flavor_risk(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=(
            "# 标题\n\n"
            "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
            "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
            "人很多时候就是从这里开始慢下来的。没出什么大事，也谈不上垮。只是闹钟响了，按掉，再按掉；明明只差十分钟就能从容出门，还是在床边坐了很久。\n\n"
            "麻烦就麻烦在，这些信号太容易被她自己轻轻带过去。醒来更累，胃口乱，下午三四点会突然心慌；消息提示音一密集，太阳穴就跟着发紧。可熟悉的话也会立刻跟上来：忙完这阵就好了，周末补个觉就好了。\n\n"
            "身体先亮红灯，人却还照着原来的效率和礼貌往前走。该交的照交，该回的照回，见了人也还能笑，说自己没事。\n\n"
            "她还没倒下。还能上班，能交差，能在别人问起时回一句“挺好的”。偏偏就是这种“还能”，最容易让人误判。\n\n"
            "关系里的缺席，也是在这些时候一点点长出来的。见面改成改天，电话换成文字，长回复缩成表情，解释缩成“最近有点忙”。\n\n"
            "这句话很体谅，可听久了，人会更沉。因为她慢慢也默认了自己总在往后退。生活里有变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。\n\n"
            "难的地方就在这儿。不是因为太久没见，也不全是因为之前推掉太多次。更常见的情况是，人已经在长时间硬撑里，跟自己的感受脱了节。\n\n"
            "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。"
        ),
    )

    assert any("长段前置总括句偏多" in hit for hit in summary.hits)
    assert any("锚句起段台阶推进" in hit for hit in summary.hits)
    assert summary.score >= 30


def test_extract_isolated_quote_paragraphs_flags_quote_only_blocks() -> None:
    hits = extract_isolated_quote_paragraphs(
        "# 标题\n\n"
        "她点进去，又退了出来。\n\n"
        "“你最近怎么都不说话了？”\n\n"
        "她盯着那行字看了几秒，最后只回了个表情。"
    )

    assert hits == ["“你最近怎么都不说话了？”"]


def test_extract_explanatory_bridge_paragraphs_flags_detached_explanation_blocks() -> None:
    hits = extract_explanatory_bridge_paragraphs(
        "# 标题\n\n"
        "下午那阵发空先顶上来了。\n\n"
        "解释也来得很快：昨晚睡少了，今天会多，喝点咖啡就过去了。\n\n"
        "人一旦先替不适找好了理由，后面的动作就会很顺。回工位，盯屏幕，继续把自己往下一格日程里塞。"
    )

    assert hits == ["解释也来得很快：昨晚睡少了，今天会多，喝点咖啡就过去了。"]


def test_evaluate_ai_flavor_risk_flags_quote_and_explanation_detours() -> None:
    summary = evaluate_ai_flavor_risk(
        title="她回了很多个收到，却把那杯水放到晚上都没喝完",
        body_markdown=(
            "# 标题\n\n"
            "桌角那杯水一直没动。\n\n"
            "她刚从会议室出来，群消息一层层往上顶，手机屏幕亮了又暗。\n\n"
            "解释也来得很快：昨晚睡少了，今天会多，喝点咖啡就过去了。\n\n"
            "脑子里的解释来了：先把今天熬过去，晚上早点睡，明天应该就能缓回来。\n\n"
            "人一旦先替不适找好了理由，后面的动作就会很顺。回工位，盯屏幕，继续把自己往下一格日程里塞。\n\n"
            "朋友发来一条消息：\n\n"
            "“你最近怎么都不说话了？”\n\n"
            "“是不是又把自己忙没了？”\n\n"
            "她点进去，又退出来，最后只回了个表情。"
        ),
    )

    assert any("独立引语段偏多" in hit for hit in summary.hits)
    assert any("独立解释段偏多" in hit for hit in summary.hits)


def test_evaluate_ai_flavor_risk_allows_single_quote_and_explanation_break() -> None:
    summary = evaluate_ai_flavor_risk(
        title="她回了很多个收到，却把那杯水放到晚上都没喝完",
        body_markdown=(
            "# 标题\n\n"
            "桌角那杯水一直没动。\n\n"
            "她刚从会议室出来，群消息一层层往上顶，手机屏幕亮了又暗。\n\n"
            "解释也来得很快：昨晚睡少了，今天会多，喝点咖啡就过去了。\n\n"
            "人一旦先替不适找好了理由，后面的动作就会很顺。回工位，盯屏幕，继续把自己往下一格日程里塞。\n\n"
            "朋友发来一条消息：\n\n"
            "“你最近怎么都不说话了？”\n\n"
            "她点进去，又退出来，最后只回了个表情。"
        ),
    )

    assert not any("独立引语段偏多" in hit for hit in summary.hits)
    assert not any("独立解释段偏多" in hit for hit in summary.hits)


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
    assert "至少合并掉一半" in instruction
    assert "可以保留 1 到 3 个带具体动作、物件或身体反应的短段" in instruction
    assert "不要反复使用“短句点一下，下一段再长解释”的固定节拍" in instruction
    assert "不要把所有停顿句、改口句和动作残留都清掉" in instruction
    assert "不要单独起一段宣布“更麻烦的是”“有些代价是延迟出现的”“关系里的缺席”这类观点" in instruction
    assert "不要在长段开头先补“这条线常常就是这么出来的”" in instruction
    assert "打散连续“她……她……她……”或“你……你……你……”起段" in instruction
    assert "少用“先是……后来……再后来……”这种整理得过于整齐的梳理链" in instruction
    assert "优先把纯判断段改成机制段：补出触发动作、当场反应和后续影响" in instruction
    assert "每 2 到 3 段至少保住一个稳定抓手" in instruction
    assert "允许少量说明性句子把事情为什么会变成这样讲清楚" in instruction
    assert "不要把原稿抹成统一的成熟公众号成稿腔" in instruction
    assert "不要把一句消息、对话或引用单独切成一个展示段这种做法写成固定排版习惯" in instruction
    assert "不要单独起一个只负责解释的短段这种做法写成固定排版习惯" in instruction


def test_build_ai_flavor_polish_instruction_compact_focuses_on_hit_specific_actions() -> None:
    summary = evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=(
            "# 标题\n\n"
            "不是失败，而是我本可以。\n\n"
            "后来我才明白，很多事没有彩排。\n\n"
            "她总把要紧的事往后顺，饭能晚点吃，检查能下周做，想说的话也等有空再提。"
            "等到真要回头时，前面的门已经关上了。\n\n"
            "这句话最近出现得太频繁。\n\n"
            "朋友阿杰总说等忙完这阵就休息，可体检单一直压在抽屉里。"
            "外婆离世后我才发现，有些话不是没想过说，只是每次都以为还有下次，结果后来真的没有机会了。\n\n"
            "等回过神时，很多门已经关上了。\n\n"
            "她后来才承认，自己不是没有察觉，只是总把吃饭、体检、回消息这些事往后顺。"
            "工作能先做，情绪能先压，真正要面对自己的时候，却已经被前面的安排磨空了。\n\n"
            "从今天开始，别再把重要的东西推到以后。"
        ),
    )

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)

    assert "请基于现有草稿做一次去模板化精修。" in instruction
    assert "只做下面这些调整：" in instruction
    assert "删掉全部“不是A，而是B / 不是不……只是……”骨架" in instruction
    assert "把独立短判断段压到最多 2 处" in instruction
    assert "打散至少 3 处“短句点一下 + 下一段长解释”的节拍" in instruction
    assert "不虚构新人物、新职业、新病症、新地点或新剧情" in instruction
    assert "不要硬改成小说化故事开场" in instruction
    assert "输出只返回重写后的标题和正文" in instruction
    assert "每 2 到 3 段至少保住一个稳定抓手" not in instruction

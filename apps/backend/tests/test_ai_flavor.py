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
    extract_orphaned_rebound_tails,
    extract_rebound_explainer_tails,
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


def test_evaluate_ai_flavor_risk_flags_explainer_wechat_ai_cadence() -> None:
    summary = evaluate_ai_flavor_risk(
        title="善待自己，好好爱自己｜被排到最后的，常常是你自己",
        body_markdown=(
            "你以为自己只是累吗？有一类疲惫，休息一天也缓不过来。它往往与其说是事情多到做不完，不如说是你已经太久没把自己算进生活里。别人一有需要，你立刻接住；轮到自己的睡眠、情绪、体检、那顿该好好吃的饭，你总能往后再挪一点。答案先放这儿：成年后很多深一点的累，起点就是这个次序失衡。\n\n"
            "它一开始并不惊人，甚至很像负责。工作临时加项，你先改；家里有人要你搭把手，你先去；关系里气氛不对，你先安抚。你当场做出的反应，常常是把自己的不舒服压下去，把那句“我现在也不太行”咽回去。短时间里，事情被处理了，场面也稳住了。后面留下来的，是睡眠被切碎，身体信号被拖延，情绪越来越晚才轮到被照顾。\n\n"
            "成年人的生活里，最会抢位置的，几乎都是紧急的东西。消息要回，节点要赶，孩子和父母的问题要接，伴侣的情绪也需要回应。你的需要通常没有那么大的声量，它不敲门，只是在肩颈发紧、经期紊乱、胃口变差、耐心变短时提醒你。偏偏这类提醒没有外部倒计时，也没人替你追着办，最容易被划进“再等等”。你以为自己在排序，实际是在长期撤掉对自己的优先权。\n\n"
            "更麻烦的地方在这儿：这套模式很容易被夸成成熟。能扛、会让、少麻烦别人、凡事先顾全大局，这些词听着都体面，也确实帮你换来过认可。可一旦认可和自我忽略绑在一起，人就会慢慢学会一件危险的事：只要自己再忍一忍，关系就能顺一点，事情就能快一点。久了，“我需要”会变得很生硬，“我先来”也会让你有负罪感。\n\n"
            "更难受的，不全是累。是你要到失去一点东西，才肯承认这件事已经过头。失去的未必是某段关系，也可能是对生活的兴趣，是身体原本的弹性，是你看见自己需求时那点自然。自我亏欠最麻烦的地方，在于它前期很安静。你还能上班，还能照顾人，还能把一天撑过去，外面看不出什么。等到脾气变硬、委屈堆高、身体开始追债，你才发现，原来自己早就被排除在生活之外了。\n\n"
            "善待自己，不能等到所有事情安排完。成年人的待办清单不会自己见底，你把自己留给“有空再说”，基本就等于长期取消。更现实的做法，是把自己放回固定位置里：身体有信号就去看，接不住的请求就说接不住，给自己的时间和钱单独留下，不再拿“先紧着别人”吞掉。动作不需要很大，关键是次序要改。\n\n"
            "你也不用把这理解成自私。一个长期透支的人，给出去的照顾里常常夹着疲惫、怨气和勉强，关系迟早会尝到那股味道。你先把自己顾住，边界才不会总靠爆发来建立，亲密也少一点亏欠和埋怨。你只是不再拿自己去填所有空位。\n\n"
            "如果你已经累了，先别再拿“我习惯了”安抚自己。把一个最小的位置还给自己，先从那个总被往后拖的部分开始：今晚早点睡，把那次检查约上，不立刻回复每一个本可晚点回的消息。日子还是那些日子，关系也还在往前推，只是名单里终于有你。"
        ),
    )

    assert summary.level == "高"
    assert summary.score >= 60
    assert any("第二人称讲理腔偏重" in hit for hit in summary.hits)
    assert any("抽象机制标签密集" in hit for hit in summary.hits)
    assert any("中长段标准讲理排布" in hit for hit in summary.hits)

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "删掉“答案先放这儿 / 更麻烦的地方在这儿 / 你也不用”这类讲解台词" in instruction
    assert "降低第二人称密度" in instruction


def test_evaluate_ai_flavor_risk_flags_balanced_second_person_answer_shells() -> None:
    summary = evaluate_ai_flavor_risk(
        title="等到身体先报警，才发现自己一直排在最后",
        body_markdown=(
            "体检单上多了一行红字，你盯着下周那场会，想的还是能不能照常开。情绪忽然失控那次，你也没把它当回事，只当自己这阵子没休息好。连休息都变成任务的人，最容易把“累”理解成忙，把“撑不住”理解成自己还不够能扛。成年后的很多疲惫，起点往往更早：你已经习惯了，谁都可以排在你前面，只有你自己，总往后挪。\n\n"
            "这个顺序，不是一夜之间改掉的。通常是从很小的地方开始。消息先回，工作先交，家里的事先补上，朋友的请求先答应。轮到自己，复查可以下周再去，饭晚一点吃也行，睡眠先欠着，衣服鞋子还能将就。外面给你的反馈很直接，回得快、做得多、顶得住，就会被夸靠谱、懂事、顾全大局。照顾自己没那么立刻，少休一次，不会马上出大事；少吃一顿，也还能撑完今天。人就是在这种“暂时没问题”里，把自己一点点放到了最后。\n\n"
            "最难受的地方还不在忙。忙有时是阶段性的，过去就过去了。真正消耗人的，是你慢慢默认了：自己的不舒服可以先放一放，自己的需要可以再等等，自己的委屈没那么要紧。这个默认，会把人训练得很麻木。你明明已经发烧，还在改方案；经期疼得站不久，还在说没事；一句话已经冒犯了你，你先顾的是别把气氛弄僵。你一次次退后，不全是善良，也夹着一种很深的熟悉感：只要我还能扛，我就先扛。久了，连你自己都开始把这件事当成理所当然。\n\n"
            "很多女人的亏欠感，就是在这里长出来的。你总觉得自己还不够好，休息像偷懒，拒绝像亏待别人，花时间在自己身上，还要先补一句“我最近真的有点累”。这背后常常是一种价值感绑定：你把自己有没有用，看得比自己舒不舒服更重要。别人需要你，你会有存在感；轮到你需要被照顾，第一反应却常常是收回去。你怕麻烦人，怕显得矫情，怕一停下来，别人会失望。可身体不会配合这套逻辑。它只会在你长期忽略它的时候，用失眠、暴躁、心慌、内耗把账一点点送回来。\n\n"
            "人往往要等到真出问题，才承认自己丢了东西。请假住院那几天，你会忽然发现，少了你，很多事也还能转；一段一直靠你兜底的关系，一旦你不再提供情绪劳动，对方未必真会站出来接住你。那一刻你才看清，过去那些被你牺牲掉的睡眠、体力、兴趣、体面，都是从自己身上硬扣出去的。失去感会疼，疼也有用。它逼你承认，你早就欠了自己很多。\n\n"
            "还有一种失衡，表面看很小，拖久了最伤。医生让你三个月后复查，你拖成了八个月；牙疼一阵一阵，你总说过两天再去；心里已经很压抑了，还是把假期让给“更重要的安排”；一段关系里你总负责理解、安抚、兜底，轮到你难受，对方只回一句“你别想太多”。这些都容易被归进“小事不算事”。可小事重复得够久，就会改写一个人对自己的态度。你会越来越难分清，自己到底是在体谅别人，还是已经习惯亏待自己。\n\n"
            "把自己往前放，不用等到辞职、搬家、彻底翻篇那种大动作。成年人的止损，常常先从顺序改起。身体不舒服，就先去看；已经累到说话带火气，就先停一停；不属于你的额外责任，少接一点；能晚回的消息，晚回；周末留半天给自己，不拿来补所有人的需求。关键在于让自己看见：我的事也有名字，我的感受也占位置。我可以照顾人，也可以先照顾我自己。\n\n"
            "这件事刚开始，常常会有阻力。你会不习惯，会想把刚留出来的时间再让出去，会在拒绝别人之后冒出一点歉意。这不代表你做错了，只是旧顺序还在往回拽。你以前总把自己垫在最下面，大家都站稳了，只有你一直悬着。现在只是把那块垫子抽回来一点，让自己能落地。\n\n"
            "成年后最该补上的，是别再拿自己垫底。先去复查，先把晚饭吃完，先把那句“这次我来不了”发出去。做一件就够了。你会慢慢认出来，善待自己不是附加项，它本来就该在你的生活里面。"
        ),
    )

    assert summary.level == "中"
    assert summary.score >= 30
    assert any("第二人称整篇讲解密度偏高" in hit for hit in summary.hits)
    assert any("中长段整篇过于齐整" in hit for hit in summary.hits)

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "降低整篇第二人称讲解密度" in instruction
    assert "标准答案壳" in instruction


def test_evaluate_ai_flavor_risk_flags_explicit_second_person_lecture_lines() -> None:
    summary = evaluate_ai_flavor_risk(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=(
            "你有没有过这种阶段：消息看见了，不想回；别人多问两句，胸口就发闷；明明没出什么大事，人却像被抽掉了反应。答案我先直接告诉你，这通常不是懒，也不是你忽然变脆弱了。更常见的情况是，你已经很久没把自己放进日程里，身体和情绪先替你停了下来。\n\n"
            "手机界面还亮着，消息一排排挂在那里。\n\n"
            "你看见了，也知道该回谁，先点掉，又退出来。\n\n"
            "如果你这段时间已经开始变慢、变钝、变得不想说话，就别再拿“还能撑”安慰自己了。先把自己算进去。"
        ),
    )

    assert any("第二人称讲解台词偏显眼" in hit for hit in summary.hits)

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "你有没有过这种阶段 / 答案我先告诉你 / 如果你已经" in instruction
    assert "不要换成“不是……而是……”或“其实 / 所以”解释链" in instruction


def test_evaluate_ai_flavor_risk_flags_vague_attribution_and_signposting() -> None:
    summary = evaluate_ai_flavor_risk(
        title="总说自己还能撑的人，往往最晚承认身体已经在追债",
        body_markdown=(
            "先说结论，很多人不是不知道自己累，而是习惯先把累往后放。有人说，成年人都这样，忙完这一阵自然会好；专家指出，长期疲惫的人最容易忽略身体最早的提醒。\n\n"
            "接下来我们来看，问题为什么会越拖越重。她先把复查往后改，后来把晚饭和睡觉也一起往后推。很多人都会这样解释自己：先把手头这些事做完，等有空了再说。\n\n"
            "真正的问题是，身体不会按这套说法配合。提醒轻的时候被压过去，后面就只能用更重的后果继续敲门。"
        ),
    )

    assert any("模糊归因偏多" in hit for hit in summary.hits)
    assert any("宣布式结构路标偏多" in hit for hit in summary.hits)

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "模糊归因拆掉" in instruction
    assert "宣布式路标" in instruction


def test_evaluate_ai_flavor_risk_flags_dense_explainer_shell_even_without_explicit_lecture_lines() -> None:
    summary = evaluate_ai_flavor_risk(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=(
            "消息看见了，不想回；别人多问两句，胸口就发闷；明明没出什么大事，人却像被抽掉了反应。你已经很久没把自己放进日程里，身体和情绪先替你停了下来。很多人以为，生活失序会先出现在大地方，工作垮掉了，关系闹僵了，体检单亮红灯了。真到那一步，往往已经拖了很久。更早出现的，是话变短，记性变差，耐心越来越薄，坐着也像在赶路。\n\n"
            "这份发钝最容易被误解。旁人会说你只是最近太累，休息两天就好；你自己也会拿“先把今天过完”压过去。可很多亏空，根本不是两天形成的。饭总在后面吃，觉总往后挪，不舒服先忍，体检改下个月，情绪等忙完再整理。每次都只是往后推一点，推到最后，被挪走的就是你自己。\n\n"
            "先出问题的，常常是睡眠和吃饭。它们最容易牺牲，也最容易被轻视。少睡一晚，第二天确实还能出门；午饭凑合过去，下午也还能撑着做事。可身体不会按你的待办表运行。睡眠一碎，注意力先散；吃饭长期凑合，反应就会慢，火气却更快。别人第二句话说完了，你前面那句还没接稳；流程临时改动，整天节奏都乱；孩子多问两遍，语气先硬起来。\n\n"
            "这种状态磨人的地方，不在于事情有多大，在于它会慢慢改写关系。最亲近的人，最先接住的未必是你的辛苦，往往是你的走神、敷衍、不耐烦。你也会难受，会怪自己，觉得连好好回应都做不到。可愧疚一上来，人常常更想赶紧把眼前应付完，更舍不得停。前面没补上的觉，没吃完整的那顿饭，没说出口的委屈，最后都会绕回来，落到关系里。\n\n"
            "很多人总在失去后才承认，原来早就不对了。病倒一场，才肯承认身体不是机器；关系冷下去，才看见自己很久没认真听人说话；崩一次，才把那些旧信号对上号：懒得回消息，话越来越短，记性变差，对原本喜欢的事提不起劲。这些都不是突然发生的，它们早就在提醒，只是提醒不够响，不像工作催办那样立刻找上门。\n\n"
            "真正卡住人的，是紧急和重要的顺序被拧反了。工作上的临时需求、家里的突发状况、孩子的作业、父母的安排，都有当场反馈，你处理了，事情就往前走；你停下来，麻烦马上堆着看你。照顾自己没有这种即时催促。少睡一晚，表面没塌；情绪不整理，会也照开，饭也能继续做。久了，人会越来越擅长维持外面的秩序，越来越迟钝于里面的失衡。\n\n"
            "更难的是，很多人会把这叫成“我还行”“我再撑撑”。这几个字很硬，也很危险。撑住不等于没代价。你做事开始反复确认，效率却没高多少；别人一句普通的话，你听着都刺；忙了整天，晚上躺下却没完成感。连身体给出的信号也被压成背景音：累了不敢停，烦了不敢说，不舒服先忍，想休息先内疚。拖久了，人会连自己的需要都认不准。\n\n"
            "到这里，最该补的不是更强的执行力，也不是再学几条时间管理。先把一件事认下来：照顾自己，不该是忙完以后才轮到的奖励，它本来就是日常秩序的一部分。睡觉要往前放，吃饭要往前放，身体已经发出的信号要往前放。那句“我现在没力气，晚点再说”，也该被允许出现。\n\n"
            "变慢、变钝、变得不想说话的时候，就别再拿“还能撑”安慰自己了。把无效熬夜停掉，把那顿饭完整吃完，把原本准备硬接的请求往后放。日子能不能重新稳住，往往就从这里开始。不是先把所有人都安顿好，才轮得到你，是你先别继续亏欠自己。"
        ),
    )

    assert any("整篇解释壳偏密" in hit for hit in summary.hits)

    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "至少合并 2 到 4 段" in instruction


def test_evaluate_ai_flavor_risk_flags_opening_explainer_shell_in_short_window() -> None:
    summary = evaluate_ai_flavor_risk(
        title="等到身体先报警，才发现自己一直排在最后",
        body_markdown=(
            "你以为自己只是累吗？有一类疲惫，休息一天也缓不过来。别人一有需要，你立刻接住；轮到自己的睡眠、情绪、体检和那顿该好好吃的饭，你总能往后再挪一点。\n\n"
            "它一开始并不惊人，甚至很像负责。工作临时加项，你先改；家里有人要你搭把手，你先去；关系里气氛不对，你先安抚。短时间里，事情被处理了，场面也稳住了，后面留下来的，是睡眠被切碎，身体信号被拖延，情绪越来越晚才轮到被照顾。\n\n"
            "成年人的生活里，最会抢位置的，几乎都是紧急的东西。消息要回，节点要赶，孩子和父母的问题要接，伴侣的情绪也需要回应。你的需要通常没有那么大的声量，它不敲门，只是在肩颈发紧、经期紊乱、胃口变差、耐心变短时提醒你。\n\n"
            "很多亏空，不是一天形成的。你只是一次次把那句“我现在也不太行”压回去，久了，身体和情绪就先替你停下来。"
        ),
    )

    assert any("开头讲稿式先答后证" in hit for hit in summary.hits)
    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "不要先用“你以为……吗 / 有一类……”替读者分类下定义" in instruction


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


def test_evaluate_ai_flavor_risk_flags_abstract_answer_shell_title() -> None:
    summary = evaluate_ai_flavor_risk(
        title="总把自己放最后的人，生活为什么会慢慢失序",
        body_markdown=(
            "# 标题\n\n"
            "她先把体检往后改，又把回家吃饭这件事往后推。后来整个人越来越钝，连一句解释都懒得说。"
        ),
    )

    assert any("标题抽象答案壳" in hit for hit in summary.hits)
    instruction = build_ai_flavor_polish_instruction(summary, compact=True)
    assert "标题先落一个现实接口、后果或身体信号" in instruction


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


def test_extract_rebound_explainer_tails_finds_repeated_cleanup_like_tails() -> None:
    tails = extract_rebound_explainer_tails(
        "真要把它算成最近没休息好，反而把事情说浅了。"
        "真要这么说，也把事情说浅了。"
        "先说成体贴，反而太轻了。"
    )

    assert tails == [
        "真要把它算成最近没休息好，反而把事情说浅了",
        "真要这么说，也把事情说浅了",
        "先说成体贴，反而太轻了",
    ]


def test_evaluate_ai_flavor_risk_flags_rebound_explainer_tails() -> None:
    summary = evaluate_ai_flavor_risk(
        title="把复查一拖再拖的人，生活会慢慢缩到只剩先扛着",
        body_markdown=(
            "脸有点肿，嘴上说的是下周再去。真要把它算成最近没休息好，反而把事情说浅了。\n\n"
            "请假要解释，工作要有人接。真要把它算成没感觉，反而把事情说浅了。\n\n"
            "她太会把自己排到最后。真要把它算成不爱自己，反而把事情说浅了。"
        ),
    )

    assert any("回钩解释尾句偏多" in hit for hit in summary.hits)
    assert any("删掉反复出现的“真要把它算成……" in suggestion for suggestion in summary.suggestions)


def test_extract_orphaned_rebound_tails_finds_broken_cleanup_residue() -> None:
    tails = extract_orphaned_rebound_tails(
        "它代表的，反而把事情说浅了。"
        "后面那点拖延和硬撑反而更难解释。"
        "也把事情说浅了。"
    )

    assert tails == [
        "它代表的，反而把事情说浅了",
        "后面那点拖延和硬撑反而更难解释",
        "也把事情说浅了",
    ]


def test_evaluate_ai_flavor_risk_flags_orphaned_rebound_tails() -> None:
    summary = evaluate_ai_flavor_risk(
        title="那张没去复查的单子，通常比诊断书更早知道你扛不住了",
        body_markdown=(
            "它，你已经收到了提醒，但生活里没有给自己留处理提醒的位置。"
            "它代表的，反而把事情说浅了。"
            "你可以把很多人很多事安排进去，却没有把自己的复查排进去。"
        ),
    )

    assert any("断裂回钩尾句" in hit for hit in summary.hits)
    assert any("被拆断后单独残留的回钩尾句" in suggestion for suggestion in summary.suggestions)


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

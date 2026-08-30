from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_SANS = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Hiragino Sans GB','Microsoft YaHei',sans-serif"
)
_SERIF = "Georgia,'Times New Roman','Songti SC','Noto Serif CJK SC',SimSun,serif"
_MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


@dataclass(frozen=True)
class WechatMpHtmlStyle:
    """One paste-safe WeChat article style and its deterministic matching cues."""

    key: str
    name: str
    group: str
    aliases: tuple[str, ...]
    suitable_for: tuple[str, ...]
    body_style: str
    inherited_style: str
    element_styles: Mapping[str, str]
    match_terms: tuple[tuple[str, int], ...] = ()

    def style_for(self, element: str) -> str:
        element_style = self.element_styles.get(element, "")
        return f"{self.inherited_style}{element_style}"


@dataclass(frozen=True)
class WechatMpHtmlStyleRecommendation:
    key: str
    name: str
    reason: str
    matched_terms: tuple[str, ...]
    score: int


def _make_style(
    *,
    key: str,
    name: str,
    group: str,
    aliases: tuple[str, ...],
    suitable_for: tuple[str, ...],
    family: str,
    font_size: int,
    line_height: float,
    color: str,
    max_width: int,
    padding: str,
    background_color: str,
    elements: Mapping[str, str],
    match_terms: tuple[tuple[str, int], ...] = (),
) -> WechatMpHtmlStyle:
    inherited_style = (
        f"font-family:{family};font-size:{font_size}px;"
        f"line-height:{line_height};color:{color};"
    )
    body_style = (
        f"{inherited_style}max-width:{max_width}px;margin:0 auto;"
        f"padding:{padding};background-color:{background_color};"
    )
    element_styles = dict(elements)
    element_styles.setdefault("ol", element_styles.get("ul", ""))
    element_styles.setdefault("em", "font-style:italic;")
    element_styles.setdefault(
        "img",
        "display:block;max-width:100%;height:auto;margin:20px auto;",
    )
    return WechatMpHtmlStyle(
        key=key,
        name=name,
        group=group,
        aliases=aliases,
        suitable_for=suitable_for,
        body_style=body_style,
        inherited_style=inherited_style,
        element_styles=element_styles,
        match_terms=match_terms,
    )


BUILTIN_WECHAT_MP_HTML_STYLES: tuple[WechatMpHtmlStyle, ...] = (
    _make_style(
        key="minimal",
        name="极简黑白",
        group="推荐默认",
        aliases=("默认", "极简", "干净", "黑白", "商业方法论", "诊断报告"),
        suitable_for=("默认款", "深度文章", "方法论", "诊断报告"),
        family=_SANS,
        font_size=16,
        line_height=1.82,
        color="#2b2b2b",
        max_width=740,
        padding="24px 22px",
        background_color="#fff",
        elements={
            "h1": "font-size:24px;line-height:1.35;font-weight:800;text-align:left;margin:34px 0 24px;color:#111;padding-bottom:16px;border-bottom:1px solid #111;",
            "h2": "font-size:19px;line-height:1.45;font-weight:800;margin:42px 0 14px;color:#111;",
            "h3": "font-size:17px;line-height:1.5;font-weight:760;margin:30px 0 10px;color:#222;",
            "p": "margin:12px 0;line-height:1.82;",
            "blockquote": "margin:20px 0;padding:13px 16px;border-left:3px solid #111;background-color:#f7f7f7;color:#555;font-style:normal;",
            "ul": "margin:12px 0;padding-left:20px;",
            "li": "margin:7px 0;line-height:1.82;",
            "strong": "font-weight:850;color:#111;",
            "code": f"font-family:{_MONO};background-color:#f2f2f2;color:#111;padding:2px 6px;border-radius:3px;font-size:14px;line-height:1.6;",
            "pre": f"margin:20px 0;padding:14px 16px;overflow:auto;font-family:{_MONO};background-color:#f2f2f2;color:#111;font-size:14px;line-height:1.6;white-space:pre-wrap;word-break:break-word;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#111;padding:0;font-size:14px;line-height:1.6;white-space:pre-wrap;",
            "hr": "height:0;margin:32px 0;border:0;border-top:1px solid #e0e0e0;",
        },
    ),
    _make_style(
        key="medium",
        name="Medium Essay",
        group="经典媒体",
        aliases=("Medium", "长文", "随笔", "个人观点"),
        suitable_for=("个人观点", "深度长文", "方法论文章"),
        family=_SERIF,
        font_size=16,
        line_height=1.92,
        color="#242424",
        max_width=680,
        padding="34px 24px",
        background_color="#fff",
        elements={
            "h1": "font-size:28px;line-height:1.28;font-weight:700;text-align:left;margin:42px 0 28px;color:#111;",
            "h2": "font-size:22px;line-height:1.35;font-weight:700;margin:52px 0 18px;color:#111;",
            "h3": "font-size:18px;line-height:1.45;font-weight:700;margin:34px 0 12px;color:#333;",
            "p": "margin:15px 0;line-height:1.92;",
            "blockquote": "margin:28px 0;padding:0 0 0 22px;border-left:3px solid #242424;color:#444;font-size:17px;line-height:1.86;font-style:italic;",
            "ul": "margin:15px 0;padding-left:24px;",
            "li": "margin:8px 0;line-height:1.9;",
            "strong": "font-weight:800;color:#111;",
            "code": f"font-family:{_MONO};background-color:#f2f2f2;color:#222;padding:2px 6px;border-radius:3px;font-size:14px;",
            "pre": f"background-color:#f2f2f2;color:#222;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#222;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #d8d8d8;margin:40px auto;width:34%;",
        },
        match_terms=(("随笔", 4), ("个人观点", 5), ("深度", 3), ("思考", 2), ("长文", 2), ("故事", 2)),
    ),
    _make_style(
        key="wired",
        name="WIRED Feature",
        group="经典媒体",
        aliases=("WIRED", "科技", "AI", "前沿", "产品发布", "有冲击力"),
        suitable_for=("AI", "科技观点", "产品发布", "前沿趋势"),
        family=_SANS,
        font_size=16,
        line_height=1.74,
        color="#111",
        max_width=750,
        padding="22px",
        background_color="#fff",
        elements={
            "h1": "font-size:28px;line-height:1.16;font-weight:950;text-align:left;margin:36px 0 26px;color:#111;border-top:6px solid #111;border-bottom:6px solid #111;padding:16px 0;",
            "h2": "font-size:20px;line-height:1.35;font-weight:950;margin:44px 0 14px;color:#111;background-color:#f5ff00;padding:10px 12px;",
            "h3": "font-size:18px;line-height:1.4;font-weight:900;margin:32px 0 10px;color:#111;text-decoration:underline;text-decoration-thickness:4px;text-decoration-color:#00e5ff;text-underline-offset:5px;",
            "p": "margin:12px 0;line-height:1.74;",
            "blockquote": "margin:22px 0;padding:15px 16px;background-color:#111;color:#fff;border-left:0;font-weight:750;font-style:normal;",
            "ul": "margin:12px 0;padding-left:0;list-style:none;",
            "li": "margin:8px 0;line-height:1.72;padding:8px 10px;background-color:#f2f2f2;border-left:5px solid #111;",
            "strong": "font-weight:950;color:#111;background-color:#f5ff00;",
            "code": f"font-family:{_MONO};background-color:#111;color:#00e5ff;padding:2px 6px;border-radius:0;font-size:14px;",
            "pre": f"background-color:#111;color:#00e5ff;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#00e5ff;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;height:5px;background-color:#111;margin:34px 0;",
        },
        match_terms=(("科技", 4), ("人工智能", 5), ("ai", 5), ("模型", 3), ("产品发布", 4), ("前沿", 3), ("技术", 3)),
    ),
    _make_style(
        key="verge",
        name="The Verge Briefing",
        group="经典媒体",
        aliases=("The Verge", "Verge", "年轻", "热点", "资讯评论"),
        suitable_for=("热点解读", "产品更新", "资讯评论"),
        family=_SANS,
        font_size=16,
        line_height=1.76,
        color="#171717",
        max_width=750,
        padding="22px",
        background_color="#fff7fb",
        elements={
            "h1": "font-size:27px;line-height:1.2;font-weight:950;text-align:left;margin:36px 0 24px;color:#fff;background-color:#111;padding:18px 16px;box-shadow:8px 8px 0 #ff4fd8;",
            "h2": "font-size:20px;line-height:1.35;font-weight:900;margin:44px 0 14px;color:#111;padding:10px 12px;background-color:#bcff2f;",
            "h3": "font-size:18px;line-height:1.42;font-weight:880;margin:32px 0 10px;color:#111;border-bottom:3px solid #ff4fd8;padding-bottom:6px;",
            "p": "margin:12px 0;line-height:1.76;",
            "blockquote": "margin:22px 0;padding:14px 16px;border:3px solid #111;background-color:#fff;color:#111;font-weight:700;font-style:normal;",
            "ul": "margin:12px 0;padding-left:0;list-style:none;",
            "li": "margin:8px 0;line-height:1.74;padding:9px 10px;background-color:#fff;border-left:5px solid #ff4fd8;",
            "strong": "font-weight:950;color:#111;background-color:#bcff2f;",
            "code": f"font-family:{_MONO};background-color:#111;color:#bcff2f;padding:2px 6px;border-radius:0;font-size:14px;",
            "pre": f"background-color:#111;color:#bcff2f;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#bcff2f;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;height:3px;background-color:#ff4fd8;margin:34px 0;width:70%;",
        },
        match_terms=(("热点", 5), ("资讯", 4), ("评论", 3), ("年轻", 2), ("更新", 2)),
    ),
    _make_style(
        key="stripe",
        name="Stripe Docs",
        group="科技产品",
        aliases=("Stripe", "文档", "工具说明", "教程", "操作指南", "产品文档"),
        suitable_for=("教程", "工具说明", "Agent 工作流文档"),
        family=_SANS,
        font_size=16,
        line_height=1.78,
        color="#2a2f45",
        max_width=760,
        padding="24px 22px",
        background_color="#fbfcff",
        elements={
            "h1": "font-size:25px;line-height:1.32;font-weight:850;text-align:left;margin:36px 0 24px;color:#0a2540;",
            "h2": "font-size:19px;line-height:1.45;font-weight:820;margin:42px 0 14px;color:#0a2540;padding:10px 12px;background-color:#f1f5ff;border-left:4px solid #635bff;",
            "h3": "font-size:17px;line-height:1.5;font-weight:780;margin:30px 0 10px;color:#425466;",
            "p": "margin:12px 0;line-height:1.78;",
            "blockquote": "margin:20px 0;padding:14px 16px;background-color:#fff;border:1px solid #d9e2f3;border-left:4px solid #635bff;color:#3c4257;font-style:normal;",
            "ul": "margin:12px 0;padding-left:0;list-style:none;",
            "li": "margin:8px 0;line-height:1.76;padding:9px 10px;background-color:#fff;border:1px solid #e5ebf5;",
            "strong": "font-weight:850;color:#0a2540;",
            "code": f"font-family:{_MONO};background-color:#eef2ff;color:#3b35a8;padding:2px 6px;border-radius:4px;font-size:14px;",
            "pre": f"background-color:#eef2ff;color:#3b35a8;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#3b35a8;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #d9e2f3;margin:32px 0;",
        },
        match_terms=(("教程", 5), ("文档", 4), ("工具", 4), ("操作指南", 5), ("工作流", 4), ("agent", 4), ("步骤", 2)),
    ),
    _make_style(
        key="apple",
        name="Apple Newsroom",
        group="经典媒体",
        aliases=("Apple", "正式公告", "品牌稿", "产品介绍"),
        suitable_for=("正式公告", "产品介绍", "品牌文章"),
        family=_SANS,
        font_size=16,
        line_height=1.82,
        color="#1d1d1f",
        max_width=730,
        padding="34px 24px",
        background_color="#fff",
        elements={
            "h1": "font-size:30px;line-height:1.16;font-weight:800;text-align:center;margin:42px 0 30px;color:#1d1d1f;",
            "h2": "font-size:21px;line-height:1.42;font-weight:750;margin:48px 0 16px;color:#1d1d1f;text-align:center;",
            "h3": "font-size:18px;line-height:1.5;font-weight:700;margin:32px 0 10px;color:#424245;",
            "p": "margin:13px 0;line-height:1.82;",
            "blockquote": "margin:22px 0;padding:16px 18px;background-color:#f5f5f7;border-left:0;color:#424245;border-radius:10px;font-style:normal;",
            "ul": "margin:13px 0;padding-left:22px;",
            "li": "margin:7px 0;line-height:1.82;",
            "strong": "font-weight:800;color:#1d1d1f;",
            "code": f"font-family:{_MONO};background-color:#f5f5f7;color:#1d1d1f;padding:2px 6px;border-radius:5px;font-size:14px;",
            "pre": f"background-color:#f5f5f7;color:#1d1d1f;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;border-radius:10px;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#1d1d1f;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #d2d2d7;margin:36px auto;width:42%;",
        },
        match_terms=(("正式公告", 5), ("品牌", 4), ("产品介绍", 5), ("产品", 2), ("发布", 2)),
    ),
    _make_style(
        key="ft",
        name="FT Analysis",
        group="经典媒体",
        aliases=("FT", "财经", "商业分析", "市场判断", "对标研究"),
        suitable_for=("商业分析", "市场判断", "对标研究"),
        family=_SERIF,
        font_size=16,
        line_height=1.9,
        color="#262018",
        max_width=740,
        padding="24px 22px",
        background_color="#fff1df",
        elements={
            "h1": "font-size:27px;line-height:1.3;font-weight:800;text-align:left;margin:38px 0 24px;color:#111;border-bottom:3px double #5a4a36;padding-bottom:14px;",
            "h2": "font-size:21px;line-height:1.42;font-weight:800;margin:46px 0 16px;color:#3b2b1d;padding-top:10px;border-top:1px solid #8a7356;",
            "h3": "font-size:18px;line-height:1.5;font-weight:750;margin:32px 0 10px;color:#4c3a29;",
            "p": "margin:13px 0;line-height:1.9;",
            "blockquote": "margin:22px 0;padding:12px 0 12px 18px;border-left:4px solid #8a7356;color:#4f4030;background-color:#f9e6cf;font-style:normal;",
            "ul": "margin:13px 0;padding-left:22px;",
            "li": "margin:7px 0;line-height:1.9;",
            "strong": "font-weight:850;color:#111;",
            "code": f"font-family:{_MONO};background-color:#f5dec4;color:#3b2b1d;padding:2px 6px;border-radius:2px;font-size:14px;",
            "pre": f"background-color:#f5dec4;color:#3b2b1d;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#3b2b1d;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #8a7356;margin:34px 0;width:58%;",
        },
        match_terms=(("财经", 5), ("商业分析", 5), ("市场", 4), ("行业", 3), ("增长", 3), ("对标", 4), ("投资", 3)),
    ),
    _make_style(
        key="linear",
        name="Linear Changelog",
        group="科技产品",
        aliases=("Linear", "changelog", "版本更新", "更新日志", "路线图"),
        suitable_for=("版本公告", "功能更新", "路线图说明"),
        family=_SANS,
        font_size=16,
        line_height=1.76,
        color="#d7d7e1",
        max_width=750,
        padding="24px 22px",
        background_color="#111114",
        elements={
            "h1": "font-size:25px;line-height:1.32;font-weight:850;text-align:left;margin:36px 0 24px;color:#fff;",
            "h2": "font-size:19px;line-height:1.45;font-weight:820;margin:40px 0 14px;color:#fff;padding:10px 0;border-bottom:1px solid #2b2b33;",
            "h3": "font-size:17px;line-height:1.5;font-weight:780;margin:30px 0 10px;color:#c4b5fd;",
            "p": "margin:12px 0;line-height:1.76;",
            "blockquote": "margin:20px 0;padding:14px 16px;background-color:#19191f;border:1px solid #2b2b33;color:#d7d7e1;font-style:normal;",
            "ul": "margin:12px 0;padding-left:0;list-style:none;",
            "li": "margin:8px 0;line-height:1.74;padding:9px 10px;background-color:#17171c;border-left:3px solid #8b5cf6;",
            "strong": "font-weight:850;color:#fff;",
            "code": f"font-family:{_MONO};background-color:#242432;color:#c4b5fd;padding:2px 6px;border-radius:4px;font-size:14px;",
            "pre": f"background-color:#242432;color:#c4b5fd;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#c4b5fd;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #2b2b33;margin:32px 0;",
        },
        match_terms=(("更新日志", 5), ("版本更新", 5), ("changelog", 5), ("路线图", 4), ("迭代", 3), ("功能更新", 5)),
    ),
    _make_style(
        key="github",
        name="GitHub README",
        group="科技产品",
        aliases=("GitHub", "README", "开源", "安装说明"),
        suitable_for=("安装说明", "工具介绍", "技术文档"),
        family=_SANS,
        font_size=16,
        line_height=1.76,
        color="#24292f",
        max_width=760,
        padding="24px 22px",
        background_color="#fff",
        elements={
            "h1": "font-size:26px;line-height:1.28;font-weight:750;text-align:left;margin:36px 0 22px;color:#24292f;padding-bottom:10px;border-bottom:1px solid #d0d7de;",
            "h2": "font-size:20px;line-height:1.45;font-weight:700;margin:38px 0 14px;color:#24292f;padding-bottom:8px;border-bottom:1px solid #d8dee4;",
            "h3": "font-size:17px;line-height:1.5;font-weight:700;margin:28px 0 10px;color:#24292f;",
            "p": "margin:11px 0;line-height:1.76;",
            "blockquote": "margin:18px 0;padding:8px 16px;border-left:4px solid #d0d7de;color:#57606a;background-color:#fff;font-style:normal;",
            "ul": "margin:12px 0;padding-left:24px;",
            "li": "margin:6px 0;line-height:1.76;",
            "strong": "font-weight:750;color:#24292f;",
            "code": f"font-family:{_MONO};background-color:#f6f8fa;color:#24292f;padding:2px 6px;border-radius:4px;font-size:14px;",
            "pre": f"background-color:#f6f8fa;color:#24292f;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#24292f;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #d0d7de;margin:28px 0;",
        },
        match_terms=(("开源", 5), ("readme", 5), ("安装", 4), ("部署", 4), ("代码", 3), ("开发", 3), ("技术文档", 5)),
    ),
    _make_style(
        key="notion",
        name="Notion Memo",
        group="科技产品",
        aliases=("Notion", "备忘录", "内部总结", "项目复盘"),
        suitable_for=("学习笔记", "内部总结", "项目复盘"),
        family=_SANS,
        font_size=16,
        line_height=1.82,
        color="#37352f",
        max_width=720,
        padding="28px 24px",
        background_color="#fffefc",
        elements={
            "h1": "font-size:27px;line-height:1.28;font-weight:780;text-align:left;margin:38px 0 24px;color:#37352f;",
            "h2": "font-size:20px;line-height:1.45;font-weight:720;margin:42px 0 14px;color:#37352f;background-color:#f7f6f3;padding:10px 12px;",
            "h3": "font-size:17px;line-height:1.5;font-weight:720;margin:30px 0 10px;color:#37352f;",
            "p": "margin:12px 0;line-height:1.82;",
            "blockquote": "margin:20px 0;padding:12px 16px;border-left:3px solid #9b9a97;background-color:#f7f6f3;color:#4f4d48;font-style:normal;",
            "ul": "margin:12px 0;padding-left:22px;",
            "li": "margin:7px 0;line-height:1.82;",
            "strong": "font-weight:800;color:#37352f;border-bottom:2px solid #eeeeee;",
            "code": f"font-family:{_MONO};background-color:#f1f1ef;color:#37352f;padding:2px 6px;border-radius:3px;font-size:14px;",
            "pre": f"background-color:#f1f1ef;color:#37352f;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#37352f;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #e7e6e2;margin:32px 0;",
        },
        match_terms=(("备忘录", 4), ("笔记", 4), ("内部总结", 5), ("项目复盘", 5), ("学习", 3), ("复盘", 4), ("总结", 2)),
    ),
    _make_style(
        key="magazine",
        name="Magazine Feature",
        group="内容出版",
        aliases=("杂志", "人物稿", "品牌故事", "专题"),
        suitable_for=("人物稿", "品牌故事", "深度专题"),
        family=_SERIF,
        font_size=16,
        line_height=1.94,
        color="#282828",
        max_width=700,
        padding="30px 24px",
        background_color="#fff",
        elements={
            "h1": "font-size:28px;line-height:1.3;font-weight:700;text-align:center;margin:42px 0 30px;color:#111;",
            "h2": "font-size:21px;line-height:1.45;font-weight:700;margin:50px 0 18px;color:#111;text-align:center;",
            "h3": "font-size:18px;line-height:1.5;font-weight:700;margin:34px 0 12px;color:#333;text-align:center;",
            "p": "margin:15px 0;line-height:1.94;",
            "blockquote": "margin:26px 0;padding:0 22px;border-left:0;color:#555;font-size:15px;line-height:1.95;text-align:center;font-style:italic;",
            "ul": "margin:15px 0;padding-left:22px;",
            "li": "margin:8px 0;line-height:1.92;",
            "strong": "font-weight:800;color:#111;",
            "code": f"font-family:{_MONO};background-color:#f3f3f3;color:#222;padding:2px 6px;border-radius:2px;font-size:14px;",
            "pre": f"background-color:#f3f3f3;color:#222;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#222;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #bdbdbd;margin:36px auto;width:46%;",
        },
        match_terms=(("人物", 5), ("品牌故事", 5), ("专题", 4), ("采访", 4), ("杂志", 3), ("人物稿", 5)),
    ),
    _make_style(
        key="editorial",
        name="Editorial Column",
        group="内容出版",
        aliases=("专栏", "手记", "创作者随笔", "复盘札记"),
        suitable_for=("创作者手记", "观点随笔", "复盘札记"),
        family=_SANS,
        font_size=16,
        line_height=1.92,
        color="#252525",
        max_width=680,
        padding="28px 24px",
        background_color="#fff",
        elements={
            "h1": "font-size:25px;line-height:1.42;font-weight:650;text-align:left;margin:38px 0 24px;color:#111;",
            "h2": "font-size:19px;line-height:1.5;font-weight:700;margin:46px 0 16px;color:#111;",
            "h3": "font-size:17px;line-height:1.55;font-weight:700;margin:32px 0 12px;color:#333;",
            "p": "margin:14px 0;line-height:1.92;",
            "blockquote": "margin:22px 0;padding:0 0 0 18px;border-left:2px solid #222;color:#4f4f4f;font-size:15px;line-height:1.9;font-style:normal;",
            "ul": "margin:14px 0;padding-left:20px;",
            "li": "margin:7px 0;line-height:1.9;",
            "strong": "font-weight:800;color:#111;border-bottom:2px solid #eeeeee;",
            "code": f"font-family:{_MONO};background-color:#f5f5f5;color:#222;padding:2px 6px;border-radius:3px;font-size:14px;",
            "pre": f"background-color:#f5f5f5;color:#222;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#222;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #e0e0e0;margin:34px 0;",
        },
        match_terms=(("专栏", 5), ("手记", 5), ("创作者", 4), ("札记", 4), ("随笔", 2)),
    ),
    _make_style(
        key="newspaper",
        name="Newspaper Report",
        group="内容出版",
        aliases=("报纸", "报道", "调查", "严肃分析"),
        suitable_for=("调查稿", "商业报道", "严肃分析"),
        family="'Songti SC','Noto Serif CJK SC',Georgia,'Times New Roman',SimSun,serif",
        font_size=16,
        line_height=1.88,
        color="#202020",
        max_width=760,
        padding="22px",
        background_color="#fff",
        elements={
            "h1": "font-size:25px;line-height:1.36;font-weight:800;text-align:left;margin:34px 0 20px;color:#111;padding:0 0 14px;border-bottom:3px double #111;",
            "h2": "font-size:20px;line-height:1.42;font-weight:800;margin:42px 0 14px;color:#111;padding-top:10px;border-top:2px solid #111;",
            "h3": "font-size:17px;line-height:1.5;font-weight:800;margin:30px 0 10px;color:#222;",
            "p": "margin:12px 0;line-height:1.88;",
            "blockquote": "margin:20px 0;padding:12px 0 12px 18px;border-left:4px solid #555;color:#444;background-color:#fafafa;font-style:normal;",
            "ul": "margin:12px 0;padding-left:21px;",
            "li": "margin:7px 0;line-height:1.88;",
            "strong": "font-weight:800;color:#111;",
            "code": f"font-family:{_MONO};background-color:#eeeeee;color:#222;padding:2px 6px;border-radius:1px;font-size:14px;",
            "pre": f"background-color:#eeeeee;color:#222;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#222;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #999;margin:30px 0;",
        },
        match_terms=(("报道", 5), ("调查", 5), ("严肃分析", 5), ("记者", 3), ("数据", 3), ("调查稿", 5)),
    ),
    _make_style(
        key="course",
        name="课程讲义",
        group="中文公众号",
        aliases=("课程", "学习笔记", "讲义", "教程"),
        suitable_for=("课程", "教程", "学习笔记", "操作说明"),
        family=_SANS,
        font_size=16,
        line_height=1.84,
        color="#272727",
        max_width=750,
        padding="22px",
        background_color="#fff",
        elements={
            "h1": "font-size:24px;line-height:1.38;font-weight:800;text-align:center;margin:34px 0 22px;color:#111;",
            "h2": "font-size:19px;line-height:1.45;font-weight:800;margin:40px 0 16px;color:#111;padding:11px 14px;background-color:#f3f3f3;",
            "h3": "font-size:17px;line-height:1.5;font-weight:800;margin:30px 0 10px;color:#111;padding-bottom:6px;border-bottom:1px dotted #aaa;",
            "p": "margin:12px 0;line-height:1.84;",
            "blockquote": "margin:18px 0;padding:14px 16px;background-color:#f8f8f8;border-left:0;border-top:1px solid #e1e1e1;border-bottom:1px solid #e1e1e1;color:#444;font-style:normal;",
            "ul": "margin:12px 0;padding-left:20px;",
            "li": "margin:7px 0;line-height:1.84;",
            "strong": "font-weight:850;color:#111;",
            "code": f"font-family:{_MONO};background-color:#eeeeee;color:#222;padding:2px 6px;border-radius:3px;font-size:14px;",
            "pre": f"background-color:#eeeeee;color:#222;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#222;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;border-top:1px solid #ddd;margin:30px 0;",
        },
        match_terms=(("课程", 5), ("讲义", 5), ("学习笔记", 5), ("操作说明", 5), ("教程", 2)),
    ),
    _make_style(
        key="event",
        name="活动公告",
        group="中文公众号",
        aliases=("活动", "招募", "转化", "通知", "公告"),
        suitable_for=("活动通知", "招募", "发布公告", "转化文"),
        family=_SANS,
        font_size=16,
        line_height=1.78,
        color="#2c2424",
        max_width=740,
        padding="22px",
        background_color="#fff",
        elements={
            "h1": "font-size:24px;line-height:1.35;font-weight:900;text-align:center;margin:34px 0 20px;color:#8f1f1d;padding:18px 12px;border:2px solid #8f1f1d;background-color:#fffafa;",
            "h2": "font-size:19px;line-height:1.45;font-weight:850;margin:40px 0 14px;color:#8f1f1d;padding:0 0 10px;border-bottom:2px solid #8f1f1d;",
            "h3": "font-size:17px;line-height:1.5;font-weight:800;margin:30px 0 10px;color:#4a2a2a;",
            "p": "margin:12px 0;line-height:1.78;",
            "blockquote": "margin:18px 0;padding:14px 16px;background-color:#8f1f1d;color:#fff;border-left:0;font-style:normal;",
            "ul": "margin:12px 0;padding-left:20px;",
            "li": "margin:7px 0;line-height:1.78;",
            "strong": "font-weight:900;color:#8f1f1d;",
            "code": f"font-family:{_MONO};background-color:#fff0f0;color:#8f1f1d;padding:2px 6px;border-radius:3px;font-size:14px;",
            "pre": f"background-color:#fff0f0;color:#8f1f1d;padding:14px 16px;overflow:auto;font-family:{_MONO};font-size:14px;line-height:1.6;",
            "pre_code": f"font-family:{_MONO};background-color:transparent;color:#8f1f1d;padding:0;font-size:14px;line-height:1.6;",
            "hr": "border:0;height:2px;background-color:#8f1f1d;margin:30px 0;",
        },
        match_terms=(("活动", 5), ("招募", 5), ("报名", 5), ("通知", 4), ("公告", 4), ("转化", 3)),
    ),
)

STYLE_BY_KEY = {style.key: style for style in BUILTIN_WECHAT_MP_HTML_STYLES}
DEFAULT_WECHAT_MP_HTML_STYLE_KEY = "minimal"


def list_builtin_wechat_mp_html_styles() -> list[WechatMpHtmlStyle]:
    return list(BUILTIN_WECHAT_MP_HTML_STYLES)


def get_wechat_mp_html_style(style_key: str | None = None) -> WechatMpHtmlStyle:
    normalized = str(style_key or DEFAULT_WECHAT_MP_HTML_STYLE_KEY).strip().lower()
    style = STYLE_BY_KEY.get(normalized)
    if style is None:
        raise ValueError(f"Unknown WeChat HTML style: {style_key}")
    return style


def recommend_wechat_mp_html_style(
    *,
    title: str = "",
    body_markdown: str = "",
    topic_title: str = "",
    topic_angle: str = "",
    active_style_keys: set[str] | None = None,
    default_style_key: str = DEFAULT_WECHAT_MP_HTML_STYLE_KEY,
) -> WechatMpHtmlStyleRecommendation:
    available = [
        style
        for style in BUILTIN_WECHAT_MP_HTML_STYLES
        if active_style_keys is None or style.key in active_style_keys
    ]
    if not available:
        available = [get_wechat_mp_html_style(DEFAULT_WECHAT_MP_HTML_STYLE_KEY)]

    corpus = " ".join((title, topic_title, topic_angle, body_markdown)).lower()
    scored: list[tuple[int, int, WechatMpHtmlStyle, tuple[str, ...]]] = []
    for index, style in enumerate(available):
        matched_terms = tuple(term for term, _weight in style.match_terms if term.lower() in corpus)
        score = sum(weight for term, weight in style.match_terms if term.lower() in corpus)
        scored.append((score, -index, style, matched_terms))

    best_score = max(item[0] for item in scored)
    if best_score <= 0:
        fallback = next(
            (item[2] for item in scored if item[2].key == default_style_key),
            available[0],
        )
        reason = f"未命中明确内容场景，使用当前默认排版「{fallback.name}」。"
        return WechatMpHtmlStyleRecommendation(
            key=fallback.key,
            name=fallback.name,
            reason=reason,
            matched_terms=(),
            score=0,
        )

    _score, _order, selected, matched_terms = max(scored, key=lambda item: (item[0], item[1]))
    terms = "、".join(matched_terms[:4])
    reason = f"根据内容命中「{terms}」等场景，智能选择「{selected.name}」。"
    return WechatMpHtmlStyleRecommendation(
        key=selected.key,
        name=selected.name,
        reason=reason,
        matched_terms=matched_terms,
        score=best_score,
    )


STYLE_PREVIEW_MARKDOWN = """# 公众号文章标题

这是一段用于查看正文密度、字体、颜色和段落间距的示例文字。风格只影响排版，不会改写文章内容。

## 一个清晰的小标题

正文会在这里保持可读的行宽，并把段落、引用和重点拆开处理。

> 重要的话会被单独托住，但不会遮住正文。

- 重点信息保持清楚
- 列表适合快速扫描

### 适合的使用场景

你可以把它应用到发布包预览，也可以在生成前为项目指定风格。
"""


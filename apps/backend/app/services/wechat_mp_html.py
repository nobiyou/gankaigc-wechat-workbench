from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urlparse

from app.services.wechat_mp_styles import (
    DEFAULT_WECHAT_MP_HTML_STYLE_KEY,
    WechatMpHtmlStyle,
    get_wechat_mp_html_style,
)


class WechatMpHtmlRenderError(ValueError):
    """Raised when Markdown cannot be converted to a safe WeChat article body."""


ImageResolver = Callable[[Path, str], str]


@dataclass(frozen=True)
class WechatMpHtmlRenderResult:
    title: str
    body_html: str
    style_key: str = DEFAULT_WECHAT_MP_HTML_STYLE_KEY
    style_name: str = "极简黑白"


_FONT_FAMILY = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Hiragino Sans GB','Microsoft YaHei',sans-serif"
)
_CODE_FONT_FAMILY = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^\s)]+))"
    r"(?:\s+['\"][^'\"]*['\"])?\s*\)"
)
_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(\s*(?:<([^>]+)>|([^\s)]+))"
    r"(?:\s+['\"][^'\"]*['\"])?\s*\)"
)
_CODE_RE = re.compile(r"`([^`]+)`")
_STRONG_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_EM_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
_UNORDERED_LIST_RE = re.compile(r"^\s*[-+*]\s+(.+)$")
_ORDERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*[^`~]*$")
_HR_RE = re.compile(r"^\s*(?:\*\s*){3,}$|^\s*(?:-\s*){3,}$|^\s*(?:_\s*){3,}$")


def render_wechat_html(
    markdown_text: str,
    *,
    base_dir: str | Path | None = None,
    image_resolver: ImageResolver | None = None,
    title: str = "",
    remove_first_h1: bool = True,
    style_key: str | None = None,
) -> WechatMpHtmlRenderResult:
    """Render Markdown into a WeChat-compatible, inline-styled body fragment."""

    try:
        style = get_wechat_mp_html_style(style_key)
    except ValueError as exc:
        raise WechatMpHtmlRenderError(str(exc)) from None

    normalized_base_dir = Path(base_dir or Path.cwd()).resolve()
    lines = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    quote_lines: list[str] = []
    list_type: str | None = None
    list_items: list[str] = []
    fence_marker: str | None = None
    code_lines: list[str] = []
    first_h1_removed = False
    resolved_title = _clean_title(title)

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(part.strip() for part in paragraph_lines).strip()
        paragraph_lines.clear()
        if text:
            blocks.append(f'<p style="{style.style_for("p")}">{_render_inline(text, normalized_base_dir, image_resolver, style)}</p>')

    def flush_quote() -> None:
        if not quote_lines:
            return
        text = " ".join(part.strip() for part in quote_lines).strip()
        quote_lines.clear()
        if text:
            blocks.append(
                f'<blockquote style="{style.style_for("blockquote")}">'
                f"{_render_inline(text, normalized_base_dir, image_resolver, style)}"
                "</blockquote>"
            )

    def flush_list() -> None:
        nonlocal list_type
        if not list_items or list_type is None:
            list_type = None
            list_items.clear()
            return
        tag = list_type
        item_html = "".join(
            f'<li style="{style.style_for("li")}">'
            f"{_render_inline(item, normalized_base_dir, image_resolver, style)}</li>"
            for item in list_items
        )
        blocks.append(f'<{tag} style="{style.style_for(tag)}">{item_html}</{tag}>')
        list_type = None
        list_items.clear()

    def flush_code() -> None:
        nonlocal code_lines
        if fence_marker is None:
            code_lines = []
            return
        code_text = "\n".join(code_lines)
        code_lines = []
        escaped = html.escape(code_text, quote=False)
        blocks.append(
            f'<pre style="{style.style_for("pre")}">'
            f'<code style="{style.style_for("pre_code")}">{escaped}</code></pre>'
        )

    def flush_open_blocks() -> None:
        flush_paragraph()
        flush_quote()
        flush_list()

    for raw_line in lines:
        line = raw_line.strip()

        if fence_marker is not None:
            if line.startswith(fence_marker):
                flush_code()
                fence_marker = None
            else:
                code_lines.append(raw_line.rstrip())
            continue

        if _FENCE_RE.match(raw_line):
            flush_open_blocks()
            fence_marker = line[:3]
            code_lines = []
            continue

        if not line:
            flush_open_blocks()
            continue

        heading_match = _HEADING_RE.match(raw_line)
        if heading_match:
            flush_open_blocks()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if level == 1 and remove_first_h1 and not first_h1_removed:
                first_h1_removed = True
                resolved_title = _clean_title(_plain_inline_text(heading_text)) or resolved_title
                continue
            rendered_level = 2 if level == 1 else min(level, 3)
            blocks.append(
                f'<h{rendered_level} style="{style.style_for(f"h{rendered_level}")}">'
                f"{_render_inline(heading_text, normalized_base_dir, image_resolver, style)}"
                f"</h{rendered_level}>"
            )
            continue

        if _HR_RE.match(raw_line):
            flush_open_blocks()
            blocks.append(f'<hr style="{style.style_for("hr")}">')
            continue

        quote_match = _BLOCKQUOTE_RE.match(raw_line)
        if quote_match:
            flush_paragraph()
            flush_list()
            quote_lines.append(quote_match.group(1))
            continue
        flush_quote()

        unordered_match = _UNORDERED_LIST_RE.match(raw_line)
        ordered_match = _ORDERED_LIST_RE.match(raw_line)
        if unordered_match or ordered_match:
            item_type = "ul" if unordered_match else "ol"
            item_text = (unordered_match or ordered_match).group(1).strip()
            flush_paragraph()
            if list_type is not None and list_type != item_type:
                flush_list()
            list_type = item_type
            list_items.append(item_text)
            continue
        flush_list()

        paragraph_lines.append(line)

    if fence_marker is not None:
        flush_code()
    flush_open_blocks()

    return WechatMpHtmlRenderResult(
        title=resolved_title,
        body_html="".join(blocks),
        style_key=style.key,
        style_name=style.name,
    )


def build_wechat_preview_document(
    rendered: WechatMpHtmlRenderResult,
    *,
    title: str | None = None,
    lead: str | None = None,
    cover_image_url: str | None = None,
) -> str:
    """Wrap the shared article fragment in a standalone local-preview document."""

    document_title = _clean_title(title if title is not None else rendered.title)
    style = get_wechat_mp_html_style(rendered.style_key)
    header_blocks: list[str] = []
    if document_title:
        header_blocks.append(
            f'<h1 style="{style.style_for("h1")}">{html.escape(document_title, quote=False)}</h1>'
        )
    normalized_cover_image_url = str(cover_image_url or "").strip()
    if normalized_cover_image_url:
        header_blocks.append(
            f'<img src="{html.escape(normalized_cover_image_url, quote=True)}" '
            f'alt="{html.escape(document_title, quote=True)}" style="{style.style_for("img")}">'
        )
    normalized_lead = str(lead or "").strip()
    if normalized_lead:
        header_blocks.append(
            f'<p style="{style.style_for("p")}font-weight:650;">'
            f"{html.escape(normalized_lead, quote=False)}</p>"
        )
    header_html = "".join(header_blocks)
    return (
        "<!doctype html>"
        '<html lang="zh-CN"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(document_title, quote=False)}</title>"
        f'</head><body style="box-sizing:border-box;{style.body_style}">{header_html}{rendered.body_html}</body></html>'
    )


def _render_inline(
    value: str,
    base_dir: Path,
    image_resolver: ImageResolver | None,
    style: WechatMpHtmlStyle,
) -> str:
    tokens: dict[str, str] = {}

    def add_token(markup: str) -> str:
        token = f"WECHATMPTOKEN{len(tokens)}X"
        tokens[token] = markup
        return token

    def replace_image(match: re.Match[str]) -> str:
        source = match.group(2) or match.group(3) or ""
        image_path = _resolve_local_image_path(source, base_dir)
        if not image_path.is_file():
            raise WechatMpHtmlRenderError(f"正文图片不存在：{image_path}")
        image_src = image_resolver(image_path, match.group(1)) if image_resolver else source
        if not str(image_src or "").strip():
            raise WechatMpHtmlRenderError(f"正文图片解析失败：{image_path}")
        return add_token(
            f'<img src="{html.escape(str(image_src), quote=True)}" '
            f'alt="{html.escape(match.group(1), quote=True)}" style="{style.style_for("img")}">' 
        )

    value = _CODE_RE.sub(
        lambda match: add_token(
            f'<code style="{style.style_for("code")}">{html.escape(match.group(1), quote=False)}</code>'
        ),
        value,
    )
    value = _IMAGE_RE.sub(replace_image, value)
    value = _LINK_RE.sub(lambda match: match.group(1), value)
    value = _STRONG_RE.sub(
        lambda match: add_token(
            f'<strong style="{style.style_for("strong")}">'
            f"{html.escape(match.group(1) or match.group(2) or '', quote=False)}</strong>"
        ),
        value,
    )
    value = _EM_RE.sub(
        lambda match: add_token(
            f'<em style="{style.style_for("em")}">'
            f"{html.escape(match.group(1) or match.group(2) or '', quote=False)}</em>"
        ),
        value,
    )

    escaped = html.escape(value, quote=False)
    for token, markup in tokens.items():
        escaped = escaped.replace(token, markup)
    return escaped


def _resolve_local_image_path(source: str, base_dir: Path) -> Path:
    candidate = Path(source)
    if not candidate.is_absolute():
        parsed = urlparse(source)
        if parsed.scheme or source.startswith("//"):
            raise WechatMpHtmlRenderError("正文包含外部图片，请先保存为本地图片后再生成公众号 HTML")
        candidate = base_dir / source
    return candidate.resolve()


def _plain_inline_text(value: str) -> str:
    text = _IMAGE_RE.sub(lambda match: match.group(1), value)
    text = _LINK_RE.sub(lambda match: match.group(1), text)
    text = _CODE_RE.sub(lambda match: match.group(1), text)
    text = re.sub(r"\*{1,3}|_{1,3}|~~", "", text)
    return html.unescape(re.sub(r"\s+", " ", text).strip())


def _clean_title(value: str) -> str:
    return _plain_inline_text(str(value or ""))

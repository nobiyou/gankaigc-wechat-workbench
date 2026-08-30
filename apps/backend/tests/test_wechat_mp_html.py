from pathlib import Path

from app.services.wechat_mp_html import build_wechat_preview_document, render_wechat_html


def test_render_wechat_html_uses_inline_styles_and_removes_the_first_title(tmp_path: Path) -> None:
    image_path = tmp_path / "body.png"
    image_path.write_bytes(b"image")
    markdown = """# 文章标题

开头第一行
开头第二行，包含 **重点**、*强调*、`inline()` 和 [链接](https://example.com)。

## 第二部分

> 这是一段引用

- 第一项
- 第二项

1. 有序第一项
2. 有序第二项

```python
print('<安全内容>')
```

---

![配图](body.png)
"""

    rendered = render_wechat_html(
        markdown,
        base_dir=tmp_path,
        image_resolver=lambda path, _alt: f"/generated-assets/{path.name}",
    )

    assert rendered.title == "文章标题"
    assert "<h1" not in rendered.body_html
    assert '<h2 style="' in rendered.body_html
    assert '<p style="' in rendered.body_html
    assert '<blockquote style="' in rendered.body_html
    assert '<ul style="' in rendered.body_html
    assert '<ol style="' in rendered.body_html
    assert '<li style="' in rendered.body_html
    assert '<pre style="' in rendered.body_html
    assert '<code style="' in rendered.body_html
    assert '<hr style="' in rendered.body_html
    assert '<strong style="' in rendered.body_html
    assert '<em style="' in rendered.body_html
    assert 'src="/generated-assets/body.png"' in rendered.body_html
    assert "<br" not in rendered.body_html
    assert "https://example.com" not in rendered.body_html
    assert "&lt;安全内容&gt;" in rendered.body_html
    assert "<style" not in rendered.body_html
    assert "class=" not in rendered.body_html
    assert "id=" not in rendered.body_html
    assert "<script" not in rendered.body_html

    document = build_wechat_preview_document(rendered)
    assert document.startswith("<!doctype html>")
    assert '<title>文章标题</title>' in document
    assert '<body style="' in document
    assert '<h1 style="' in document


def test_build_wechat_preview_document_includes_publish_metadata() -> None:
    rendered = render_wechat_html("正文内容", title="文章标题")

    document = build_wechat_preview_document(
        rendered,
        title="文章标题",
        lead="这是文章导语。",
        cover_image_url="/generated-assets/cover.png",
    )

    assert '<h1 style="' in document
    assert "文章标题" in document
    assert "这是文章导语。" in document
    assert '<img src="/generated-assets/cover.png" alt="文章标题" style="' in document


def test_render_wechat_html_downgrades_later_h1_to_h2() -> None:
    rendered = render_wechat_html("# 首个标题\n\n# 正文中的标题\n\n内容")

    assert rendered.title == "首个标题"
    assert rendered.body_html.count("<h1") == 0
    assert rendered.body_html.count('<h2 style="') == 1

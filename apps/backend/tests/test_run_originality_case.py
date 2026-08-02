from __future__ import annotations

import importlib.util
import json
import os
import re
import tempfile
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_originality_case.py"
ZHUQUE_HELPER_PATH = REPO_ROOT / "scripts" / "run_zhuque_text_detector.js"


def _load_run_originality_case_module():
    spec = importlib.util.spec_from_file_location("run_originality_case_script", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_detector_templates_include_zhuque_helper(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    result_json = tmp_path / "result.json"
    payload = script._build_external_detector_templates(
        output_dir=tmp_path,
        source_file=str(tmp_path / "source.txt"),
        draft_file=str(tmp_path / "draft.txt"),
        result_json_path=result_json,
    )

    instructions = Path(payload["instructions_md"]).read_text(encoding="utf-8")
    assert "run_zhuque_text_detector.js" in instructions
    assert "--template-json" in instructions
    assert "--bundle-result-json" in instructions
    assert "--bundle-slot source" in instructions
    assert "--bundle-slot draft" in instructions
    assert "--capture-payload-file" in instructions
    assert "--captcha-payload-file" in instructions
    assert "--auth-payload-file" in instructions
    assert "--source-zhuque-report-file" in instructions
    assert "--draft-zhuque-report-file" in instructions
    assert "--source-zhuque-report-clipboard" in instructions
    assert "--draft-zhuque-report-clipboard" in instructions
    assert "source.txt" in instructions
    assert "draft.txt" in instructions


def test_to_detector_text_strips_markdown_surface() -> None:
    script = _load_run_originality_case_module()

    text = script._to_detector_text("# 标题\n\n**加粗** [链接](https://example.com)\n> 引用")

    assert text == "标题 加粗 链接 引用"


def test_request_budget_accounts_for_one_topic_retry() -> None:
    script = _load_run_originality_case_module()

    budget = script._build_request_budget(
        include_assets_publish=False,
        skip_metadata=True,
        reuse_topic=False,
    )

    assert budget["topic"] == 2


def test_request_budget_accounts_for_one_analysis_retry() -> None:
    script = _load_run_originality_case_module()

    budget = script._build_request_budget(
        include_assets_publish=False,
        skip_metadata=False,
        reuse_topic=False,
    )

    assert budget["metadata"] == 2


def test_request_budget_accounts_for_one_outline_retry() -> None:
    script = _load_run_originality_case_module()

    budget = script._build_request_budget(
        include_assets_publish=False,
        skip_metadata=True,
        reuse_topic=True,
    )

    assert budget["outline"] == 2


def test_infer_title_uses_first_complete_sentence_for_plain_text_source() -> None:
    script = _load_run_originality_case_module()

    assert script._infer_title("人活着，到底是为了什么？有一个最打动我的回答。", "fallback") == "人活着，到底是为了什么"


def test_reuse_bundle_identity_allows_title_variation_when_body_hash_matches() -> None:
    script = _load_run_originality_case_module()
    source_title = "人活着，到底是为了什么"
    source_markdown = "人活着，到底是为了什么？有一个最打动我的回答。"
    identity = script._build_source_identity(
        source_title=source_title,
        source_markdown=source_markdown,
    )

    result = script._validate_reuse_bundle_identity(
        reuse_bundle_payload={
            "source_title": "人活着，到底是为了什么",
            "source_identity": {
                "title": "人活着，到底是为了什么",
                "body_sha256": identity["body_sha256"],
            },
        },
        source_title="人活着，到底是为了什么？有一个最打动我的回答",
        source_markdown=source_markdown,
        bundle_json_path="matching-result.json",
    )

    assert result is not None
    assert result["validated"] is True
    assert result["title_match"] is False
    assert result["title_match_overridden_by_body_hash"] is True
    assert result["body_hash_match"] is True


def test_reuse_bundle_identity_rejects_different_source_title() -> None:
    script = _load_run_originality_case_module()

    with pytest.raises(ValueError, match="source_title 与当前文章不一致"):
        script._validate_reuse_bundle_identity(
            reuse_bundle_payload={
                "source_title": "另一篇文章",
                "source_identity": {
                    "title": "另一篇文章",
                    "body_sha256": "",
                },
            },
            source_title="当前文章",
            source_markdown="正文",
            bundle_json_path="old-result.json",
        )


def test_reuse_bundle_identity_rejects_different_source_body_hash() -> None:
    script = _load_run_originality_case_module()
    source_markdown = "第一段正文"
    source_identity = script._build_source_identity(
        source_title="当前文章",
        source_markdown=source_markdown,
    )

    with pytest.raises(ValueError, match="source body hash 与当前文章不一致"):
        script._validate_reuse_bundle_identity(
            reuse_bundle_payload={
                "source_identity": {
                    "title": "当前文章",
                    "body_sha256": "0" * 64,
                },
            },
            source_title="当前文章",
            source_markdown=source_markdown,
            bundle_json_path="old-result.json",
        )

    assert source_identity["body_sha256"] != "0" * 64


def test_reuse_bundle_identity_accepts_legacy_analysis_with_matching_source_identity() -> None:
    script = _load_run_originality_case_module()
    source_markdown = "当前文章正文"
    source_identity = script._build_source_identity(
        source_title="当前文章",
        source_markdown=source_markdown,
    )

    result = script._validate_reuse_bundle_identity(
        reuse_bundle_payload={
            "source_identity": source_identity,
            "tracked_article": {
                "analysis_theme": "当前文章的主题",
            },
        },
        source_title="当前文章",
        source_markdown=source_markdown,
        bundle_json_path="legacy-analysis-result.json",
    )

    assert result is not None
    assert result["validated"] is True
    assert result["analysis_provenance_source"] == "source_identity_legacy"


def test_reuse_bundle_identity_rejects_legacy_analysis_without_body_hash() -> None:
    script = _load_run_originality_case_module()

    with pytest.raises(ValueError, match="分析合同缺少 analysis_source_identity"):
        script._validate_reuse_bundle_identity(
            reuse_bundle_payload={
                "source_identity": {
                    "title": "当前文章",
                    "body_sha256": "",
                },
                "tracked_article": {
                    "analysis_theme": "旧文章的主题",
                },
            },
            source_title="当前文章",
            source_markdown="正文",
            bundle_json_path="legacy-analysis-result.json",
        )


def test_reuse_bundle_identity_rejects_analysis_provenance_for_different_body() -> None:
    script = _load_run_originality_case_module()
    source_markdown = "当前文章正文"
    source_identity = script._build_source_identity(
        source_title="当前文章",
        source_markdown=source_markdown,
    )
    old_identity = script._build_source_identity(
        source_title="旧文章",
        source_markdown="旧文章正文",
    )

    with pytest.raises(ValueError, match="分析合同的正文 hash 与当前文章不一致"):
        script._validate_reuse_bundle_identity(
            reuse_bundle_payload={
                "source_identity": source_identity,
                "analysis_source_identity": old_identity,
                "tracked_article": {
                    "analysis_theme": "旧文章的主题",
                },
            },
            source_title="当前文章",
            source_markdown=source_markdown,
            bundle_json_path="stale-analysis-result.json",
        )


def test_reuse_bundle_identity_accepts_analysis_with_matching_provenance() -> None:
    script = _load_run_originality_case_module()
    source_markdown = "当前文章正文"
    source_identity = script._build_source_identity(
        source_title="当前文章",
        source_markdown=source_markdown,
    )

    result = script._validate_reuse_bundle_identity(
        reuse_bundle_payload={
            "source_identity": source_identity,
            "analysis_source_identity": source_identity,
            "tracked_article": {
                "analysis_theme": "当前文章的主题",
            },
        },
        source_title="当前文章",
        source_markdown=source_markdown,
        bundle_json_path="matching-analysis-result.json",
    )

    assert result is not None
    assert result["validated"] is True
    assert result["analysis_contract_checked"] is True


def test_reuse_bundle_only_skips_metadata_when_analysis_contract_is_complete() -> None:
    script = _load_run_originality_case_module()
    args = script._build_parser().parse_args([])

    partial_bundle = {
        "tracked_article": {
            "analysis_theme": "只完成了主题字段",
        }
    }
    complete_bundle = {
        "tracked_article": {
            **{field: field for field in script._TRACKED_ARTICLE_ANALYSIS_FIELDS},
            "analysis_content_pillars": ["第一层内容", "第二层内容"],
        }
    }
    legacy_complete_bundle = {
        "tracked_article": {field: field for field in script._TRACKED_ARTICLE_ANALYSIS_FIELDS}
    }

    assert script._should_skip_tracked_article_enrichment(
        args=args,
        reuse_bundle_payload=partial_bundle,
    ) is False
    assert script._should_skip_tracked_article_enrichment(
        args=args,
        reuse_bundle_payload=complete_bundle,
    ) is True
    assert script._should_skip_tracked_article_enrichment(
        args=args,
        reuse_bundle_payload=legacy_complete_bundle,
    ) is False


def test_reuse_bundle_identity_accepts_legacy_title_only_bundle() -> None:
    script = _load_run_originality_case_module()

    result = script._validate_reuse_bundle_identity(
        reuse_bundle_payload={
            "source_title": "当前文章",
            "topic": {"title": "当前文章"},
        },
        source_title="当前文章",
        source_markdown="正文",
        bundle_json_path="legacy-result.json",
    )

    assert result is not None
    assert result["validated"] is True
    assert result["analysis_contract_checked"] is False
    assert result["body_hash_checked"] is False
    assert result["body_hash_match"] is None


def test_build_tracked_article_seed_sanitizes_reused_responsibility_metadata() -> None:
    script = _load_run_originality_case_module()

    def fake_sanitizer(metadata, *, article_title: str, body_markdown: str, tags: list[str]):
        assert article_title == "万般辛苦，皆为序章"
        assert "电话" in body_markdown
        assert tags == ["长期扛压", "不能倒"]
        return {
            **metadata,
            "summary": "长期把家里的事放在心上，也会被家里人的回应托住。",
            "structure_notes": "先写现实开销，再写家里的踏实。",
            "analysis_theme": "责任和被惦记互相托住。",
            "analysis_hook_trigger": "家里临时有事时，自己先把顺序理清。",
            "analysis_progression_drive": "从一个人的安排，走向家里的分担。",
            "analysis_share_reason": "让认真照顾日子的人被看见。",
            "tags": ["责任被看见", "家里踏实"],
        }

    seed = script._build_tracked_article_seed(
        article_slug="article-responsibility-seed",
        article_title="万般辛苦，皆为序章",
        source_markdown="电话这头，是父母、孩子和现实开销。",
        source_name="manual",
        reuse_bundle_payload={
            "tracked_article": {
                "author": "原作者",
                "summary": "长期扛压，暂时不能倒，辛苦没有白扛。",
                "structure_notes": "为什么这么苦还要撑，最后写成苦情赞歌。",
                "analysis_theme": "硬撑和不能倒下。",
                "analysis_hook_trigger": "白天扛事晚上崩一下。",
                "analysis_progression_drive": "多能扛才有回报。",
                "analysis_share_reason": "辛苦没有白扛。",
                "source_name": "old-run",
                "tags": ["长期扛压", "不能倒"],
            }
        },
        metadata_sanitizer=fake_sanitizer,
    )

    combined = json.dumps(seed, ensure_ascii=False)
    for forbidden in (
        "长期扛压",
        "暂时不能倒",
        "不能倒下",
        "辛苦没有白扛",
        "白天扛事晚上崩一下",
        "为什么这么苦还要撑",
        "苦情赞歌",
        "多能扛",
    ):
        assert forbidden not in combined
    assert seed["author"] == "原作者"
    assert seed["source_name"] == "old-run"
    assert seed["tags"] == ["责任被看见", "家里踏实"]
    assert seed["analysis_hook_trigger"] == "家里临时有事时，自己先把顺序理清。"


def test_probe_ai_text_routes_collects_route_status_from_backend_mapping() -> None:
    script = _load_run_originality_case_module()

    class FakeResponses:
        def create(self, **kwargs):
            if kwargs.get("input") == "Reply with exactly OK.":
                class FakeResponse:
                    output_text = "OK"

                return FakeResponse()

            class FakeJsonResponse:
                output_text = '{"title":"ok","angle":"ok"}'

            return FakeJsonResponse()

        def parse(self, **kwargs):
            class FakeParsedResponse:
                output_parsed = FakeTopicGenerationResult("ok", "ok")
                output_text = '{"title":"ok","angle":"ok"}'

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            class FakeMessage:
                content = '{"title":"ok","angle":"ok"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeClient:
        responses = FakeResponses()
        chat = FakeChat()

    class FakeGenerator:
        def __init__(self, _settings) -> None:
            self._client = FakeClient()

    class FakeTopicGenerationResult:
        def __init__(self, title: str, angle: str) -> None:
            self.title = title
            self.angle = angle

        def model_dump(self) -> dict[str, str]:
            return {"title": self.title, "angle": self.angle}

    class FakeSettings:
        openai_model = "gpt-5.4-mini"
        openai_request_timeout_seconds = 12.0

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "model": "gpt-5.4-mini",
                "base_url": "https://proxy.example/v1",
                "image_model": "gpt-image-2",
                "image_base_url": "https://proxy.example/v1",
                "image_api_key_configured": True,
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "api_key_configured": True,
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    payload = script._probe_ai_text_routes(
        {
            "settings": FakeSettings(),
            "OpenAIWorkbenchGenerator": FakeGenerator,
            "TopicGenerationResult": FakeTopicGenerationResult,
            "get_ai_config_summary": lambda: FakeSummary(),
        }
    )

    assert payload["ai_config"]["model"] == "gpt-5.4-mini"
    assert payload["routes"]["responses_create_text"]["ok"] is True
    assert payload["routes"]["responses_create_json_text"]["ok"] is True
    assert payload["routes"]["responses_parse_topic"]["ok"] is True
    assert payload["routes"]["chat_completions_json"]["ok"] is True


def test_probe_ai_image_routes_collects_route_status_from_backend_mapping() -> None:
    script = _load_run_originality_case_module()

    class FakeGenerator:
        def __init__(self, _settings) -> None:
            self._image_routes = [
                {"label": "primary", "model": "primary-image-model", "base_url": "https://primary.example/v1"},
                {"label": "fallback", "model": "fallback-image-model", "base_url": "https://fallback.example/v1"},
            ]

        def _generate_cover_image_with_route(self, prompt: str):
            assert "16:9" in prompt
            route = self._image_routes[0]
            if route["label"] == "primary":
                raise RuntimeError("primary image route unavailable")
            return (b"fallback-cover", "fallback")

    class FakeSettings:
        openai_api_key = "test-key"

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
                "image_model": "primary-image-model",
                "image_api_key_configured": True,
                "image_base_url": "https://primary.example/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": True,
                "image_fallback_route_configured": True,
                "image_fallback_route_active": True,
                "image_fallback_model": "fallback-image-model",
                "image_fallback_base_url": "https://fallback.example/v1",
                "image_fallback_route_difference_labels": ["模型", "接口"],
                "image_fallback_route_note": "备用图片链路已生效；它与主出图链路的差异项：模型、接口。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    payload = script._probe_ai_image_routes(
        {
            "settings": FakeSettings(),
            "OpenAIWorkbenchGenerator": FakeGenerator,
            "get_ai_config_summary": lambda: FakeSummary(),
        }
    )

    assert payload["routes"]["primary"]["ok"] is False
    assert payload["routes"]["primary"]["configured_model"] == "primary-image-model"
    assert payload["routes"]["fallback"]["ok"] is True
    assert payload["routes"]["fallback"]["used_route_label"] == "fallback"
    assert payload["routes"]["fallback"]["byte_length"] == len(b"fallback-cover")


def test_parse_zhuque_report_text_extracts_score_and_band() -> None:
    script = _load_run_originality_case_module()
    payload = script._parse_zhuque_report_text(
        """
        未发现明显的人工创作特征
        朱雀AI生成检测报告单
        检测时间：2026/6/1 21:08:59
        检测结果
        AI分布图
        人工特征 (AIGC值: 0-0.5)
        疑似AI (AIGC值: 0.5-0.99)
        AI特征 (AIGC值: 0.99-1)
        片段解析
        序号 片段 占全文比例 占字符数 AIGC值
        1
        片段1
        100.00%
        1725
        0.9351
        检测片段详情
        NO. 1 片段1 AIGC值 0.9351
        """
    )

    assert payload["confidence"] == 0.9351
    assert payload["raw_result"]["classification_band"] == "疑似AI"
    assert payload["raw_result"]["classification_range"] == "0.5-0.99"
    assert payload["raw_result"]["segment_ratio"] == "100.00%"
    assert payload["raw_result"]["segment_chars"] == 1725
    assert payload["raw_result"]["verdict_text"] == "未发现明显的人工创作特征"


def test_parse_zhuque_report_text_prefers_segment_score_over_band_header_value() -> None:
    script = _load_run_originality_case_module()
    payload = script._parse_zhuque_report_text(
        """
        未发现明显的人工创作特征
        朱雀AI生成检测报告单
        检测时间：2026/6/3 12:35:50
        检测结果
        AI分布图
        人工特征 (AIGC值: 0-0.5)
        疑似AI (AIGC值: 0.5-0.99)
        AI特征 (AIGC值: 0.99-1)
        片段解析
        序号 片段 占全文比例 占字符数 AIGC值
        1 片段1 100.00% 1986 0.9
        """
    )

    assert payload["confidence"] == 0.9
    assert payload["raw_result"]["classification_band"] == "疑似AI"
    assert payload["raw_result"]["classification_range"] == "0.5-0.99"
    assert payload["raw_result"]["segment_ratio"] == "100.00%"
    assert payload["raw_result"]["segment_chars"] == 1986
    assert payload["raw_result"]["aigc_value"] == 0.9


def test_read_detector_payload_accepts_zhuque_report_file(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    report_file = tmp_path / "zhuque-report.txt"
    report_file.write_text(
        """
        未发现明显的人工创作特征
        朱雀AI生成检测报告单
        检测时间：2026/6/1 21:14:02
        AI分布图
        人工特征 (AIGC值: 0-0.5)
        疑似AI (AIGC值: 0.5-0.99)
        AI特征 (AIGC值: 0.99-1)
        序号 片段 占全文比例 占字符数 AIGC值
        1 片段1 100.00% 909 0.9984
        NO. 1 片段1 AIGC值 0.9984
        """,
        encoding="utf-8",
    )

    payload = script._read_detector_payload(
        json_file=None,
        score=None,
        zhuque_report_file=str(report_file),
    )

    assert payload is not None
    assert payload["confidence"] == 0.9984
    assert payload["raw_result"]["classification_band"] == "AI特征"
    assert payload["raw_result"]["segment_chars"] == 909


def test_read_detector_payload_accepts_zhuque_report_clipboard(monkeypatch) -> None:
    script = _load_run_originality_case_module()
    monkeypatch.setattr(
        script,
        "_read_clipboard_text",
        lambda: """
        存在疑似AI生成特征
        朱雀AI生成检测报告单
        检测时间：2026/6/3 09:08:59
        AI分布图
        人工特征 (AIGC值: 0-0.5)
        疑似AI (AIGC值: 0.5-0.99)
        AI特征 (AIGC值: 0.99-1)
        序号 片段 占全文比例 占字符数 AIGC值
        1 片段1 100.00% 1885 0.9152
        NO. 1 片段1 AIGC值 0.9152
        """,
    )

    payload = script._read_detector_payload(
        json_file=None,
        score=None,
        zhuque_report_clipboard=True,
    )

    assert payload is not None
    assert payload["confidence"] == 0.9152
    assert payload["raw_result"]["classification_band"] == "疑似AI"
    assert payload["raw_result"]["segment_chars"] == 1885
    assert payload["raw_result"]["verdict_text"] == "存在疑似AI生成特征"


def test_maybe_build_external_detector_report_allows_partial_clipboard_merge(monkeypatch) -> None:
    script = _load_run_originality_case_module()
    monkeypatch.setattr(
        script,
        "_read_clipboard_text",
        lambda: """
        未发现明显的人工创作特征
        朱雀AI生成检测报告单
        检测时间：2026/6/3 10:14:02
        AI分布图
        人工特征 (AIGC值: 0-0.5)
        疑似AI (AIGC值: 0.5-0.99)
        AI特征 (AIGC值: 0.99-1)
        序号 片段 占全文比例 占字符数 AIGC值
        1 片段1 100.00% 909 0.9984
        NO. 1 片段1 AIGC值 0.9984
        """,
    )
    args = script._build_parser().parse_args(
        [
            "--attach-result-json",
            "dummy.json",
            "--external-detector-name",
            "zhuque_tencent_text",
            "--source-zhuque-report-clipboard",
        ]
    )

    existing_report = {
        "name": "zhuque_tencent_text",
        "draft": {
            "confidence": 0.9152,
            "detector_url": "https://matrix.tencent.com/ai-detect/ai_gen_txt",
            "captured_at": "",
            "notes": "existing draft result",
            "raw_result": {
                "classification_band": "疑似AI",
                "aigc_value": 0.9152,
            },
        },
        "summary": {
            "draft_score": 0.9152,
        },
    }

    report = script._maybe_build_external_detector_report(
        args,
        existing_report=existing_report,
        allow_partial=True,
    )

    assert report is not None
    assert report["source"]["confidence"] == 0.9984
    assert report["draft"]["confidence"] == 0.9152
    assert report["summary"]["source_score"] == 0.9984
    assert report["summary"]["draft_score"] == 0.9152
    assert report["summary"]["delta"] == -0.0832
    assert report["summary"]["verdict"] == "draft_lower_than_source"


def test_maybe_build_external_detector_report_rebinds_existing_report_without_new_inputs() -> None:
    script = _load_run_originality_case_module()
    args = script._build_parser().parse_args(
        [
            "--attach-result-json",
            "dummy.json",
            "--external-detector-name",
            "zhuque_tencent_text",
        ]
    )

    existing_report = {
        "name": "zhuque_tencent_text",
        "source": {
            "confidence": 0.9984,
            "raw_result": {
                "segment_chars": 9,
            },
        },
        "draft": {
            "confidence": 0.9152,
            "raw_result": {
                "segment_chars": 15,
            },
        },
        "summary": {
            "source_score": 0.9984,
            "draft_score": 0.9152,
        },
    }

    report = script._maybe_build_external_detector_report(
        args,
        existing_report=existing_report,
        allow_partial=True,
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    assert report is not None
    assert report["summary"]["source_binding_ok"] is True
    assert report["summary"]["draft_binding_ok"] is False
    assert report["summary"]["binding_verdict"] == "draft_mismatch"
    assert report["draft"]["input_meta"]["detector_text_chars"] == 11


def test_build_external_detector_report_binds_detector_text_meta() -> None:
    script = _load_run_originality_case_module()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {
                "segment_chars": 9,
            },
        },
        draft_payload={
            "confidence": 0.9152,
            "raw_result": {
                "segment_chars": 11,
            },
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    assert report["source"]["input_meta"]["detector_text_chars"] == 9
    assert report["source"]["input_meta"]["segment_chars_match"] is True
    assert report["source"]["input_meta"]["segment_chars_delta"] == 0
    assert len(report["source"]["input_meta"]["detector_text_sha256"]) == 64
    assert report["draft"]["input_meta"]["detector_text_chars"] == 11
    assert report["draft"]["input_meta"]["segment_chars_match"] is True
    assert report["draft"]["input_meta"]["segment_chars_delta"] == 0
    assert len(report["draft"]["input_meta"]["detector_text_sha256"]) == 64
    assert report["summary"]["source_binding_ok"] is True
    assert report["summary"]["draft_binding_ok"] is True
    assert report["summary"]["binding_verdict"] == "source_and_draft_bound"


def test_build_external_detector_report_flags_segment_char_mismatch() -> None:
    script = _load_run_originality_case_module()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload=None,
        draft_payload={
            "confidence": 0.9418,
            "raw_result": {
                "segment_chars": 2031,
            },
        },
        draft_detector_text="x" * 1650,
    )

    assert report["draft"]["input_meta"]["detector_text_chars"] == 1650
    assert report["draft"]["input_meta"]["segment_chars_match"] is False
    assert report["draft"]["input_meta"]["segment_chars_delta"] == -381
    assert report["summary"]["draft_binding_ok"] is False
    assert report["summary"]["binding_verdict"] == "draft_mismatch"


def test_build_external_detector_report_marks_partial_binding_in_summary() -> None:
    script = _load_run_originality_case_module()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {
                "segment_chars": 9,
            },
        },
        draft_payload={
            "confidence": 0.9152,
            "raw_result": {
                "segment_chars": 15,
            },
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    assert report["summary"]["source_binding_ok"] is True
    assert report["summary"]["draft_binding_ok"] is False
    assert report["summary"]["binding_verdict"] == "draft_mismatch"


def test_audit_external_detector_report_marks_trusted_bundle() -> None:
    script = _load_run_originality_case_module()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {
                "segment_chars": 9,
            },
        },
        draft_payload={
            "confidence": 0.9351,
            "raw_result": {
                "segment_chars": 11,
            },
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    audit = script._audit_external_detector_report(report)

    assert audit["detector_name"] == "zhuque_tencent_text"
    assert audit["source_binding_ok"] is True
    assert audit["draft_binding_ok"] is True
    assert audit["binding_verdict"] == "source_and_draft_bound"
    assert audit["trust_status"] == "trusted"


def test_audit_external_detector_report_marks_draft_mismatch_bundle() -> None:
    script = _load_run_originality_case_module()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {
                "segment_chars": 9,
            },
        },
        draft_payload={
            "confidence": 0.8123,
            "raw_result": {
                "segment_chars": 15,
            },
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    audit = script._audit_external_detector_report(report)

    assert audit["source_binding_ok"] is True
    assert audit["draft_binding_ok"] is False
    assert audit["binding_verdict"] == "draft_mismatch"
    assert audit["trust_status"] == "untrusted"


def test_audit_external_detector_report_marks_missing_binding_as_unverified() -> None:
    script = _load_run_originality_case_module()

    audit = script._audit_external_detector_report(
        {
            "name": "zhuque_tencent_text",
            "summary": {
                "draft_score": 0.9152,
            },
            "draft": {
                "confidence": 0.9152,
                "raw_result": {
                    "segment_chars": 1885,
                },
            },
        }
    )

    assert audit["source_binding_ok"] is None
    assert audit["draft_binding_ok"] is None
    assert audit["binding_verdict"] is None
    assert audit["trust_status"] == "unverified"


def test_audit_bundle_draft_consistency_marks_matching_bundle() -> None:
    script = _load_run_originality_case_module()

    bundle_payload = {
        "draft": {
            "body_markdown": "# 标题\n\n正文",
        }
    }

    audit = script._audit_bundle_draft_consistency(
        bundle_payload,
        bundle_dir=Path("."),
    )

    assert audit["draft_bundle_consistent"] is None
    assert audit["draft_bundle_verdict"] == "artifact_missing_draft_md"
    assert audit["result_draft_chars"] == len("# 标题\n\n正文")
    assert audit["artifact_draft_chars"] is None


def test_audit_external_detector_result_root_reports_draft_bundle_mismatch(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    mismatch_dir = tmp_path / "bundle-mismatch"
    mismatch_dir.mkdir()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {"segment_chars": 9},
        },
        draft_payload={
            "confidence": 0.9351,
            "raw_result": {"segment_chars": 11},
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    (mismatch_dir / "draft.md").write_text("# 标题\n\n磁盘稿件", encoding="utf-8")
    (mismatch_dir / "result.json").write_text(
        json.dumps(
            {
                "draft": {
                    "body_markdown": "# 标题\n\n结果稿件",
                },
                "external_detector": report,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    audit = script._audit_external_detector_result_root(tmp_path)

    assert audit["summary"]["consistent_draft_bundles"] == 0
    assert audit["summary"]["drifted_draft_bundles"] == 1
    assert audit["summary"]["unknown_draft_bundles"] == 0
    item = audit["results"][0]
    assert item["draft_bundle_consistent"] is False
    assert item["draft_bundle_verdict"] == "bundle_and_artifact_mismatch"


def test_audit_bundle_current_cleanup_preview_marks_improvement_candidate(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()

    bundle_payload = {
        "draft": {
            "title": "她在电梯口扶住门的那一秒，身体已经先开口了",
            "body_markdown": (
                "电梯门快要合上的时候，她伸手挡了一下。\n\n"
                "金属门沿碰到手背，凉了一瞬。人是进来了，心口却突然空了一拍，像踩空楼梯那种短促的失重。她站稳，先低头看手机，聊天框顶着一句：文件到了吗。拇指飞快敲了两个字：马上。\n\n"
                "电梯往上走，镜面里的人脸色有点白。她盯着数字跳，没把那口气补完整。刚才那下心慌，按理说该停一停，至少靠着轿厢站会儿，等胸口缓过来。可屏幕亮着，红点还在，她下意识先把身体往后排。\n\n"
                "这时候最容易发生的误认，是把报警当偷懒。\n\n"
                "明明已经开始耗了，她还会拿“别人也这么忙”压自己，拿“就这几天”拖自己，拿“先把这件做完”借自己。每回只借走一小截体力，借走一点耐心，借走一次好好吃饭和好好说话的机会。表面看都不算大事，拼在一起，人才会慢慢变成现在这样：反应迟，睡不好，不想回消息，不想解释，坐着都像在咬牙。\n"
            ),
        }
    }

    audit = script._audit_bundle_current_cleanup_preview(
        bundle_payload,
        bundle_dir=tmp_path,
    )

    assert audit["current_cleanup_available"] is True
    assert audit["current_cleanup_source"] == "result_draft_body"
    assert audit["current_cleanup_applied"] is True
    assert audit["current_cleanup_improved"] is True
    assert audit["current_cleanup_score_improved"] is True
    assert audit["current_cleanup_structural_improved"] is True
    assert audit["current_cleanup_cleaned_score"] < audit["current_cleanup_original_score"]
    assert audit["current_cleanup_cleaned_residue_score"] < audit["current_cleanup_original_residue_score"]
    assert audit["current_cleanup_score_delta"] > 0
    assert audit["current_cleanup_structural_residue_delta"] > 0
    assert "ai_flavor_score" in audit["current_cleanup_improvement_axes"]
    assert "structural_residue" in audit["current_cleanup_improvement_axes"]
    assert "collapse_leading_short_long_cadence_residue" in audit["current_cleanup_changed_steps"]


def test_audit_bundle_current_cleanup_preview_marks_structural_only_improvement(tmp_path: Path, monkeypatch) -> None:
    script = _load_run_originality_case_module()

    monkeypatch.setattr(
        script,
        "_apply_current_compare_cleanups",
        lambda *, title, draft_markdown: (
            draft_markdown,
            {
                "applied": True,
                "steps": [{"name": "collapse_over_segmented_shell_residue", "changed": True}],
                "original_ai_flavor": {"score": 12},
                "cleaned_ai_flavor": {"score": 12},
                "original_structural_residue": {"residue_score": 9},
                "cleaned_structural_residue": {"residue_score": 3},
            },
        ),
    )

    bundle_payload = {
        "draft": {
            "title": "测试标题",
            "body_markdown": "第一段。\n\n第二段。",
        }
    }

    audit = script._audit_bundle_current_cleanup_preview(
        bundle_payload,
        bundle_dir=tmp_path,
    )

    assert audit["current_cleanup_available"] is True
    assert audit["current_cleanup_improved"] is True
    assert audit["current_cleanup_score_improved"] is False
    assert audit["current_cleanup_structural_improved"] is True
    assert audit["current_cleanup_original_residue_score"] == 9
    assert audit["current_cleanup_cleaned_residue_score"] == 3
    assert audit["current_cleanup_score_delta"] == 0
    assert audit["current_cleanup_structural_residue_delta"] == 6
    assert audit["current_cleanup_improvement_axes"] == ["structural_residue"]


def test_audit_external_detector_result_root_summarizes_trust_counts(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    trusted_dir = tmp_path / "trusted-bundle"
    mismatch_dir = tmp_path / "mismatch-bundle"
    trusted_dir.mkdir()
    mismatch_dir.mkdir()

    trusted_report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {"segment_chars": 9},
        },
        draft_payload={
            "confidence": 0.9351,
            "raw_result": {"segment_chars": 11},
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )
    mismatch_report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {"segment_chars": 9},
        },
        draft_payload={
            "confidence": 0.8123,
            "raw_result": {"segment_chars": 15},
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )

    (trusted_dir / "result.json").write_text(
        json.dumps(
            {
                "draft": {"body_markdown": "hello world"},
                "external_detector": trusted_report,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (mismatch_dir / "result.json").write_text(
        json.dumps(
            {
                "draft": {"body_markdown": "hello world!!!"},
                "external_detector": mismatch_report,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (trusted_dir / "draft.md").write_text("hello world", encoding="utf-8")
    (mismatch_dir / "draft.md").write_text("hello world!!!", encoding="utf-8")

    audit = script._audit_external_detector_result_root(tmp_path)

    assert audit["root"] == str(tmp_path.resolve())
    assert audit["summary"]["total_result_files"] == 2
    assert audit["summary"]["audited_reports"] == 2
    assert audit["summary"]["trusted_reports"] == 1
    assert audit["summary"]["untrusted_reports"] == 1
    assert audit["summary"]["unverified_reports"] == 0
    assert audit["summary"]["consistent_draft_bundles"] == 2
    assert audit["summary"]["drifted_draft_bundles"] == 0
    assert audit["summary"]["unknown_draft_bundles"] == 0
    assert audit["summary"]["cleanup_preview_improved_bundles"] == 0
    assert audit["summary"]["cleanup_preview_unchanged_bundles"] == 2
    assert audit["summary"]["cleanup_preview_unavailable_bundles"] == 0
    assert audit["summary"]["cleanup_preview_score_improved_bundles"] == 0
    assert audit["summary"]["cleanup_preview_structural_improved_bundles"] == 0
    assert audit["summary"]["cleanup_preview_score_delta_total"] == 0
    assert audit["summary"]["cleanup_preview_structural_residue_delta_total"] == 0
    assert audit["summary"]["trusted_cleanup_replay_candidates"] == 0
    assert audit["summary"]["trusted_cleanup_replay_top_labels"] == []
    assert audit["summary"]["trusted_cleanup_replay_top_candidates"] == []
    labels = {item["label"]: item["trust_status"] for item in audit["results"]}
    assert labels == {
        "mismatch-bundle": "untrusted",
        "trusted-bundle": "trusted",
    }


def test_audit_result_json_cli_reports_bundle_consistency(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    bundle_dir = tmp_path / "trusted-bundle"
    bundle_dir.mkdir()

    report = script._build_external_detector_report(
        detector_name="zhuque_tencent_text",
        source_payload={
            "confidence": 0.9984,
            "raw_result": {"segment_chars": 9},
        },
        draft_payload={
            "confidence": 0.9351,
            "raw_result": {"segment_chars": 11},
        },
        source_detector_text="123456789",
        draft_detector_text="hello world",
    )
    (bundle_dir / "draft.md").write_text("hello world", encoding="utf-8")
    result_json = bundle_dir / "result.json"
    result_json.write_text(
        json.dumps(
            {
                "draft": {"body_markdown": "hello world"},
                "external_detector": report,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--audit-result-json",
            str(result_json),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["trust_status"] == "trusted"
    assert payload["draft_bundle_consistent"] is True
    assert payload["draft_bundle_verdict"] == "bundle_and_artifact_match"
    assert payload["current_cleanup_available"] is True


def test_zhuque_helper_help_smoke() -> None:
    completed = subprocess.run(
        ["node", str(ZHUQUE_HELPER_PATH), "--help"],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0
    combined_output = f"{completed.stdout}\n{completed.stderr}"
    assert "--input-file" in combined_output
    assert "--bundle-result-json" in combined_output
    assert "--capture-payload-file" in combined_output
    assert "--captcha-payload-file" in combined_output
    assert "--auth-payload-file" in combined_output


def test_zhuque_helper_resends_access_token_after_fp_bootstrap() -> None:
    node_script = f"""
const helper = require({str(ZHUQUE_HELPER_PATH)!r});

class MockWebSocket {{
  constructor() {{
    this.sent = [];
    setImmediate(() => this.onopen && this.onopen());
  }}

  send(payload) {{
    this.sent.push(JSON.parse(payload));
    if (this.sent.length === 1) {{
      setImmediate(() => this.onmessage && this.onmessage({{
        data: JSON.stringify({{ access_token: "token-from-server" }})
      }}));
      setImmediate(() => this.onmessage && this.onmessage({{
        data: JSON.stringify({{ status: "success", availableUses: 3 }})
      }}));
    }}
  }}

  close() {{
    setImmediate(() => this.onclose && this.onclose({{ code: 1000, reason: "done" }}));
  }}
}}

global.WebSocket = MockWebSocket;

helper.runDetector({{
  text: "这是一段足够长的测试文本".repeat(40),
  wsUrl: "ws://mocked",
  pageUrl: "https://example.com/detector",
  resultUrl: "https://example.com/result",
  timeoutMs: 2000,
  pollIntervalMs: 1,
  maxPolls: 1,
}}).then((payload) => {{
  process.stdout.write(JSON.stringify(payload));
}}, (error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    payload = completed.stdout
    assert '"status":"needs_ticket"' in payload.replace(" ", "").replace("\n", "")
    assert '"auth_mode":"fp_bootstrap_access_token"' in payload.replace(" ", "").replace("\n", "")
    assert '"type":"send_access_token"' in payload.replace(" ", "").replace("\n", "")


def test_zhuque_helper_marks_reauth_as_browser_auth() -> None:
    node_script = f"""
const helper = require({str(ZHUQUE_HELPER_PATH)!r});

class MockWebSocket {{
  constructor() {{
    setImmediate(() => this.onopen && this.onopen());
  }}

  send() {{
    setImmediate(() => this.onmessage && this.onmessage({{
      data: JSON.stringify({{ status: "reauth" }})
    }}));
  }}

  close() {{
    setImmediate(() => this.onclose && this.onclose({{ code: 1000, reason: "reauth" }}));
  }}
}}

global.WebSocket = MockWebSocket;

helper.runDetector({{
  text: "这是一段足够长的测试文本".repeat(40),
  wsUrl: "ws://mocked",
  pageUrl: "https://example.com/detector",
  resultUrl: "https://example.com/result",
  timeoutMs: 2000,
  pollIntervalMs: 1,
  maxPolls: 1,
}}).then((payload) => {{
  process.stdout.write(JSON.stringify(payload));
}}, (error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    payload = completed.stdout
    normalized = payload.replace(" ", "").replace("\n", "")
    assert '"status":"needs_browser_auth"' in normalized
    assert '"auth_dump_snippet"' in normalized


def test_zhuque_helper_capture_payload_file_combines_auth_and_captcha(tmp_path: Path) -> None:
    capture_file = tmp_path / "capture.txt"
    capture_file.write_text(
        '\n'.join(
            [
                'ZHUQUE_AUTH_PAYLOAD {"access_token":"auth-token","fp":"fp-value"}',
                'ZHUQUE_CAPTCHA_PAYLOAD {"ticket":"ticket-value","randstr":"rand-value"}',
                'ZHUQUE_COMBINED_PAYLOAD {"auth":{"access_token":"auth-token","fp":"fp-value"},"captcha":{"ticket":"ticket-value","randstr":"rand-value"}}',
            ]
        ),
        encoding="utf-8",
    )

    node_script = f"""
const helper = require({str(ZHUQUE_HELPER_PATH)!r});
const args = helper.parseArgs([
  "--capture-payload-file",
  {str(capture_file)!r},
]);
const authPayload = helper.normalizeAuthPayload(args);
const captchaPayload = helper.normalizeCaptchaPayload(args);
process.stdout.write(JSON.stringify({{ authPayload, captchaPayload }}));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    normalized = completed.stdout.replace(" ", "").replace("\n", "")
    assert '"accessToken":"auth-token"' in normalized
    assert '"fp":"fp-value"' in normalized
    assert '"ticket":"ticket-value"' in normalized
    assert '"randstr":"rand-value"' in normalized


def test_zhuque_helper_capture_payload_text_combines_auth_and_captcha() -> None:
    capture_text = '\n'.join(
        [
            'debug line',
            'ZHUQUE_COMBINED_PAYLOAD {"auth":{"access_token":"text-token","fp":"text-fp"},"captcha":{"ticket":"text-ticket","randstr":"text-rand"}}',
        ]
    )

    node_script = f"""
const helper = require({str(ZHUQUE_HELPER_PATH)!r});
const args = helper.parseArgs([
  "--capture-payload-text",
  {capture_text!r},
]);
const authPayload = helper.normalizeAuthPayload(args);
const captchaPayload = helper.normalizeCaptchaPayload(args);
process.stdout.write(JSON.stringify({{ authPayload, captchaPayload }}));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    normalized = completed.stdout.replace(" ", "").replace("\n", "")
    assert '"accessToken":"text-token"' in normalized
    assert '"fp":"text-fp"' in normalized
    assert '"ticket":"text-ticket"' in normalized
    assert '"randstr":"text-rand"' in normalized


def test_zhuque_helper_capture_payload_clipboard_combines_auth_and_captcha() -> None:
    node_script = f"""
const childProcess = require("node:child_process");
const helper = require({str(ZHUQUE_HELPER_PATH)!r});

childProcess.execFileSync = () =>
  'ZHUQUE_COMBINED_PAYLOAD {{"auth":{{"access_token":"clip-token","fp":"clip-fp"}},"captcha":{{"ticket":"clip-ticket","randstr":"clip-rand"}}}}';

const args = helper.parseArgs(["--capture-payload-clipboard"]);
const authPayload = helper.normalizeAuthPayload(args);
const captchaPayload = helper.normalizeCaptchaPayload(args);
process.stdout.write(JSON.stringify({{ authPayload, captchaPayload }}));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    normalized = completed.stdout.replace(" ", "").replace("\n", "")
    assert '"accessToken":"clip-token"' in normalized
    assert '"fp":"clip-fp"' in normalized
    assert '"ticket":"clip-ticket"' in normalized
    assert '"randstr":"clip-rand"' in normalized


def test_zhuque_helper_extracts_auth_from_leveldb_text() -> None:
    leveldb_text = (
        "randomprefix"
        "aiGenAccessToken"
        '{"value":"'
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJ1aWQ"
        "AYTEwZDVlN2E5MTE2NDQyYWJkOTI2MWE1MWY5MTNlOSIsImV4"
        "MTc4MDkxMjM5NTA5NX0."
        "qcBVUrPcW6v0X2ZCAdx8qAREGN4w2XMMA7YWueLFu1A"
        '","expiry":1780912394592,"uid":"@a10d5e7a9116442abd9261a51f913e9"}'
        "_immortal|fp_3fcb29b96fc20f6903afe37db140ff92"
    )

    node_script = f"""
const helper = require({str(ZHUQUE_HELPER_PATH)!r});
const payload = helper.extractChromeAuthPayloadFromLevelDbText({leveldb_text!r});
const fp = helper.extractChromeFingerprintFromLevelDbText({leveldb_text!r});
process.stdout.write(JSON.stringify({{ payload, fp }}));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    normalized = completed.stdout.replace(" ", "").replace("\n", "")
    assert '"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJAYTEwZDVlN2E5MTE2NDQyYWJkOTI2MWE1MWY5MTNlOSIsImV4cCI6MTc4MDkxMjM5NTA5NX0.qcBVUrPcW6v0X2ZCAdx8qAREGN4w2XMMA7YWueLFu1A"' in normalized
    assert '"fp":"3fcb29b96fc20f6903afe37db140ff92"' in normalized


def test_zhuque_helper_normalize_auth_can_recover_from_local_storage(tmp_path: Path) -> None:
    leveldb_dir = (
        tmp_path
        / "Google"
        / "Chrome"
        / "User Data"
        / "Default"
        / "Local Storage"
        / "leveldb"
    )
    leveldb_dir.mkdir(parents=True)
    (leveldb_dir / "000001.ldb").write_text(
        "aiGenAccessToken"
        '{"value":"'
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJ1aWQ"
        "AYTEwZDVlN2E5MTE2NDQyYWJkOTI2MWE1MWY5MTNlOSIsImV4"
        "MTc4MDkxMjM5NTA5NX0."
        "qcBVUrPcW6v0X2ZCAdx8qAREGN4w2XMMA7YWueLFu1A"
        '","expiry":1780912394592,"uid":"@a10d5e7a9116442abd9261a51f913e9"}'
        "_immortal|fp_3fcb29b96fc20f6903afe37db140ff92",
        encoding="utf-8",
    )

    node_script = f"""
const helper = require({str(ZHUQUE_HELPER_PATH)!r});
const args = helper.parseArgs(["--auth-from-chrome-local-storage"]);
const authPayload = helper.normalizeAuthPayload(args);
process.stdout.write(JSON.stringify(authPayload));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "LOCALAPPDATA": str(tmp_path)},
    )

    assert completed.returncode == 0, completed.stderr
    normalized = completed.stdout.replace(" ", "").replace("\n", "")
    assert '"accessToken":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJAYTEwZDVlN2E5MTE2NDQyYWJkOTI2MWE1MWY5MTNlOSIsImV4cCI6MTc4MDkxMjM5NTA5NX0.qcBVUrPcW6v0X2ZCAdx8qAREGN4w2XMMA7YWueLFu1A"' in normalized
    assert '"fp":"3fcb29b96fc20f6903afe37db140ff92"' in normalized


def test_compare_mode_apply_current_cleanups_exports_collapsed_draft(tmp_path: Path) -> None:
    source_file = tmp_path / "source.md"
    draft_file = tmp_path / "draft.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_file.write_text(
        (
            "# 标题\n\n"
            "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
            "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
            "人很多时候就是从这里开始慢下来的。没出什么大事，也谈不上垮。只是闹钟响了，按掉，再按掉；明明只差十分钟就能从容出门，还是在床边坐了很久。\n\n"
            "麻烦就麻烦在，这些信号太容易被她自己轻轻带过去。醒来更累，胃口乱，下午三四点会突然心慌；消息提示音一密集，太阳穴就跟着发紧。可熟悉的话也会立刻跟上来：忙完这阵就好了，周末补个觉就好了。\n\n"
            "身体先亮红灯，人却还照着原来的效率和礼貌往前走。该交的照交，该回的照回，见了人也还能笑，说自己没事。\n\n"
            "她还没倒下。还能上班，能交差，能在别人问起时回一句“挺好的”。偏偏就是这种“还能”，最容易让人误判。\n\n"
            "关系里的缺席，也是在这些时候一点点长出来的。见面改成改天，电话换成文字，长回复缩成表情，解释缩成“最近有点忙”。\n\n"
            "这句话很体谅，可听久了，人会更沉。因为她慢慢也默认了自己总在往后退。生活里有变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。\n\n"
            "难的地方就在这儿。不是因为太久没见，也不全是因为之前推掉太多次。更常见的情况是，人已经在长时间硬撑里，跟自己的感受脱了节。\n"
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--compare-source-file",
            str(source_file),
            "--compare-draft-file",
            str(draft_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "compare-cleanup-case",
            "--apply-current-cleanups",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    cleanup = result["compare_cleanup"]
    assert cleanup["enabled"] is True
    assert cleanup["applied"] is True
    assert cleanup["original_embedded_banner_count"] > cleanup["cleaned_embedded_banner_count"]
    assert cleanup["original_ai_flavor"]["score"] > cleanup["cleaned_ai_flavor"]["score"]
    assert cleanup["cleaned_ai_flavor"]["score"] == result["ai_flavor"]["draft"]["score"]

    cleaned_draft = Path(result["artifacts"]["draft_copy"]).read_text(encoding="utf-8")
    assert "人很多时候就是从这里开始慢下来的，没出什么大事" in cleaned_draft
    assert "人很多时候就是从这里开始慢下来的。没出什么大事" not in cleaned_draft
    assert Path(result["artifacts"]["draft_original_copy"]).exists()


def test_compare_mode_can_attach_ai_route_probe(tmp_path: Path, monkeypatch) -> None:
    script = _load_run_originality_case_module()
    source_file = tmp_path / "source.md"
    draft_file = tmp_path / "draft.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_file.write_text("# 标题\n\n这是改写稿。", encoding="utf-8")
    monkeypatch.setattr(
        script,
        "_probe_ai_text_routes",
        lambda: {
            "ai_config": {"model": "gpt-5.4-mini", "base_url": "https://proxy.example/v1"},
            "routes": {"responses_parse_topic": {"ok": False}},
        },
    )
    monkeypatch.setattr(
        script,
        "_probe_ai_image_routes",
        lambda: {
            "ai_config": {"image_model": "gpt-image-2", "image_base_url": "https://images.example/v1"},
            "routes": {"fallback": {"ok": True, "used_route_label": "fallback"}},
        },
    )

    args = script._build_parser().parse_args(
        [
            "--compare-source-file",
            str(source_file),
            "--compare-draft-file",
            str(draft_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "compare-route-probe-case",
            "--probe-ai-routes",
        ]
    )

    exit_code = script._run_compare_mode(args)

    assert exit_code == 0
    result_path = tmp_path / "runs" / "compare-route-probe-case" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["ai_text_routes_probe"]["ai_config"]["model"] == "gpt-5.4-mini"
    assert result["ai_text_routes_probe"]["routes"]["responses_parse_topic"]["ok"] is False
    assert result["ai_image_routes_probe"]["ai_config"]["image_model"] == "gpt-image-2"
    assert result["ai_image_routes_probe"]["routes"]["fallback"]["used_route_label"] == "fallback"


def test_compare_mode_apply_current_cleanups_collapses_over_segmented_shell(tmp_path: Path) -> None:
    source_file = tmp_path / "source.md"
    draft_file = tmp_path / "draft.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_file.write_text(
        (
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
            "这也是为什么，越着急恢复成原来那个样子，越容易看不见自己已经透支。她想赶快追平进度，赶快找回效率，赶快证明自己没事，于是那些变慢、变钝、不想说话的信号，就又被归到“短期失控”里。忍忍，顶顶，睡一觉再说。\n\n"
            "可身体有时不按这套来。你越催，它越迟。\n\n"
            "能让人往回退半步的，通常也不是什么大动作，可能只是第二天通勤路上，她没有一上车就点开工作群，而是把手机切到备忘录，记下最近最明显的三个变化：回消息变慢；越来越怕说话；做什么都像拖着一截湿衣服。写完那三行，事情不会立刻变少，人也不会立刻轻松，但模糊的自责会松开一条缝。\n\n"
            "原来不是自己突然变懒了，真正卡住的地方在，她已经耗到需要分辨：哪些是必须做的，哪些可以晚点回；哪些是责任，哪些只是习惯性逞强。\n\n"
            "后面的事，也许只是先减掉一项没那么要紧的安排，先让某条无关紧要的消息晚回半天，先别逼自己今天就恢复利落。不是每次都要搞出完整方案。有时候，能把“我得赶紧正常起来”改成“我今天少撑一会儿”，已经很难了，也很有用。\n\n"
            "夜里那面镜子还在，灯光照下来，脸色还是疲惫的。她没有突然想通，也没有瞬间好起来。牙刷还在手里，包终于从肩上滑下来，落到门边的凳子上，发出一声很轻的闷响。她坐了会儿，把第二天最早的提醒关掉了。\n\n"
            "屋里安静下来以后，很多事并不会马上变轻，工作还在，消息明天还会继续来，人际里的牵扯也不会自己消失。但至少那一晚，她不用再一边难受，一边把这件事说得很小。她先承认了：自己确实已经撑了太久。\n"
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--compare-source-file",
            str(source_file),
            "--compare-draft-file",
            str(draft_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "compare-over-segmented-shell-case",
            "--apply-current-cleanups",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    cleanup = result["compare_cleanup"]
    step_names = [step["name"] for step in cleanup["steps"] if step["changed"]]
    assert "collapse_over_segmented_shell_residue" in step_names
    assert cleanup["original_ai_flavor"]["score"] > cleanup["cleaned_ai_flavor"]["score"]

    cleaned_draft = Path(result["artifacts"]["draft_copy"]).read_text(encoding="utf-8")
    original_paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", draft_file.read_text(encoding="utf-8"))
        if block.strip() and not block.strip().startswith("#")
    ]
    cleaned_paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", cleaned_draft)
        if block.strip() and not block.strip().startswith("#")
    ]
    assert len(original_paragraphs) == 23
    assert len(cleaned_paragraphs) <= 15
    assert "\n\n她没动。\n\n" not in cleaned_draft


def test_compare_mode_apply_current_cleanups_reflows_leading_cadence_pair(tmp_path: Path) -> None:
    source_file = tmp_path / "source.md"
    draft_file = tmp_path / "draft.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_file.write_text(
        (
            "# 标题\n\n"
            "电梯门快要合上的时候，她伸手挡了一下。\n\n"
            "金属门沿碰到手背，凉了一瞬。人是进来了，心口却突然空了一拍，像踩空楼梯那种短促的失重。她站稳，先低头看手机，聊天框顶着一句：文件到了吗。拇指飞快敲了两个字：马上。\n\n"
            "电梯往上走，镜面里的人脸色有点白。她盯着数字跳，没把那口气补完整。刚才那下心慌，按理说该停一停，至少靠着轿厢站会儿，等胸口缓过来。可屏幕亮着，红点还在，她下意识先把身体往后排。\n\n"
            "这时候最容易发生的误认，是把报警当偷懒。\n\n"
            "明明已经开始耗了，她还会拿“别人也这么忙”压自己，拿“就这几天”拖自己，拿“先把这件做完”借自己。每回只借走一小截体力，借走一点耐心，借走一次好好吃饭和好好说话的机会。表面看都不算大事，拼在一起，人才会慢慢变成现在这样：反应迟，睡不好，不想回消息，不想解释，坐着都像在咬牙。\n"
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--compare-source-file",
            str(source_file),
            "--compare-draft-file",
            str(draft_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "compare-leading-cadence-case",
            "--apply-current-cleanups",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    cleanup = result["compare_cleanup"]
    step_names = [step["name"] for step in cleanup["steps"] if step["changed"]]
    assert "collapse_leading_short_long_cadence_residue" in step_names
    assert cleanup["original_ai_flavor"]["score"] > cleanup["cleaned_ai_flavor"]["score"]

    cleaned_draft = Path(result["artifacts"]["draft_copy"]).read_text(encoding="utf-8")
    assert "电梯门快要合上的时候，她伸手挡了一下。金属门沿碰到手背，凉了一瞬。" in cleaned_draft
    assert "\n\n人是进来了，心口却突然空了一拍" in cleaned_draft


def test_compare_mode_apply_current_cleanups_reflows_light_segmented_shell(tmp_path: Path) -> None:
    source_file = tmp_path / "source.md"
    draft_file = tmp_path / "draft.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_file.write_text(
        (
            "# 标题\n\n"
            "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
            "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
            "她点开语音，说了两个字，停住。删掉。又按住，说到“我最近……”就没声了。肩膀绷得很紧，像有人把两边往里拽。最后发出去的，还是那句最省力的话：这周有点满，下次一定。\n\n"
            "消息发完，手机被她扣在桌上。屋里很安静，只有冰箱压缩机时不时响一声。她坐着没动，连起身去洗那个杯子都像要先攒一会儿力气。很多人就是从这种地方开始变慢的。\n\n"
            "不是什么大事，也没有戏剧性的崩塌。闹钟响了，按掉，再按掉。明明只差十分钟就能从容出门，还是在床边坐了很久。洗头这件事，要在心里过两遍流程。工作群里的消息回得很快，私人聊天框一排红点，看见了，也知道该回，手指却悬在那儿，不太想点开。\n\n"
            "白天她照常开会、改东西、回邮件。谁来催，她都能接住，语气也稳。到了下班路上，地铁门一开，风吹进来，她忽然只想把耳机音量调大一点，谁都别找她。回家以后，包放在门口，外套搭上椅背，人靠着沙发坐下去，盯着墙，或者盯着短视频往下滑。不是在看什么，就是不想动。\n\n"
            "这里面有条很清楚的线。\n\n"
            "待办一项项堆上来，她最先做的，通常与其说是分辨自己累到哪了，不如说是把那点不舒服往里折，先做完再说。眼前这关要过，明天那项不能拖，周会材料还差最后两页。情绪先收起来，困和烦也先收起来。这样撑过去几次，表面看着没出事，代价却会留在别处：越晚处理自己，恢复的门槛越高，到后来，连见朋友、回电话、认真聊近况这种原本能让人松口气的事，也开始带着任务感。\n\n"
            "她不是突然不爱说话的。早上出门前，口红拿起来又放下，算了。午休时间，本来想去楼下走走，结果坐在工位上发呆。深夜洗漱，牙刷含在嘴里，眼睛看着镜子里的人，脑子却是空的。第二天继续。你会发现她还在运转，但速度不一样了，钝感也出来了，像手机进入了省电模式，屏幕亮着，后台却关掉了很多东西。\n\n"
            "更麻烦的是，她常把这些信号当成“最近状态不太好”。\n\n"
            "醒来更累，胃口乱，有时下午三四点突然心慌；消息提示音一密集，太阳穴就跟着发紧。按理说，这些已经够明显了。可她对自己的解释总是很熟：忙完这阵就好了，周末补个觉就好了，最近事情多，谁不是这样。\n\n"
            "她不是没感觉到，只是太习惯“撑一下”。\n\n"
            "身体先给信号，她的反应却往往还是维持原来的效率和礼貌。该交的照交，该回的照回，见了人也还能笑，说自己没事。这样做短期确实管用，能让日子继续往前推；可后续的空，会越来越实。最先被取消的，常常不是工作，不是合作，也与其说是那些明确有后果的安排，不如说是朋友约饭、回家人的电话、好好讲一遍自己这阵子到底怎么了。\n\n"
            "因为她还没有倒下。还能上班，能交差，能在别人问起时回一句“挺好的”。正是这种“还能”，最容易让人误判。像房间里有一盏灯开始忽明忽暗，但只要没彻底灭掉，大家就继续用。她自己也继续用，直到连换个灯泡都嫌麻烦。\n\n"
            "关系里的缺席，也不是某天忽然形成的。先是把见面改成改天，接着电话变成文字，最后长回复缩成表情，解释缩成“最近有点忙”。聊天框里的未读红点越来越多，她收藏过几条想认真回的话，后来也没再点开。朋友起初还会追问两句，发生了什么，忙成这样？再往后，大家学会了顺着她：行，等你忙完。\n\n"
            "这句话听上去很体谅，可听多了，人会更沉默。因为她慢慢适应了自己总在往后退。生活里有新变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。别人伸手的时候，她先想到的与其说是“我可以说”，不如说是“我得赶紧恢复正常，再去见人”。真正卡住的地方就在这儿：她越想尽快回到从前那个利落、能聊、能接住一切的自己，就越容易忽略现在这个已经很累的人。\n\n"
            "有些代价是延迟出现的。\n\n"
            "过了很久，终于约出来吃饭。餐厅里灯偏黄，汤上来时还冒着热气，对面的人问她，最近还好吗。她先笑了一下，下意识说“还行”。筷子碰到碗沿，轻轻响了一声。后半句卡住了。与其说是故意藏着不说，不如说是她真的一时不知道从哪里讲起。\n\n"
            "那种难，不只在于太久没见，不只在于之前推掉了太多次。更常见的情况是，人已经在长期硬撑里跟自己的感受脱了节。她知道自己累，知道自己变了，可要把这段日子重新接起来，像把散在地上的线头重新找出来，光找开头就要坐很久。\n\n"
            "所以后来很多女人补的，根本不只是几顿饭、几次见面、几条没回的消息。她在补的是一段长时间的缺席：没在最难的时候承认自己难，没在身体已经开始报警时停下来，也没在关系还松动得开的时刻，把真实情况递出去。\n\n"
            "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。\n\n"
            "她只给其中一个人发了句实话：我最近有点撑不动，可能会回得慢一点。\n\n"
            "发完以后，电梯门开了。她把手机放回口袋，先去把那只杯子洗了。\n"
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--compare-source-file",
            str(source_file),
            "--compare-draft-file",
            str(draft_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "compare-light-segmented-shell-case",
            "--apply-current-cleanups",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    cleanup = result["compare_cleanup"]
    step_names = [step["name"] for step in cleanup["steps"] if step["changed"]]
    assert "collapse_light_segmented_shell_residue" in step_names
    assert cleanup["original_structural_residue"]["residue_score"] > cleanup["cleaned_structural_residue"]["residue_score"]
    assert cleanup["original_structural_residue"]["paragraph_count"] > cleanup["cleaned_structural_residue"]["paragraph_count"]

    cleaned_draft = Path(result["artifacts"]["draft_copy"]).read_text(encoding="utf-8")
    original_paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", draft_file.read_text(encoding="utf-8"))
        if block.strip() and not block.strip().startswith("#")
    ]
    cleaned_paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", cleaned_draft)
        if block.strip() and not block.strip().startswith("#")
    ]
    assert len(cleaned_paragraphs) < len(original_paragraphs)


def test_apply_current_compare_cleanups_reports_structural_residue() -> None:
    script = _load_run_originality_case_module()

    draft_markdown = (
        "# 标题\n\n"
        "电梯门快要合上的时候，她伸手挡了一下。\n\n"
        "金属门沿碰到手背，凉了一瞬。人是进来了，心口却突然空了一拍，像踩空楼梯那种短促的失重。她站稳，先低头看手机，聊天框顶着一句：文件到了吗。拇指飞快敲了两个字：马上。\n\n"
        "这时候最容易发生的误认，是把报警当偷懒。\n\n"
        "明明已经开始耗了，她还会拿“别人也这么忙”压自己，拿“就这几天”拖自己，拿“先把这件做完”借自己。每回只借走一小截体力，借走一点耐心，借走一次好好吃饭和好好说话的机会。表面看都不算大事，拼在一起，人才会慢慢变成现在这样：反应迟，睡不好，不想回消息，不想解释，坐着都像在咬牙。\n"
    )

    _, cleanup = script._apply_current_compare_cleanups(
        title="标题",
        draft_markdown=draft_markdown,
    )

    original_residue = cleanup["original_structural_residue"]
    cleaned_residue = cleanup["cleaned_structural_residue"]
    assert original_residue["residue_score"] > cleaned_residue["residue_score"]
    assert original_residue["short_judgment_count"] >= cleaned_residue["short_judgment_count"]
    assert original_residue["short_long_cadence_pairs"] >= cleaned_residue["short_long_cadence_pairs"]


def test_apply_current_compare_cleanups_reflows_quote_examples_and_tail_fragments() -> None:
    script = _load_run_originality_case_module()

    draft_markdown = (
        "# 标题\n\n"
        "很多人的收口，几次认真开口，换来轻飘飘的回应。真要把它算成突然发生的。，反而把事情说浅了；"
        "是明明在说委屈，对方只盯着语气；是你把边界提出来，场面立刻变得尴尬，最后还是你先圆回来。\n\n"
        "比如：“刚才那样说，我不舒服。”。\n\n"
        "“这件事我做不到。”。\n\n"
        "“这个问题你得回应我。”。\n\n"
        "发出去，先停在这里。"
    )

    cleaned_markdown, cleanup = script._apply_current_compare_cleanups(
        title="标题",
        draft_markdown=draft_markdown,
    )

    changed_steps = [step["name"] for step in cleanup["steps"] if step["changed"]]
    assert "strip_orphaned_rebound_tail_residue" in changed_steps
    assert "collapse_isolated_quote_example_residue" in changed_steps
    assert "真要把它算成突然发生的" not in cleaned_markdown
    assert "反而把事情说浅了" not in cleaned_markdown
    assert "比如：“刚才那样说，我不舒服。”“这件事我做不到。”“这个问题你得回应我。”" in cleaned_markdown
    assert "\n\n“这件事我做不到。”" not in cleaned_markdown
    assert cleanup["original_ai_flavor"]["score"] > cleanup["cleaned_ai_flavor"]["score"]


def test_apply_current_compare_cleanups_reflows_common_broken_rebound_shape() -> None:
    script = _load_run_originality_case_module()

    draft_markdown = (
        "# 标题\n\n"
        "很多消耗，你明明已经不舒服，还在维持体面，维持理解，维持那句“再看看”。"
        "真要把它算成从一次争吵开始的。它更常见的样子。"
        "白天照常上班，照常说笑，事情也在做，节奏却乱了。"
    )

    cleaned_markdown, cleanup = script._apply_current_compare_cleanups(
        title="标题",
        draft_markdown=draft_markdown,
    )

    changed_steps = [step["name"] for step in cleanup["steps"] if step["changed"]]
    assert "strip_orphaned_rebound_tail_residue" in changed_steps
    assert "真要把它算成从一次争吵开始的" not in cleaned_markdown
    assert "它更常见的样子" not in cleaned_markdown
    assert "白天照常上班，照常说笑，事情也在做，节奏却乱了" in cleaned_markdown


def test_replay_result_mode_reuses_bundle_artifacts_and_exports_cleaned_compare_bundle(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "historical-bundle"
    bundle_dir.mkdir()
    source_file = bundle_dir / "source.md"
    draft_file = bundle_dir / "draft.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_file.write_text(
        (
            "# 标题\n\n"
            "电梯门快要合上的时候，她伸手挡了一下。\n\n"
            "金属门沿碰到手背，凉了一瞬。人是进来了，心口却突然空了一拍，像踩空楼梯那种短促的失重。她站稳，先低头看手机，聊天框顶着一句：文件到了吗。拇指飞快敲了两个字：马上。\n\n"
            "电梯往上走，镜面里的人脸色有点白。她盯着数字跳，没把那口气补完整。刚才那下心慌，按理说该停一停，至少靠着轿厢站会儿，等胸口缓过来。可屏幕亮着，红点还在，她下意识先把身体往后排。\n\n"
            "这时候最容易发生的误认，是把报警当偷懒。\n\n"
            "明明已经开始耗了，她还会拿“别人也这么忙”压自己，拿“就这几天”拖自己，拿“先把这件做完”借自己。每回只借走一小截体力，借走一点耐心，借走一次好好吃饭和好好说话的机会。表面看都不算大事，拼在一起，人才会慢慢变成现在这样：反应迟，睡不好，不想回消息，不想解释，坐着都像在咬牙。\n"
        ),
        encoding="utf-8",
    )
    result_json = bundle_dir / "result.json"
    result_json.write_text(
        json.dumps(
            {
                "source_title": "原文标题",
                "draft": {
                    "title": "重放标题",
                },
                "artifacts": {
                    "source_md": str(source_file),
                    "draft_md": str(draft_file),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--replay-result-json",
            str(result_json),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "replay-cleanup-case",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["mode"] == "replay_result_cleanup"
    assert result["replayed_from_result_json"] == str(result_json.resolve())
    assert result["compare_cleanup"]["enabled"] is True
    assert result["compare_cleanup"]["applied"] is True
    assert result["compare_cleanup"]["original_ai_flavor"]["score"] > result["compare_cleanup"]["cleaned_ai_flavor"]["score"]
    assert result["ai_flavor"]["draft"]["score"] == result["compare_cleanup"]["cleaned_ai_flavor"]["score"]

    cleaned_draft = Path(result["artifacts"]["draft_copy"]).read_text(encoding="utf-8")
    original_draft = Path(result["artifacts"]["draft_original_copy"]).read_text(encoding="utf-8")
    assert "电梯门快要合上的时候，她伸手挡了一下。金属门沿碰到手背，凉了一瞬。" in cleaned_draft
    assert original_draft == draft_file.read_text(encoding="utf-8")


def test_replay_result_root_mode_replays_only_trusted_cleanup_candidates(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    script = _load_run_originality_case_module()

    replay_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        script,
        "_audit_external_detector_result_root",
        lambda _root: {
            "summary": {
                "audited_reports": 3,
                "trusted_cleanup_replay_candidates": 1,
            },
            "results": [
                {
                    "label": "trusted-a",
                    "result_json": str(tmp_path / "trusted-a" / "result.json"),
                    "current_cleanup_replay_candidate": True,
                },
                {
                    "label": "trusted-b",
                    "result_json": str(tmp_path / "trusted-b" / "result.json"),
                    "current_cleanup_replay_candidate": False,
                },
                {
                    "label": "untrusted-a",
                    "result_json": str(tmp_path / "untrusted-a" / "result.json"),
                    "current_cleanup_replay_candidate": False,
                },
            ],
        },
    )

    def fake_build_replay_result_bundle(*, result_path: Path, output_root: Path, label: str | None, probe_ai_routes: bool):
        replay_calls.append((str(result_path), label))
        return {
            "artifacts": {
                "result_json": str(output_root / f"{label}" / "result.json"),
                "output_dir": str(output_root / f"{label}"),
            },
            "compare_cleanup": {
                "original_ai_flavor": {"score": 24},
                "cleaned_ai_flavor": {"score": 0},
                "original_structural_residue": {"residue_score": 10},
                "cleaned_structural_residue": {"residue_score": 3},
            },
        }

    monkeypatch.setattr(script, "_build_replay_result_bundle", fake_build_replay_result_bundle)

    args = script._build_parser().parse_args(
        [
            "--replay-result-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "runs"),
        ]
    )

    exit_code = script._run_replay_result_root_mode(args)

    assert exit_code == 0
    assert replay_calls == [
        (str((tmp_path / "trusted-a" / "result.json").resolve()), "trusted-a-current-cleanup"),
    ]

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "replay_result_root_cleanup"
    assert payload["summary"]["trusted_cleanup_replay_candidates"] == 1
    assert payload["summary"]["selected_candidates"] == 1
    assert payload["summary"]["replayed_candidates"] == 1
    assert payload["summary"]["error_candidates"] == 0
    assert payload["replayed"][0]["label"] == "trusted-a"
    assert payload["replayed"][0]["cleaned_ai_flavor_score"] == 0
    assert payload["replayed"][0]["ai_flavor_score_delta"] == 24
    assert payload["replayed"][0]["original_structural_residue_score"] == 10
    assert payload["replayed"][0]["cleaned_structural_residue_score"] == 3
    assert payload["replayed"][0]["structural_residue_delta"] == 7
    assert payload["replayed"][0]["structural_residue_improved"] is True


def test_replay_result_root_mode_prioritizes_lower_cleaned_score_then_structural_residue(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    script = _load_run_originality_case_module()

    replay_calls: list[str] = []

    monkeypatch.setattr(
        script,
        "_audit_external_detector_result_root",
        lambda _root: {
            "summary": {
                "audited_reports": 3,
                "trusted_cleanup_replay_candidates": 3,
            },
            "results": [
                {
                    "label": "candidate-a",
                    "result_json": str(tmp_path / "candidate-a" / "result.json"),
                    "current_cleanup_replay_candidate": True,
                    "current_cleanup_score_improved": True,
                    "current_cleanup_structural_improved": True,
                    "current_cleanup_original_score": 18,
                    "current_cleanup_cleaned_score": 0,
                    "current_cleanup_original_residue_score": 12,
                    "current_cleanup_cleaned_residue_score": 6,
                },
                {
                    "label": "candidate-b",
                    "result_json": str(tmp_path / "candidate-b" / "result.json"),
                    "current_cleanup_replay_candidate": True,
                    "current_cleanup_score_improved": True,
                    "current_cleanup_structural_improved": True,
                    "current_cleanup_original_score": 18,
                    "current_cleanup_cleaned_score": 0,
                    "current_cleanup_original_residue_score": 12,
                    "current_cleanup_cleaned_residue_score": 2,
                },
                {
                    "label": "candidate-c",
                    "result_json": str(tmp_path / "candidate-c" / "result.json"),
                    "current_cleanup_replay_candidate": True,
                    "current_cleanup_score_improved": False,
                    "current_cleanup_structural_improved": True,
                    "current_cleanup_original_score": 12,
                    "current_cleanup_cleaned_score": 12,
                    "current_cleanup_original_residue_score": 10,
                    "current_cleanup_cleaned_residue_score": 1,
                },
            ],
        },
    )

    def fake_build_replay_result_bundle(*, result_path: Path, output_root: Path, label: str | None, probe_ai_routes: bool):
        replay_calls.append(result_path.parent.name)
        name = result_path.parent.name
        score_map = {
            "candidate-a": (18, 0, 12, 6),
            "candidate-b": (18, 0, 12, 2),
            "candidate-c": (12, 12, 10, 1),
        }
        original_score, cleaned_score, original_residue, cleaned_residue = score_map[name]
        return {
            "artifacts": {
                "result_json": str(output_root / f"{label}" / "result.json"),
                "output_dir": str(output_root / f"{label}"),
            },
            "compare_cleanup": {
                "original_ai_flavor": {"score": original_score},
                "cleaned_ai_flavor": {"score": cleaned_score},
                "original_structural_residue": {"residue_score": original_residue},
                "cleaned_structural_residue": {"residue_score": cleaned_residue},
            },
        }

    monkeypatch.setattr(script, "_build_replay_result_bundle", fake_build_replay_result_bundle)

    args = script._build_parser().parse_args(
        [
            "--replay-result-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "runs"),
        ]
    )

    exit_code = script._run_replay_result_root_mode(args)

    assert exit_code == 0
    assert replay_calls == ["candidate-b", "candidate-a", "candidate-c"]

    payload = json.loads(capsys.readouterr().out)
    assert [item["label"] for item in payload["replayed"]] == ["candidate-b", "candidate-a", "candidate-c"]


def test_replay_result_root_mode_writes_cleanup_retest_manifest(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    script = _load_run_originality_case_module()

    monkeypatch.setattr(
        script,
        "_audit_external_detector_result_root",
        lambda _root: {
            "summary": {
                "audited_reports": 2,
                "trusted_cleanup_replay_candidates": 2,
            },
            "results": [
                {
                    "label": "candidate-a",
                    "result_json": str(tmp_path / "candidate-a" / "result.json"),
                    "current_cleanup_replay_candidate": True,
                    "current_cleanup_cleaned_score": 0,
                    "current_cleanup_cleaned_residue_score": 6,
                    "current_cleanup_score_delta": 24,
                    "current_cleanup_structural_residue_delta": 12,
                },
                {
                    "label": "candidate-b",
                    "result_json": str(tmp_path / "candidate-b" / "result.json"),
                    "current_cleanup_replay_candidate": True,
                    "current_cleanup_cleaned_score": 0,
                    "current_cleanup_cleaned_residue_score": 2,
                    "current_cleanup_score_delta": 18,
                    "current_cleanup_structural_residue_delta": 8,
                },
            ],
        },
    )

    def fake_build_replay_result_bundle(*, result_path: Path, output_root: Path, label: str | None, probe_ai_routes: bool):
        assert label is not None
        bundle_dir = output_root / label
        return {
            "artifacts": {
                "result_json": str(bundle_dir / "result.json"),
                "output_dir": str(bundle_dir),
                "source_copy": str(bundle_dir / "source.md"),
                "draft_copy": str(bundle_dir / "draft.md"),
                "draft_original_copy": str(bundle_dir / "draft.original.md"),
                "source_detector_text": str(bundle_dir / "source.txt"),
                "draft_detector_text": str(bundle_dir / "draft.txt"),
                "external_detector_templates": {
                    "instructions_md": str(bundle_dir / "detector-instructions.md"),
                    "source_template_json": str(bundle_dir / "source-template.json"),
                    "draft_template_json": str(bundle_dir / "draft-template.json"),
                },
            },
            "compare_cleanup": {
                "original_ai_flavor": {"score": 24},
                "cleaned_ai_flavor": {"score": 0},
                "original_structural_residue": {"residue_score": 10},
                "cleaned_structural_residue": {"residue_score": 3},
            },
        }

    monkeypatch.setattr(script, "_build_replay_result_bundle", fake_build_replay_result_bundle)

    args = script._build_parser().parse_args(
        [
            "--replay-result-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "runs"),
        ]
    )

    exit_code = script._run_replay_result_root_mode(args)

    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    manifest_json = Path(payload["artifacts"]["cleanup_retest_manifest_json"])
    manifest_md = Path(payload["artifacts"]["cleanup_retest_manifest_md"])
    assert manifest_json.exists()
    assert manifest_md.exists()

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["summary"]["selected_candidate_labels"] == ["candidate-b", "candidate-a"]
    assert manifest["summary"]["selected_candidates"] == 2
    assert manifest["candidates"][0]["label"] == "candidate-b"
    assert manifest["candidates"][0]["priority_rank"] == 1
    assert manifest["candidates"][0]["draft_detector_text"].endswith("candidate-b-current-cleanup\\draft.txt")
    assert manifest["candidates"][0]["instructions_md"].endswith("candidate-b-current-cleanup\\detector-instructions.md")

    markdown = manifest_md.read_text(encoding="utf-8")
    assert "candidate-b" in markdown
    assert "draft.txt" in markdown
    assert "detector-instructions.md" in markdown


def test_annotate_cleanup_replay_priorities_sets_rank_and_reason() -> None:
    script = _load_run_originality_case_module()

    results = [
        {
            "label": "candidate-a",
            "current_cleanup_replay_candidate": True,
            "current_cleanup_cleaned_score": 0,
            "current_cleanup_cleaned_residue_score": 6,
            "current_cleanup_score_delta": 24,
            "current_cleanup_structural_residue_delta": 12,
        },
        {
            "label": "candidate-b",
            "current_cleanup_replay_candidate": True,
            "current_cleanup_cleaned_score": 0,
            "current_cleanup_cleaned_residue_score": 2,
            "current_cleanup_score_delta": 18,
            "current_cleanup_structural_residue_delta": 8,
        },
        {
            "label": "candidate-c",
            "current_cleanup_replay_candidate": False,
            "current_cleanup_cleaned_score": 0,
            "current_cleanup_cleaned_residue_score": 1,
            "current_cleanup_score_delta": 30,
            "current_cleanup_structural_residue_delta": 16,
        },
    ]

    prioritized = script._annotate_cleanup_replay_priorities(results)

    assert [item["label"] for item in prioritized] == ["candidate-b", "candidate-a"]
    assert prioritized[0]["current_cleanup_priority_rank"] == 1
    assert prioritized[1]["current_cleanup_priority_rank"] == 2
    assert prioritized[0]["current_cleanup_priority_reason"] == {
        "cleaned_ai_flavor_score": 0,
        "cleaned_structural_residue_score": 2,
        "ai_flavor_score_delta": 18,
        "structural_residue_delta": 8,
    }


def test_export_prompts_only_mode_writes_prompt_bundles(tmp_path: Path) -> None:
    source_file = tmp_path / "source.md"
    source_file.write_text(
        (
            "# 别把日子过反了\n\n"
            "别用健康换明天。\n\n"
            "朋友阿杰总说等忙完再休息，后来身体先发出了提醒。\n\n"
            "别把幸福寄托在等以后。\n\n"
            "很多重要的事，往往就是这样被顺手往后放。"
        ),
        encoding="utf-8",
    )
    reuse_bundle = tmp_path / "reuse-result.json"
    reuse_bundle.write_text(
        json.dumps(
            {
                "topic": {
                    "title": "别把日子过反了",
                    "angle": "从身体、关系和生活排序被不断往后放的处境切入，直接写清推迟的代价。",
                },
                "tracked_article": {
                    "summary": "围绕长期推迟导致生活排序失衡的参考文章。",
                    "structure_notes": "以短小节推进身体、关系和幸福排序。",
                    "tags": ["生活排序", "推迟"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input-file",
            str(source_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "export-prompts-case",
            "--skip-enrich",
            "--reuse-bundle-json",
            str(reuse_bundle),
            "--reuse-topic-from-bundle",
            "--export-prompts-only",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["mode"] == "export_prompts"
    assert result["status"] == "done"

    outline_prompt_json = Path(result["artifacts"]["outline_prompt_json"])
    draft_prompt_json = Path(result["artifacts"]["draft_prompt_json"])
    assert outline_prompt_json.exists()
    assert draft_prompt_json.exists()

    outline_payload = json.loads(outline_prompt_json.read_text(encoding="utf-8"))
    draft_payload = json.loads(draft_prompt_json.read_text(encoding="utf-8"))

    assert "创作策略包（执行摘要）" in outline_payload["prompt"]
    assert "创作策略包（执行摘要）" in draft_payload["prompt"]
    assert "主题锚点卡：" in draft_payload["prompt"]
    assert "执行顺序：" in draft_payload["prompt"]
    assert "当前任务是参考文章策略稿的首稿阶段" in draft_payload["instructions"]


def test_extract_reuse_topic_seed_falls_back_to_compare_bundle_titles() -> None:
    script = _load_run_originality_case_module()

    seed = script._extract_reuse_topic_seed(
        {
            "source_title": "别把日子过反了",
            "draft_title": "包带还挂在肩上，勒得锁骨发酸",
        }
    )

    assert seed is not None
    assert seed["title"] == "包带还挂在肩上，勒得锁骨发酸"
    assert "别把日子过反了" in seed["angle"]


def test_extract_reuse_topic_seed_uses_strategy_card_when_topic_angle_missing() -> None:
    script = _load_run_originality_case_module()

    seed = script._extract_reuse_topic_seed(
        {
            "source_title": "别把日子过反了",
            "draft_title": "包带还挂在肩上，勒得锁骨发酸",
            "adopted_strategy": {
                "strategy_card": {
                    "reader_situation": "她明明已经看到身体在透支，却还是顺手把休息往后挪。",
                    "conflict_frame": "真正堆起来的，不是一次忙，而是每次都把更重要的事排到后面。",
                    "benchmark_summary": "不要沿用原文那种总括式分节和案例轮转的推进壳子。",
                }
            },
        }
    )

    assert seed is not None
    assert seed["title"] == "包带还挂在肩上，勒得锁骨发酸"
    assert "她明明已经看到身体在透支" in seed["angle"]
    assert "真正堆起来的，不是一次忙" in seed["angle"]


def test_extract_reuse_topic_seed_uses_first_sentence_from_long_compare_draft_title() -> None:
    script = _load_run_originality_case_module()

    seed = script._extract_reuse_topic_seed(
        {
            "source_title": "别把日子过反了",
            "draft_title": "包带还挂在肩上，勒得锁骨发酸。她站在洗手台前，把牙膏挤到牙刷上，白色膏体歪歪地停在刷毛边缘。",
        }
    )

    assert seed is not None
    assert seed["title"] == "包带还挂在肩上，勒得锁骨发酸"
    assert "包带还挂在肩上，勒得锁骨发酸" in seed["angle"]


def test_export_prompts_only_mode_uses_compare_bundle_fallback_seed(tmp_path: Path) -> None:
    source_file = tmp_path / "source.md"
    source_file.write_text(
        (
            "# 别把日子过反了\n\n"
            "深夜里，她把要说的话又删掉了一次。\n\n"
            "很多重要的事，就是这样被顺手往后放。"
        ),
        encoding="utf-8",
    )
    reuse_bundle = tmp_path / "compare-result.json"
    reuse_bundle.write_text(
        json.dumps(
            {
                "mode": "compare",
                "source_title": "别把日子过反了",
                "draft_title": "包带还挂在肩上，勒得锁骨发酸",
                "tracked_article": {
                    "summary": "一篇围绕长期推迟与生活失序的参考文章。",
                    "structure_notes": "原文带有命令式分节和案例轮转壳子。",
                    "tags": ["生活排序", "推迟"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input-file",
            str(source_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "export-prompts-compare-fallback",
            "--skip-enrich",
            "--reuse-bundle-json",
            str(reuse_bundle),
            "--reuse-topic-from-bundle",
            "--export-prompts-only",
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["mode"] == "export_prompts"
    assert result["status"] == "done"
    assert result["topic_seed"]["title"] == "包带还挂在肩上，勒得锁骨发酸"
    assert "别把日子过反了" in result["topic_seed"]["angle"]


def test_export_prompts_only_mode_skips_metadata_enrichment_when_reuse_bundle_has_complete_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script = _load_run_originality_case_module()
    source_file = tmp_path / "source.md"
    source_file.write_text("# 别把日子过反了\n\n很多重要的事，就是这样被顺手往后放。", encoding="utf-8")
    source_identity = script._build_source_identity(
        source_title="别把日子过反了",
        source_markdown=source_file.read_text(encoding="utf-8"),
    )
    reuse_bundle = tmp_path / "reuse-result.json"
    reuse_bundle.write_text(
        json.dumps(
            {
                "source_identity": source_identity,
                "analysis_source_identity": source_identity,
                "topic": {
                    "title": "别把日子过反了",
                    "angle": "从身体、关系和生活排序被不断往后放的处境切入，直接写清推迟的代价。",
                },
                "tracked_article": {
                    "summary": "围绕长期推迟导致生活排序失衡的参考文章。",
                    "structure_notes": "以短小节推进身体、关系和幸福排序。",
                    "tags": ["生活排序", "推迟"],
                    **{field: field for field in script._TRACKED_ARTICLE_ANALYSIS_FIELDS},
                    "analysis_content_pillars": ["第一层内容", "第二层内容"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[str] = []
    from app.services import workbench as workbench_module

    monkeypatch.setattr(
        workbench_module,
        "enrich_tracked_article_metadata",
        lambda _slug: calls.append("enrich") or (_ for _ in ()).throw(AssertionError("should not enrich")),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--input-file",
            str(source_file),
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "export-prompts-skip-enrich-with-reuse-bundle",
            "--reuse-bundle-json",
            str(reuse_bundle),
            "--reuse-topic-from-bundle",
            "--export-prompts-only",
        ],
    )

    assert script.main() == 0
    result_path = next((tmp_path / "runs").rglob("result.json"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "done"
    assert calls == []


def test_best_effort_enrich_tracked_article_records_warning_and_keeps_seed_payload() -> None:
    script = _load_run_originality_case_module()

    class FakeArticle:
        def model_dump(self) -> dict[str, object]:
            return {
                "slug": "article-demo",
                "source_kind": "manual",
                "source_name": "manual-originality-check",
                "title": "幸福是什么",
                "url": "local://article-demo",
                "author": "",
                "summary": "",
                "body_markdown": "正文",
                "body_source": "manual_input",
                "structure_notes": "",
                "created_at": None,
                "tags": [],
            }

    partial: dict[str, object] = {}

    def fail_enrich(_slug: str):
        raise RuntimeError("502 upstream access forbidden")

    attempted = script._best_effort_enrich_tracked_article(
        article_slug="article-demo",
        article_payload=FakeArticle(),
        enrich_tracked_article_metadata=fail_enrich,
        should_skip=False,
        partial=partial,
    )

    assert attempted is True
    assert partial["tracked_article"]["slug"] == "article-demo"
    assert partial["tracked_article"]["title"] == "幸福是什么"
    assert partial["warnings"] == [
        {
            "type": "tracked_article_metadata_enrichment_failed",
            "article_slug": "article-demo",
            "message": "502 upstream access forbidden",
            "error_type": "RuntimeError",
        }
    ]


def test_best_effort_enrich_tracked_article_uses_enriched_payload_without_warning() -> None:
    script = _load_run_originality_case_module()

    class FakeArticle:
        def model_dump(self) -> dict[str, object]:
            return {
                "slug": "article-demo",
                "source_kind": "manual",
                "source_name": "manual-originality-check",
                "title": "幸福是什么",
                "url": "local://article-demo",
                "author": "",
                "summary": "",
                "body_markdown": "正文",
                "body_source": "manual_input",
                "structure_notes": "",
                "created_at": None,
                "tags": [],
            }

    class FakeEnriched:
        def model_dump(self) -> dict[str, object]:
            return {
                "slug": "article-demo",
                "source_kind": "manual",
                "source_name": "manual-originality-check",
                "title": "幸福是什么",
                "url": "local://article-demo",
                "author": "晚舟",
                "summary": "补齐摘要",
                "body_markdown": "正文",
                "body_source": "manual_input",
                "structure_notes": "先拆误解，再写放下。",
                "created_at": None,
                "tags": ["幸福", "放下"],
            }

    partial: dict[str, object] = {}

    attempted = script._best_effort_enrich_tracked_article(
        article_slug="article-demo",
        article_payload=FakeArticle(),
        enrich_tracked_article_metadata=lambda _slug: FakeEnriched(),
        should_skip=False,
        partial=partial,
    )

    assert attempted is True
    assert partial["tracked_article"]["author"] == "晚舟"
    assert partial["tracked_article"]["summary"] == "补齐摘要"
    assert "warnings" not in partial


def test_build_runtime_db_path_uses_system_temp_dir(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()

    output_dir = tmp_path / "verify-happiness-live-v10"
    output_dir.mkdir()

    runtime_db_path = script._build_runtime_db_path(output_dir)

    assert runtime_db_path.name == "verify-happiness-live-v10.db"
    assert runtime_db_path.parent == Path(tempfile.gettempdir()) / "gankaigc-originality-case-db"


def test_sync_runtime_db_to_bundle_copies_sqlite_file(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()

    runtime_db_path = tmp_path / "runtime.db"
    bundle_db_path = tmp_path / "bundle" / "workbench.db"
    runtime_db_path.write_bytes(b"sqlite-bytes")

    script._sync_runtime_db_to_bundle(runtime_db_path=runtime_db_path, bundle_db_path=bundle_db_path)

    assert bundle_db_path.exists()
    assert bundle_db_path.read_bytes() == b"sqlite-bytes"


def test_candidate_rank_tuple_prefers_lower_original_ai_flavor_when_cleaned_scores_tie() -> None:
    script = _load_run_originality_case_module()

    worse_candidate = {
        "label": "retry44",
        "ai_flavor": {"draft": {"score": 0}},
        "overlap_report": {
            "char_12gram_jaccard": 0.0,
            "char_8gram_jaccard": 0.0,
            "exact_long_sentence_overlap_count": 0,
            "title_same": False,
        },
        "compare_cleanup": {
            "applied": True,
            "steps": [{"name": "collapse_time_chain_shell_residue", "changed": True}],
            "original_ai_flavor": {"score": 32},
        },
    }
    better_candidate = {
        "label": "retry43",
        "ai_flavor": {"draft": {"score": 0}},
        "overlap_report": {
            "char_12gram_jaccard": 0.0,
            "char_8gram_jaccard": 0.0,
            "exact_long_sentence_overlap_count": 0,
            "title_same": False,
        },
        "compare_cleanup": {
            "applied": True,
            "steps": [{"name": "collapse_short_judgment_residue", "changed": True}],
            "original_ai_flavor": {"score": 12},
        },
    }

    ranked = sorted([worse_candidate, better_candidate], key=script._candidate_rank_tuple)

    assert [candidate["label"] for candidate in ranked] == ["retry43", "retry44"]


def test_candidate_rank_tuple_prefers_lower_cleaned_structural_burden_when_scores_tie() -> None:
    script = _load_run_originality_case_module()

    shell_heavier_candidate = {
        "label": "retry46",
        "ai_flavor": {"draft": {"score": 0}},
        "overlap_report": {
            "char_12gram_jaccard": 0.0,
            "char_8gram_jaccard": 0.0,
            "exact_long_sentence_overlap_count": 0,
            "title_same": False,
        },
        "compare_cleanup": {
            "applied": True,
            "steps": [{"name": "collapse_short_judgment_residue", "changed": True}],
            "original_ai_flavor": {"score": 12},
            "cleaned_structural_residue": {"paragraph_shell_burden": 9},
        },
    }
    shell_lighter_candidate = {
        "label": "retry45",
        "ai_flavor": {"draft": {"score": 0}},
        "overlap_report": {
            "char_12gram_jaccard": 0.0,
            "char_8gram_jaccard": 0.0,
            "exact_long_sentence_overlap_count": 0,
            "title_same": False,
        },
        "compare_cleanup": {
            "applied": True,
            "steps": [{"name": "collapse_short_judgment_residue", "changed": True}],
            "original_ai_flavor": {"score": 12},
            "cleaned_structural_residue": {"paragraph_shell_burden": 2},
        },
    }

    ranked = sorted([shell_heavier_candidate, shell_lighter_candidate], key=script._candidate_rank_tuple)

    assert [candidate["label"] for candidate in ranked] == ["retry45", "retry46"]


def test_candidate_rank_tuple_uses_label_as_final_stable_tiebreak() -> None:
    script = _load_run_originality_case_module()

    z_candidate = {
        "label": "z-finally",
        "ai_flavor": {"draft": {"score": 0}},
        "overlap_report": {
            "char_12gram_jaccard": 0.0,
            "char_8gram_jaccard": 0.0,
            "exact_long_sentence_overlap_count": 0,
            "title_same": False,
        },
    }
    a_candidate = {
        "label": "a-first",
        "ai_flavor": {"draft": {"score": 0}},
        "overlap_report": {
            "char_12gram_jaccard": 0.0,
            "char_8gram_jaccard": 0.0,
            "exact_long_sentence_overlap_count": 0,
            "title_same": False,
        },
    }

    ranked = sorted([z_candidate, a_candidate], key=script._candidate_rank_tuple)

    assert [candidate["label"] for candidate in ranked] == ["a-first", "z-finally"]


def test_rank_candidates_mode_records_ranking_policy_and_best_candidate(tmp_path: Path, monkeypatch) -> None:
    script = _load_run_originality_case_module()
    source_file = tmp_path / "source.md"
    draft_worse = tmp_path / "worse.md"
    draft_better = tmp_path / "better.md"
    source_file.write_text("# 原文\n\n这是原文。", encoding="utf-8")
    draft_worse.write_text("# 候选一\n\n这是候选一。", encoding="utf-8")
    draft_better.write_text("# 候选二\n\n这是候选二。", encoding="utf-8")

    def fake_evaluate_compare_pair(**kwargs):
        draft_markdown = kwargs["draft_markdown"]
        if "候选一" in draft_markdown:
            original_score = 24
            label = "候选一"
        else:
            original_score = 8
            label = "候选二"
        return {
            "draft_title": label,
            "draft_markdown": draft_markdown,
            "compare_cleanup": {
                "enabled": True,
                "applied": True,
                "steps": [{"name": "collapse_short_judgment_residue", "changed": True}],
                "original_ai_flavor": {"score": original_score},
                "cleaned_ai_flavor": {"score": 0},
                "original_embedded_banner_count": 0,
                "cleaned_embedded_banner_count": 0,
            },
            "overlap_report": {
                "title_same": False,
                "heading_overlap": [],
                "exact_long_sentence_overlap_count": 0,
                "exact_long_sentence_overlap_samples": [],
                "char_8gram_jaccard": 0.0,
                "char_12gram_jaccard": 0.0,
            },
            "ai_flavor": {
                "source": {"score": 80, "level": "高", "hits": [], "suggestions": []},
                "draft": {"score": 0, "level": "低", "hits": [], "suggestions": []},
            },
        }

    monkeypatch.setattr(script, "_evaluate_compare_pair", fake_evaluate_compare_pair)

    args = script._build_parser().parse_args(
        [
            "--rank-source-file",
            str(source_file),
            "--rank-source-title",
            "原文标题",
            "--rank-candidate",
            f"worse::{draft_worse}",
            "--rank-candidate",
            f"better::{draft_better}",
            "--output-root",
            str(tmp_path / "runs"),
            "--label",
            "rank-candidate-case",
        ]
    )

    exit_code = script._run_rank_candidates_mode(args)

    assert exit_code == 0
    result_path = tmp_path / "runs" / "rank-candidate-case" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["mode"] == "rank_candidates"
    assert result["ranking_policy"]["priority"][:5] == [
        "cleaned_ai_flavor_score",
        "original_ai_flavor_score",
        "cleaned_structural_residue_score",
        "cleanup_applied_flag",
        "cleanup_changed_steps",
    ]
    assert [candidate["label"] for candidate in result["candidates"]] == ["better", "worse"]
    assert result["best_candidate"]["label"] == "better"
    assert result["best_candidate"]["rank_key"][:2] == [0.0, 8.0]


def test_safe_print_json_swallows_stdout_oserror(capsys) -> None:
    script = _load_run_originality_case_module()

    class BrokenStdout:
        def write(self, _text: str) -> int:
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            return None

    original_stdout = sys.stdout
    try:
        sys.stdout = BrokenStdout()
        script._safe_print_json({"status": "done"})
    finally:
        sys.stdout = original_stdout

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_persist_result_snapshot_updates_stage_and_syncs_bundle(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    result_path = tmp_path / "result.json"
    payload = {"status": "running"}
    sync_calls: list[tuple[Path, Path]] = []

    def fake_sync_runtime_db_to_bundle(*, runtime_db_path: Path, bundle_db_path: Path) -> None:
        sync_calls.append((runtime_db_path, bundle_db_path))

    script._sync_runtime_db_to_bundle = fake_sync_runtime_db_to_bundle
    runtime_db_path = tmp_path / "runtime.db"
    bundle_db_path = tmp_path / "bundle.db"

    script._persist_result_snapshot(
        result_path,
        payload,
        stage="draft_ready",
        runtime_db_path=runtime_db_path,
        bundle_db_path=bundle_db_path,
    )

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["status"] == "running"
    assert saved["last_completed_stage"] == "draft_ready"
    assert sync_calls == [(runtime_db_path, bundle_db_path)]


def test_persist_result_snapshot_writes_without_sync_when_db_paths_missing(tmp_path: Path) -> None:
    script = _load_run_originality_case_module()
    result_path = tmp_path / "result.json"
    payload = {"status": "running"}
    sync_calls: list[str] = []

    def fake_sync_runtime_db_to_bundle(*, runtime_db_path: Path, bundle_db_path: Path) -> None:
        sync_calls.append(f"{runtime_db_path}->{bundle_db_path}")

    script._sync_runtime_db_to_bundle = fake_sync_runtime_db_to_bundle

    script._persist_result_snapshot(result_path, payload, stage="assets_ready")

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["last_completed_stage"] == "assets_ready"
    assert sync_calls == []


def test_pipeline_project_snapshot_uses_final_project_detail() -> None:
    script = _load_run_originality_case_module()

    class FakeProject:
        def model_dump(self) -> dict[str, object]:
            return {
                "stage": "publish_ready",
                "chain_status": "ready",
                "current_chain_state": "publish_ready",
                "next_required_step": None,
            }

    class FakeDetail:
        project = FakeProject()

        def model_dump(self) -> dict[str, object]:
            return {"project": self.project.model_dump(), "assets": {"cover_image_status": "ready"}}

    partial: dict[str, object] = {
        "project": {
            "stage": "outline",
            "chain_status": "missing",
            "current_chain_state": "missing_strategy",
            "next_required_step": "generate_strategy_package",
        }
    }
    detail = FakeDetail()

    script._update_project_result_snapshot(partial, detail)

    assert partial["project"] == {
        "stage": "publish_ready",
        "chain_status": "ready",
        "current_chain_state": "publish_ready",
        "next_required_step": None,
    }
    assert partial["project_detail"]["assets"]["cover_image_status"] == "ready"

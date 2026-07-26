import assert from "node:assert/strict";

import {
  buildBackgroundTaskErrorLines,
  buildBackgroundTaskIssueLines,
  buildBackgroundTaskSummaryLines,
  buildBatchCreateProjectResultMap,
  buildBatchCreateProjectResultLines,
  buildRecentBatchCreateProjectResultMap,
  mergeBatchCreateProjectResultMaps,
  patchBatchCreateProjectResultAsDone,
  pruneBatchCreateProjectResultMap,
} from "./backgroundTaskSummaries.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildBackgroundTaskSummaryLines returns request and result counts for batch task details", () => {
  const lines = buildBackgroundTaskSummaryLines({
    task_id: "task-1",
    job_type: "batch_generate_topics",
    status: "done",
    created_at: "2026-05-19T10:00:00Z",
    started_at: "2026-05-19T10:00:01Z",
    finished_at: "2026-05-19T10:00:10Z",
    error: null,
    result: {
      requested_count: 5,
      processed_count: 3,
      skipped_count: 1,
      failed_count: 1,
    },
  });

  assert.deepEqual(lines, ["请求 5 项", "完成 3 项", "跳过 1 项", "失败 1 项"]);
});

test("buildBackgroundTaskSummaryLines ignores incomplete or missing background task results", () => {
  assert.deepEqual(
    buildBackgroundTaskSummaryLines({
      task_id: "task-2",
      job_type: "batch_generate_topics",
      status: "failed",
      created_at: "2026-05-19T10:00:00Z",
      started_at: "2026-05-19T10:00:01Z",
      finished_at: "2026-05-19T10:00:10Z",
      error: "boom",
      result: {
        requested_count: 2,
      },
    }),
    [],
  );
  assert.deepEqual(buildBackgroundTaskSummaryLines(null), []);
});

test("buildBackgroundTaskIssueLines returns task item failures and skips with readable labels", () => {
  const lines = buildBackgroundTaskIssueLines({
    task_id: "task-3",
    job_type: "batch_generate_topics_from_tracked_articles",
    status: "failed",
    created_at: "2026-05-21T08:49:58Z",
    started_at: "2026-05-21T08:49:58Z",
    finished_at: "2026-05-21T08:50:10Z",
    error: "upstream failed",
    result: {
      requested_count: 3,
      processed_count: 2,
      skipped_count: 1,
      failed_count: 1,
      results: [
        {
          article_slug: "article-a",
          status: "failed",
          error: "502 upstream unavailable",
          topic: null,
        },
        {
          article_slug: "article-b",
          status: "skipped",
          reason: "已存在选题",
          topic: null,
        },
        {
          article_slug: "article-c",
          status: "done",
          error: null,
          topic: {
            slug: "topic-c",
            trend_slug: null,
            source_type: "tracked_article",
            source_ref_slug: "article-c",
            title: "topic c",
            angle: "angle",
            status: "new",
          },
        },
      ],
    },
  });

  assert.deepEqual(lines, ["失败: article-a - 502 upstream unavailable", "跳过: article-b - 已存在选题"]);
});

test("buildBackgroundTaskIssueLines ignores missing result arrays", () => {
  assert.deepEqual(
    buildBackgroundTaskIssueLines({
      task_id: "task-4",
      job_type: "batch_generate_topics",
      status: "failed",
      created_at: "2026-05-21T08:49:58Z",
      started_at: "2026-05-21T08:49:58Z",
      finished_at: "2026-05-21T08:50:10Z",
      error: "boom",
      result: {
        requested_count: 2,
        processed_count: 0,
        skipped_count: 0,
        failed_count: 2,
      },
    }),
    [],
  );
});

test("buildBackgroundTaskErrorLines translates upstream 502 errors into readable guidance", () => {
  const lines = buildBackgroundTaskErrorLines({
    task_id: "task-error-1",
    job_type: "batch_generate_topics_from_tracked_articles",
    status: "failed",
    created_at: "2026-05-21T08:49:58Z",
    started_at: "2026-05-21T08:49:58Z",
    finished_at: "2026-05-21T08:50:10Z",
    error: "Error code: 502 - {'error': {'message': 'Upstream service temporarily unavailable', 'type': 'upstream_error'}}",
    result: null,
  });

  assert.deepEqual(lines, [
    "上游 AI 服务暂时不可用（502）",
    "来源返回：Upstream service temporarily unavailable",
    "错误类型：upstream_error",
    "建议：稍后重试；如果持续失败，去 Settings 检查当前 AI 服务与模型配置。",
  ]);
});

test("buildBackgroundTaskErrorLines translates auth failures into actionable guidance", () => {
  const lines = buildBackgroundTaskErrorLines({
    task_id: "task-error-2",
    job_type: "batch_generate_topics",
    status: "failed",
    created_at: "2026-05-21T08:49:58Z",
    started_at: "2026-05-21T08:49:58Z",
    finished_at: "2026-05-21T08:50:10Z",
    error: "Error code: 401 - {'error': {'message': 'Incorrect API key provided', 'type': 'auth_error'}}",
    result: null,
  });

  assert.deepEqual(lines, [
    "AI 配置认证失败（401）",
    "来源返回：Incorrect API key provided",
    "错误类型：auth_error",
    "建议：去 Settings 检查 API Key、Base URL 和模型权限。",
  ]);
});

test("buildBackgroundTaskErrorLines appends cover route diagnostics for failed cover tasks", () => {
  const lines = buildBackgroundTaskErrorLines({
    task_id: "task-error-3",
    job_type: "regenerate_cover_image",
    status: "failed",
    created_at: "2026-07-17T08:49:58Z",
    started_at: "2026-07-17T08:49:58Z",
    finished_at: "2026-07-17T08:50:10Z",
    error: "封面生成失败：当前图片 API 暂无可用账号，请稍后重试。",
    error_context: {
      type: "HTTPException",
      status_code: 502,
      detail: "封面生成失败：当前图片 API 暂无可用账号，请稍后重试。",
      cover_image_route_label: "primary",
      cover_image_route_model: "gpt-image-2",
      cover_image_route_base_url: "https://i.ixiu.one/v1",
      fallback_account_pool_diagnosis_status: "not_configured",
      fallback_account_pool_diagnosis_label: "未形成第二套上游",
      fallback_account_pool_diagnosis_note: "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。",
    },
    result: null,
  });

  assert.deepEqual(lines, [
    "封面生成失败：当前图片 API 暂无可用账号，请稍后重试。",
    "封面链路：主路由 · gpt-image-2",
    "图片接口：https://i.ixiu.one/v1",
    "备用链路诊断：未形成第二套上游",
    "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。",
    "当前封面只走 API 图片链路，不会回退到本地生成。",
  ]);
});

test("buildBatchCreateProjectResultLines renders per-topic outcomes for batch create projects", () => {
  const lines = buildBatchCreateProjectResultLines({
    task_id: "task-5",
    job_type: "batch_create_projects",
    status: "done",
    created_at: "2026-05-23T10:00:00Z",
    started_at: "2026-05-23T10:00:01Z",
    finished_at: "2026-05-23T10:00:20Z",
    error: null,
    result: {
      requested_count: 3,
      processed_count: 1,
      skipped_count: 1,
      failed_count: 1,
      results: [
        {
          topic_slug: "topic-a",
          status: "done",
          error: null,
          project: {
            slug: "topic-a-project",
            title: "topic a",
            stage: "outline",
            owner: "editorial",
            preferred_tone_profile_id: null,
            preferred_tone_profile_name: null,
            domain_pack_key: null,
            chain_status: "missing",
            current_chain_state: "missing_outline",
            next_required_step: "generate_outline",
            current_outline_version: null,
            current_draft_version: null,
            current_assets_version: null,
            current_publish_package_version: null,
            retro: null,
          },
        },
        {
          topic_slug: "topic-b",
          status: "skipped",
          error: "Project already exists",
          project: null,
        },
        {
          topic_slug: "topic-c",
          status: "failed",
          error: "topic missing",
          project: null,
        },
      ],
    },
  });

  assert.deepEqual(lines, [
    "完成: topic-a -> topic-a-project",
    "跳过: topic-b - Project already exists",
    "失败: topic-c - topic missing",
  ]);
});

test("buildBatchCreateProjectResultMap indexes batch create outcomes by topic slug", () => {
  const resultMap = buildBatchCreateProjectResultMap({
    task_id: "task-6",
    job_type: "batch_create_projects",
    status: "done",
    created_at: "2026-05-23T10:00:00Z",
    started_at: "2026-05-23T10:00:01Z",
    finished_at: "2026-05-23T10:00:20Z",
    error: null,
    result: {
      requested_count: 2,
      processed_count: 1,
      skipped_count: 0,
      failed_count: 1,
      results: [
        {
          topic_slug: "topic-a",
          status: "done",
          error: null,
          project: {
            slug: "topic-a-project",
            title: "topic a",
            stage: "outline",
            owner: "editorial",
            preferred_tone_profile_id: null,
            preferred_tone_profile_name: null,
            domain_pack_key: null,
            chain_status: "missing",
            current_chain_state: "missing_outline",
            next_required_step: "generate_outline",
            current_outline_version: null,
            current_draft_version: null,
            current_assets_version: null,
            current_publish_package_version: null,
            retro: null,
          },
        },
        {
          topic_slug: "topic-b",
          status: "failed",
          error: "provider timeout",
          project: null,
        },
      ],
    },
  });

  assert.deepEqual(resultMap, {
    "topic-a": {
      topicSlug: "topic-a",
      status: "done",
      canRetry: false,
      message: null,
      projectSlug: "topic-a-project",
      line: "完成: topic-a -> topic-a-project",
    },
    "topic-b": {
      topicSlug: "topic-b",
      status: "failed",
      canRetry: true,
      message: "provider timeout",
      projectSlug: null,
      line: "失败: topic-b - provider timeout",
    },
  });
});

test("patchBatchCreateProjectResultAsDone updates counts and clears retry state after manual success", () => {
  const patched = patchBatchCreateProjectResultAsDone(
    {
      task_id: "task-7",
      job_type: "batch_create_projects",
      status: "done",
      created_at: "2026-05-23T10:00:00Z",
      started_at: "2026-05-23T10:00:01Z",
      finished_at: "2026-05-23T10:00:20Z",
      error: null,
      result: {
        requested_count: 2,
        processed_count: 0,
        skipped_count: 1,
        failed_count: 1,
        results: [
          {
            topic_slug: "topic-a",
            status: "failed",
            error: "provider timeout",
            project: null,
          },
          {
            topic_slug: "topic-b",
            status: "skipped",
            error: "Project already exists",
            project: null,
          },
        ],
      },
    },
    {
      slug: "topic-a-project",
      title: "topic a",
      stage: "outline",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      domain_pack_key: null,
      chain_status: "missing",
      current_chain_state: "missing_outline",
      next_required_step: "generate_outline",
      current_outline_version: null,
      current_draft_version: null,
      current_assets_version: null,
      current_publish_package_version: null,
      retro: null,
    },
    "topic-a",
  );

  assert.deepEqual(buildBackgroundTaskSummaryLines(patched), ["请求 2 项", "完成 1 项", "跳过 1 项", "失败 0 项"]);
  assert.deepEqual(buildBatchCreateProjectResultMap(patched), {
    "topic-a": {
      topicSlug: "topic-a",
      status: "done",
      canRetry: false,
      message: null,
      projectSlug: "topic-a-project",
      line: "完成: topic-a -> topic-a-project",
    },
    "topic-b": {
      topicSlug: "topic-b",
      status: "skipped",
      canRetry: true,
      message: "Project already exists",
      projectSlug: null,
      line: "跳过: topic-b - Project already exists",
    },
  });
});

test("mergeBatchCreateProjectResultMaps keeps old unmatched results and overwrites matched topics", () => {
  const merged = mergeBatchCreateProjectResultMaps(
    {
      "topic-a": {
        topicSlug: "topic-a",
        status: "failed",
        canRetry: true,
        message: "old error",
        projectSlug: null,
        line: "失败: topic-a - old error",
      },
      "topic-b": {
        topicSlug: "topic-b",
        status: "skipped",
        canRetry: true,
        message: "already exists",
        projectSlug: null,
        line: "跳过: topic-b - already exists",
      },
    },
    {
      "topic-a": {
        topicSlug: "topic-a",
        status: "done",
        canRetry: false,
        message: null,
        projectSlug: "topic-a-project",
        line: "完成: topic-a -> topic-a-project",
      },
    },
  );

  assert.deepEqual(merged, {
    "topic-a": {
      topicSlug: "topic-a",
      status: "done",
      canRetry: false,
      message: null,
      projectSlug: "topic-a-project",
      line: "完成: topic-a -> topic-a-project",
    },
    "topic-b": {
      topicSlug: "topic-b",
      status: "skipped",
      canRetry: true,
      message: "already exists",
      projectSlug: null,
      line: "跳过: topic-b - already exists",
    },
  });
});

test("buildRecentBatchCreateProjectResultMap keeps the newest batch-create result per topic across task details", () => {
  const resultMap = buildRecentBatchCreateProjectResultMap([
    {
      task_id: "task-older",
      job_type: "batch_create_projects",
      status: "done",
      created_at: "2026-05-23T10:00:00Z",
      started_at: "2026-05-23T10:00:01Z",
      finished_at: "2026-05-23T10:00:20Z",
      error: null,
      result: {
        requested_count: 2,
        processed_count: 1,
        skipped_count: 0,
        failed_count: 1,
        results: [
          {
            topic_slug: "topic-a",
            status: "failed",
            error: "provider timeout",
            project: null,
          },
          {
            topic_slug: "topic-b",
            status: "done",
            error: null,
            project: {
              slug: "topic-b-project",
              title: "topic b",
              stage: "outline",
              owner: "editorial",
              preferred_tone_profile_id: null,
              preferred_tone_profile_name: null,
              domain_pack_key: null,
              chain_status: "missing",
              current_chain_state: "missing_outline",
              next_required_step: "generate_outline",
              current_outline_version: null,
              current_draft_version: null,
              current_assets_version: null,
              current_publish_package_version: null,
              retro: null,
            },
          },
        ],
      },
    },
    {
      task_id: "task-ignore",
      job_type: "batch_generate_topics",
      status: "done",
      created_at: "2026-05-23T10:30:00Z",
      started_at: "2026-05-23T10:30:01Z",
      finished_at: "2026-05-23T10:30:20Z",
      error: null,
      result: {
        requested_count: 1,
        processed_count: 1,
        skipped_count: 0,
        failed_count: 0,
        results: [],
      },
    },
    {
      task_id: "task-newer",
      job_type: "batch_create_projects",
      status: "done",
      created_at: "2026-05-23T11:00:00Z",
      started_at: "2026-05-23T11:00:01Z",
      finished_at: "2026-05-23T11:00:20Z",
      error: null,
      result: {
        requested_count: 1,
        processed_count: 1,
        skipped_count: 0,
        failed_count: 0,
        results: [
          {
            topic_slug: "topic-a",
            status: "done",
            error: null,
            project: {
              slug: "topic-a-project",
              title: "topic a",
              stage: "outline",
              owner: "editorial",
              preferred_tone_profile_id: null,
              preferred_tone_profile_name: null,
              domain_pack_key: null,
              chain_status: "missing",
              current_chain_state: "missing_outline",
              next_required_step: "generate_outline",
              current_outline_version: null,
              current_draft_version: null,
              current_assets_version: null,
              current_publish_package_version: null,
              retro: null,
            },
          },
        ],
      },
    },
  ]);

  assert.deepEqual(resultMap, {
    "topic-a": {
      topicSlug: "topic-a",
      status: "done",
      canRetry: false,
      message: null,
      projectSlug: "topic-a-project",
      line: "完成: topic-a -> topic-a-project",
    },
    "topic-b": {
      topicSlug: "topic-b",
      status: "done",
      canRetry: false,
      message: null,
      projectSlug: "topic-b-project",
      line: "完成: topic-b -> topic-b-project",
    },
  });
});

test("pruneBatchCreateProjectResultMap removes results for topics no longer in queue", () => {
  const pruned = pruneBatchCreateProjectResultMap(
    {
      "topic-a": {
        topicSlug: "topic-a",
        status: "done",
        canRetry: false,
        message: null,
        projectSlug: "topic-a-project",
        line: "完成: topic-a -> topic-a-project",
      },
      "topic-b": {
        topicSlug: "topic-b",
        status: "failed",
        canRetry: true,
        message: "timeout",
        projectSlug: null,
        line: "失败: topic-b - timeout",
      },
    },
    ["topic-b"],
  );

  assert.deepEqual(pruned, {
    "topic-b": {
      topicSlug: "topic-b",
      status: "failed",
      canRetry: true,
      message: "timeout",
      projectSlug: null,
      line: "失败: topic-b - timeout",
    },
  });
});

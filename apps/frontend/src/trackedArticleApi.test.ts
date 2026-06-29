import { enrichTrackedArticleMetadata, enrichTrackedArticlesMetadataInBackground } from "./api/workbench.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

async function testEnrichTrackedArticleMetadataPostsToExpectedEndpoint() {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: RequestInfo | URL; init: RequestInit | undefined }> = [];

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        slug: "wechat-import-enrich-target",
        source_kind: "wechat_mp_import",
        source_name: "冷爱",
        title: "关系卡住的时候，很多人不是不想改，而是没电了",
        url: "https://mp.weixin.qq.com/s/enrich-target",
        author: "冷爱",
        summary: "从关系里的无力感切入，把问题落到精力透支而非方法缺失。",
        body_markdown: "正文",
        body_source: "content_noencode",
        structure_notes: "先写卡住感，再拆能量缺口，最后回到现实动作。",
        created_at: "2026-05-28T10:00:00+08:00",
        tags: ["关系修复", "能量耗尽", "公众号参考"],
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  }) as typeof fetch;

  try {
    const article = await enrichTrackedArticleMetadata("wechat-import-enrich-target");
    assert(article.slug === "wechat-import-enrich-target", "should return parsed tracked article payload");
    assert(calls.length === 1, "should issue exactly one request");
    assert(
      String(calls[0]?.input) === "http://localhost:8000/api/tracked-articles/wechat-import-enrich-target/enrich-metadata",
      "should post to enrich-metadata endpoint",
    );
    assert(calls[0]?.init?.method === "POST", "should use POST");
    assert(calls[0]?.init?.body === "{}", "should send an empty JSON body");
  } finally {
    globalThis.fetch = originalFetch;
  }
}

await testEnrichTrackedArticleMetadataPostsToExpectedEndpoint();

async function testEnrichTrackedArticlesMetadataInBackgroundPostsSelectedSlugs() {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: RequestInfo | URL; init: RequestInit | undefined }> = [];

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        task_id: "background-enrich-1",
        job_type: "enrich_tracked_articles_metadata",
        status: "queued",
        created_at: "2026-05-28T10:10:00+08:00",
      }),
      {
        status: 202,
        headers: { "Content-Type": "application/json" },
      },
    );
  }) as typeof fetch;

  try {
    const task = await enrichTrackedArticlesMetadataInBackground(["wechat-mp-cold-love-1", "wechat-mp-cold-love-2"]);
    assert(task.task_id === "background-enrich-1", "should return parsed task submission");
    assert(calls.length === 1, "should issue exactly one request");
    assert(
      String(calls[0]?.input) === "http://localhost:8000/api/tracked-articles/enrich-metadata/background",
      "should post to background enrich endpoint",
    );
    assert(calls[0]?.init?.method === "POST", "should use POST");
    assert(
      calls[0]?.init?.body === JSON.stringify({ article_slugs: ["wechat-mp-cold-love-1", "wechat-mp-cold-love-2"] }),
      "should send selected article slugs",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

await testEnrichTrackedArticlesMetadataInBackgroundPostsSelectedSlugs();

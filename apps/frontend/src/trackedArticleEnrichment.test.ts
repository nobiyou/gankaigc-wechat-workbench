import assert from "node:assert/strict";

import { autoEnrichTrackedArticles, hasTrackedArticleMetadataGaps } from "./trackedArticleEnrichment.ts";

function test(name: string, fn: () => void | Promise<void>) {
  Promise.resolve()
    .then(fn)
    .then(() => {
      console.log(`PASS ${name}`);
    })
    .catch((error) => {
      console.error(`FAIL ${name}`);
      throw error;
    });
}

test("hasTrackedArticleMetadataGaps detects missing author summary structure notes or tags", () => {
  assert.equal(
    hasTrackedArticleMetadataGaps({
      slug: "manual-gap",
      author: "",
      summary: "已有摘要",
      structure_notes: "已有结构备注",
      tags: ["关系修复"],
    }),
    true,
  );

  assert.equal(
    hasTrackedArticleMetadataGaps({
      slug: "manual-complete",
      author: "晚晴",
      summary: "已有摘要",
      structure_notes: "已有结构备注",
      tags: ["关系修复"],
    }),
    false,
  );
});

test("autoEnrichTrackedArticles only enriches articles with metadata gaps and continues after failures", async () => {
  const calls: string[] = [];
  const result = await autoEnrichTrackedArticles(
    [
      {
        slug: "needs-enrich-success",
        author: "冷爱",
        summary: "已有摘要",
        structure_notes: "",
        tags: ["公众号参考"],
      },
      {
        slug: "already-complete",
        author: "晚晴",
        summary: "已有摘要",
        structure_notes: "已有结构备注",
        tags: ["关系修复"],
      },
      {
        slug: "needs-enrich-fail",
        author: "",
        summary: "",
        structure_notes: "",
        tags: [],
      },
    ],
    async (slug) => {
      calls.push(slug);
      if (slug === "needs-enrich-fail") {
        throw new Error("Upstream service temporarily unavailable");
      }
    },
  );

  assert.deepEqual(calls, ["needs-enrich-success", "needs-enrich-fail"]);
  assert.equal(result.requestedCount, 3);
  assert.equal(result.eligibleCount, 2);
  assert.equal(result.successCount, 1);
  assert.deepEqual(result.failures, [
    {
      slug: "needs-enrich-fail",
      message: "Upstream service temporarily unavailable",
    },
  ]);
});

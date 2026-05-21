# Contract: Source Ingestion And Freshness

## `GET /api/dashboard/summary`

### Response Additions

```json
{
  "tracked_articles_count": 12,
  "source_ingestion_runs_count": 4,
  "latest_source_ingestion_at": "2026-05-21T09:15:00+08:00",
  "latest_source_ingestion_kind": "wechat_mp_import",
  "source_freshness_state": "fresh"
}
```

## `POST /api/wechat-mp/articles/import`

### Request

Existing request body is preserved.

### Response

```json
{
  "requested_count": 2,
  "imported_count": 1,
  "skipped_count": 1,
  "failed_count": 0,
  "run_id": 7,
  "results": [
    {
      "status": "created",
      "reason": null,
      "article": {
        "slug": "wechat-mp-night-read-12345-1",
        "source_name": "夜读关系实验室",
        "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
        "url": "https://mp.weixin.qq.com/s/example",
        "author": "北岛",
        "summary": "从关系修复案例提炼表达顺序。",
        "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
        "tags": ["wechat-mp", "夜读关系实验室"]
      }
    },
    {
      "status": "skipped",
      "reason": "Tracked article already exists for this URL",
      "article": {
        "slug": "wechat-mp-night-read-12345-1"
      }
    }
  ]
}
```

## `POST /api/trends/import`

### Response Additions

```json
{
  "run_id": 3,
  "skipped_count": 1
}
```

`results[*].status` stays line-oriented and now maps to aggregate run counters.

## `POST /api/trends/batch-generate-topics`

### Behavior

- If `trend_slugs` is omitted or empty, process the current eligible trend pool
- Response continues to be a background task submission

## `POST /api/tracked-articles/batch-generate-topics`

### Behavior

- If `article_slugs` is omitted or empty, process the current eligible tracked-article pool
- Task detail result must include `processed_count`, `created_count`, `skipped_count`, `failed_count`, and per-item reasons

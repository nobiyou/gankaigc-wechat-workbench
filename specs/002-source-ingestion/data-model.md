# Data Model: Source Ingestion And Freshness

## Overview

This feature extends the current persisted source pool with ingestion-run tracking, stronger deduplication, and dashboard freshness summaries.

## Source Ingestion Run

**Purpose**: Represents one completed source import operation.

**Fields**

- `id`: numeric identifier
- `source_kind`: source family such as `trend_import` or `wechat_mp_import`
- `status`: aggregate result such as `done`, `partial`, or `failed`
- `requested_count`: number of source items submitted to the run
- `created_count`: number of newly persisted source items
- `skipped_count`: number of duplicate or ineligible items
- `failed_count`: number of failed items
- `summary`: operator-facing short description
- `created_at`: run start time
- `completed_at`: run completion time

**Rules**

- One run can contain mixed item outcomes
- Dashboard freshness uses the latest successful or partially successful run timestamp

## Source Ingestion Item Result

**Purpose**: Represents one item outcome inside an ingestion run.

**Fields**

- `run_id`: parent ingestion run
- `item_key`: stable identity such as a trend line number or article URL
- `title`: operator-facing label
- `status`: `created`, `skipped`, or `failed`
- `reason`: optional explanation for skipped or failed outcomes
- `entity_slug`: slug of the created persisted entity when available

**Rules**

- Results are ordered by request order for predictable operator review
- `reason` is required when status is `skipped` or `failed`

## Tracked Article Deduplication Identity

**Purpose**: Captures the stable unique identity for imported reference articles.

**Fields**

- `url`: canonical article URL
- `slug`: existing local slug
- `source_name`: normalized account nickname
- `title`: imported article title

**Rules**

- URL uniqueness applies to imported WeChat MP articles
- Existing slug uniqueness remains in place for all tracked articles

## Dashboard Source Freshness Summary

**Purpose**: Adds upstream source health to the dashboard summary payload.

**Fields**

- `tracked_articles_count`: total tracked article count
- `source_ingestion_runs_count`: total recorded source-ingestion runs
- `latest_source_ingestion_at`: latest completed import timestamp or `null`
- `latest_source_ingestion_kind`: latest source kind or `null`
- `source_freshness_state`: `fresh`, `stale`, or `missing`

**Rules**

- `missing` means no source-ingestion run exists yet
- `fresh` means a source-ingestion run completed on the current local date
- `stale` means runs exist, but none completed on the current local date

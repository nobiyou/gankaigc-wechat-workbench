# WeChat MP Article Import Principle Port Plan

**Goal**

把 `wechat-article-exporter` 的技术原理移植到当前工作台，而不是部署或嵌入原 Nuxt 项目。第一版目标是让单账号用户通过自己的公众号后台登录态，搜索目标公众号，拉取公开文章列表，并导入到现有 `tracked_articles` 参考文章链路，继续用于“参考文章 -> 生成选题 -> 创建项目 -> 生成发布包”。

**Architecture**

新增一个后端微信公众平台导入边界：

- `wechat_mp_client` 负责微信后台协议：扫码登录、Cookie/Token 存取、`searchbiz`、`appmsgpublish`、错误归一。
- `wechat_import` API 负责面向工作台的业务动作：登录状态、搜索公众号、预览文章、导入参考文章。
- 现有 `tracked_articles` 继续作为内容生产链路的 canonical owner；微信导入模块只生产 `TrackedArticleCreate` 数据，不新增第二套参考文章表。
- 前端新增“公众号采集/导入”面板，调用后端接口，不保存微信 Cookie/Token。

**Tech Stack**

- Backend: FastAPI, Pydantic, SQLite through the existing `app.services.workbench` store pattern.
- HTTP client: `httpx`, already present through dev dependencies; move to runtime dependency when implementing the client.
- Frontend: React + TypeScript + Vite, using existing `apps/frontend/src/api/workbench.ts` API wrapper style.
- Verification: `python -m pytest`, frontend TypeScript build, focused tests for request mapping and import behavior.

**Baseline/Authority Refs**

- Existing reference article owner:
  - `apps/backend/app/schemas/tracked_articles.py`
  - `apps/backend/app/api/tracked_articles.py`
  - `apps/backend/app/services/workbench.py`
  - `apps/frontend/src/api/workbench.ts`
- Existing product boundary:
  - `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
  - The MVP favors manual/assisted publishing and single-account operation.
- Source protocol observed from `wechat-article-exporter`:
  - login QR: `https://mp.weixin.qq.com/cgi-bin/scanloginqrcode?action=getqrcode`
  - login polling: `https://mp.weixin.qq.com/cgi-bin/scanloginqrcode?action=ask`
  - login finalization: `https://mp.weixin.qq.com/cgi-bin/bizlogin?action=login`
  - account search: `https://mp.weixin.qq.com/cgi-bin/searchbiz`
  - article list: `https://mp.weixin.qq.com/cgi-bin/appmsgpublish`

**Compatibility Boundary**

- Keep all existing `tracked_articles` endpoints and payloads working.
- Do not introduce direct auto-publishing.
- Do not store WeChat Cookie/Token in frontend local storage.
- Do not log raw Cookie, Token, QR UUID, or full response headers.
- Do not require deploying `wechat-article-exporter`.
- Treat WeChat backend fields as unstable external contracts and isolate them behind one adapter.

**Verification**

- Backend tests prove:
  - login state storage never appears in public response models;
  - `searchbiz` query params match the WeChat backend contract;
  - `appmsgpublish` query params match list and keyword search modes;
  - nested `publish_page -> publish_info -> appmsgex` payload maps to import preview items;
  - selected preview items create `tracked_articles` and can generate topics through existing flow.
- Frontend build proves type compatibility after adding API types and panel wiring.
- Manual verification uses a real local run only after tests pass, with a non-production personal subscription account.

## Current Implementation Status (2026-05-24)

The original task breakdown below was written before the routed UI restructure and before the adapter landed in code. The current repository status is:

- Implemented in code:
  - Safe WeChat MP response schemas in `apps/backend/app/schemas/wechat_mp.py`
  - Local session storage and protocol adapter in `apps/backend/app/services/wechat_mp_client.py`
  - Backend API routes in `apps/backend/app/api/wechat_mp.py`
  - Frontend API wiring in `apps/frontend/src/api/workbench.ts`
  - Routed import UI in `apps/frontend/src/components/WechatMpImportPanel.tsx` and the `Sources` workspace, rather than the older `App.tsx` owner assumed by this plan
  - Backend coverage in `apps/backend/tests/test_wechat_mp_import.py`
- Verified in automated tests:
  - public session payload excludes `cookie` and `token`
  - `searchbiz` and `appmsgpublish` request construction
  - article preview normalization and duplicate-safe import into `tracked_articles`
  - imported articles can continue into the existing topic-generation flow
- Still pending final closure:
  - real-account local smoke against `mp.weixin.qq.com`
  - explicit runtime log inspection to confirm no Cookie/Token leakage during live login and import

Use the checklist sections below as the original implementation plan, but treat this status block as the current source of truth for what has already landed.

## Plan Basis

**Facts**

- Current project already has `tracked_articles` storage, API, frontend listing, and topic generation from reference articles.
- `wechat-article-exporter` uses WeChat MP backend login state and internal endpoints, not the official public account OpenAPI.
- Personal subscription accounts are sufficient if they can log in to `mp.weixin.qq.com`.

**Assumptions**

- The tool is for the user's own single account and local/private operation.
- The first version only needs article list import, not comments, read metrics, mass messaging, or publishing.
- SQLite remains the local persistence layer for this MVP stage.

**Unknowns**

- WeChat may change endpoint parameters, response fields, or risk controls.
- Some target accounts may disable name search or be hidden from `searchbiz`.
- QR login behavior may differ across account types or security settings.

**Ripple Signal Triage**

- Owner expansion: add a new WeChat MP adapter owner, but keep `tracked_articles` as the content owner.
- Downstream expansion: topic generation and batch generation must keep working for imported articles.
- Contract expansion: add new API contracts under `/api/wechat-mp/*`.
- Source-of-truth expansion: WeChat raw payload is external evidence, but normalized reference articles are the internal source.
- Verification expansion: use mocked WeChat responses for deterministic tests plus one manual real-login smoke test.

## File Map

**Create**

- `apps/backend/app/schemas/wechat_mp.py`
  - Pydantic request/response models for login state, account search, article preview, and import requests.
- `apps/backend/app/services/wechat_mp_client.py`
  - Protocol adapter and parser for WeChat MP backend.
- `apps/backend/app/api/wechat_mp.py`
  - FastAPI routes for login, search, preview, import, logout.
- `apps/backend/tests/test_wechat_mp_import.py`
  - Focused tests with mocked client responses.

**Modify**

- `pyproject.toml`
  - Move `httpx` into runtime dependencies if the service uses it outside tests.
- `apps/backend/app/core/settings.py`
  - Add local session store path and request timeout settings.
- `apps/backend/app/api/__init__.py`
  - Register `wechat_mp.router`.
- `apps/frontend/src/api/workbench.ts`
  - Add WeChat MP API types and client functions.
- `apps/frontend/src/App.tsx`
  - Add import panel near `Tracked Articles`.
- `apps/frontend/src/styles.css`
  - Minimal styling for the import panel using current panel/form conventions.
- `apps/frontend/src/contentSources.ts`
  - No change expected unless imported source labels need a new display mode.

**Do Not Modify**

- Existing `TrackedArticleItem` fields in the first pass.
- Existing topic/project generation contracts.
- Any publishing automation.

## API Design

All routes live under existing `/api` prefix.

- `GET /wechat-mp/session`
  - Returns login state: `{ "logged_in": true, "nickname": "...", "expires_at": "..." }`.
  - Never returns Cookie or Token.
- `POST /wechat-mp/login/qrcode`
  - Starts QR login and returns image bytes as a proxied response or a short-lived local QR URL.
- `GET /wechat-mp/login/status`
  - Polls QR scan state and, after confirmation, stores Cookie/Token server-side.
- `POST /wechat-mp/logout`
  - Clears local Cookie/Token.
- `GET /wechat-mp/accounts?keyword=<name>&begin=0&size=5`
  - Searches public accounts via `searchbiz`.
- `GET /wechat-mp/accounts/{fakeid}/articles?begin=0&size=5&keyword=`
  - Previews article list via `appmsgpublish`.
- `POST /wechat-mp/articles/import`
  - Imports selected preview articles into `tracked_articles`.

## Task 1: Add Backend Schema Contracts

**Files**

- Create `apps/backend/app/schemas/wechat_mp.py`
- Create `apps/backend/tests/test_wechat_mp_import.py`

**Why**

Make the new boundary explicit before implementation. This prevents raw WeChat payload fields from leaking into existing content models.

**Impact/Compatibility**

No runtime behavior changes until the router is registered.

**Verification**

```powershell
python -m pytest apps/backend/tests/test_wechat_mp_import.py
```

Expected first RED result: import or endpoint missing errors.

**Steps**

- [ ] Write test: assert session response shape excludes `cookie` and `token`.
- [ ] Verify RED with `python -m pytest apps/backend/tests/test_wechat_mp_import.py`.
- [ ] Add Pydantic models:
  - `WechatMpSessionStatus`
  - `WechatMpAccountItem`
  - `WechatMpArticlePreviewItem`
  - `WechatMpArticleImportRequest`
  - `WechatMpArticleImportResponse`
- [ ] Verify GREEN for schema-only tests.
- [ ] Commit with message: `Add WeChat MP import schema contracts`.

## Task 2: Implement Local Login State Store

**Files**

- Modify `apps/backend/app/core/settings.py`
- Create `apps/backend/app/services/wechat_mp_client.py`
- Extend `apps/backend/tests/test_wechat_mp_import.py`

**Why**

WeChat Cookie/Token are sensitive credentials. They need one local backend owner with explicit expiry and clearing behavior.

**Impact/Compatibility**

Adds local state only. Existing workbench data remains untouched.

**Verification**

```powershell
python -m pytest apps/backend/tests/test_wechat_mp_import.py
```

**Steps**

- [ ] Write test: storing a fake session returns `logged_in=True`, but serialized session status does not include raw Cookie/Token.
- [ ] Verify RED.
- [ ] Add settings:
  - `wechat_mp_session_path: str = "C:/tmp/gankaigc-wechat-workbench-wechat-session.json"`
  - `wechat_mp_request_timeout_seconds: float = 15.0`
- [ ] Implement `WechatMpSessionStore` with `load`, `save`, `clear`, and `status`.
- [ ] Verify GREEN.
- [ ] Commit with message: `Add local WeChat MP session store`.

## Task 3: Port WeChat MP Protocol Adapter

**Files**

- Modify `pyproject.toml`
- Modify `apps/backend/app/services/wechat_mp_client.py`
- Extend `apps/backend/tests/test_wechat_mp_import.py`

**Why**

This is the actual principle port from `wechat-article-exporter`: same backend endpoints and params, rewritten as a Python adapter.

**Impact/Compatibility**

The adapter isolates unstable WeChat internal APIs from the rest of the app.

**Verification**

```powershell
python -m pytest apps/backend/tests/test_wechat_mp_import.py
```

**Steps**

- [ ] Write tests for `searchbiz` query construction:
  - endpoint `https://mp.weixin.qq.com/cgi-bin/searchbiz`
  - params `action=search_biz`, `begin`, `count`, `query`, `token`, `lang=zh_CN`, `f=json`, `ajax=1`
- [ ] Write tests for `appmsgpublish` query construction:
  - endpoint `https://mp.weixin.qq.com/cgi-bin/appmsgpublish`
  - params `sub=list` without keyword and `sub=search`, `search_field=7` with keyword
  - params `fakeid`, `type=101_1`, `free_publish_type=1`, `sub_action=list_ex`
- [ ] Verify RED.
- [ ] Move `httpx>=0.28.0,<1.0.0` from dev dependency to runtime dependency if not already runtime.
- [ ] Implement client methods:
  - `start_login_qrcode`
  - `poll_login_status`
  - `finalize_login`
  - `search_accounts`
  - `list_articles`
  - `logout`
- [ ] Add headers:
  - `Referer: https://mp.weixin.qq.com/`
  - `Origin: https://mp.weixin.qq.com`
  - browser-like `User-Agent`
  - `Accept-Encoding: identity`
- [ ] Verify GREEN.
- [ ] Commit with message: `Port WeChat MP backend protocol adapter`.

## Task 4: Parse Article Payloads into Preview Items

**Files**

- Modify `apps/backend/app/services/wechat_mp_client.py`
- Extend `apps/backend/tests/test_wechat_mp_import.py`

**Why**

The WeChat response nests article data inside JSON strings. Parsing belongs in the adapter, not in API routes or UI code.

**Impact/Compatibility**

No existing content data changes. Imported content remains normalized before entering `tracked_articles`.

**Verification**

```powershell
python -m pytest apps/backend/tests/test_wechat_mp_import.py
```

**Steps**

- [ ] Write test with a sample `publish_page` payload containing `publish_list[0].publish_info.appmsgex`.
- [ ] Verify RED.
- [ ] Implement parser:
  - parse `publish_page`;
  - skip entries without `publish_info`;
  - parse `publish_info`;
  - flatten `appmsgex`;
  - map title/link/author/digest/update_time into `WechatMpArticlePreviewItem`.
- [ ] Add resilient errors for malformed JSON with context but no raw Cookie/Token.
- [ ] Verify GREEN.
- [ ] Commit with message: `Parse WeChat MP article previews`.

## Task 5: Add Backend Import API

**Files**

- Create `apps/backend/app/api/wechat_mp.py`
- Modify `apps/backend/app/api/__init__.py`
- Extend `apps/backend/tests/test_wechat_mp_import.py`

**Why**

Expose the adapter as workbench-specific actions and connect selected articles to the existing reference article pipeline.

**Impact/Compatibility**

Adds new endpoints only. Existing `/tracked-articles` endpoints keep working unchanged.

**Verification**

```powershell
python -m pytest apps/backend/tests/test_wechat_mp_import.py apps/backend/tests/test_app.py
```

**Steps**

- [ ] Write tests:
  - `GET /api/wechat-mp/session` returns safe login status.
  - account search returns normalized account items.
  - article preview returns normalized preview items.
  - import creates tracked articles through existing `create_tracked_article`.
- [ ] Verify RED.
- [ ] Implement router and register it in `apps/backend/app/api/__init__.py`.
- [ ] Import mapping:
  - `slug`: deterministic slug from source account + article id/hash.
  - `source_name`: account nickname.
  - `title`: article title.
  - `url`: article link.
  - `author`: author field or account nickname fallback.
  - `summary`: digest/abstract fallback to empty string.
  - `structure_notes`: default `Imported from WeChat MP article list; structure notes pending review.`
  - `tags`: include `wechat-mp` and account nickname when safe.
- [ ] Verify GREEN.
- [ ] Commit with message: `Add WeChat MP import API`.

## Task 6: Add Frontend API Types and Import Panel

**Files**

- Modify `apps/frontend/src/api/workbench.ts`
- Modify `apps/frontend/src/App.tsx`
- Modify `apps/frontend/src/styles.css`

**Why**

The user needs a visible low-friction workflow: login, search account, preview articles, import selected articles.

**Impact/Compatibility**

Adds controls near existing `Tracked Articles`; no navigation rewrite required.

**Verification**

```powershell
Set-Location apps/frontend
npm run build
```

**Steps**

- [ ] Write or extend frontend tests if current test harness covers API helpers; otherwise rely on TypeScript build for this slice.
- [ ] Verify RED or baseline build status.
- [ ] Add API types:
  - `WechatMpSessionStatus`
  - `WechatMpAccountItem`
  - `WechatMpArticlePreviewItem`
  - `WechatMpArticleImportResponse`
- [ ] Add functions:
  - `fetchWechatMpSession`
  - `searchWechatMpAccounts`
  - `fetchWechatMpArticles`
  - `importWechatMpArticles`
  - `logoutWechatMp`
- [ ] Add panel state and handlers in `App.tsx`:
  - session state;
  - account keyword;
  - selected account;
  - article previews;
  - selected article ids;
  - import result.
- [ ] Add minimal CSS matching existing panel/form/list styles.
- [ ] Verify GREEN with `npm run build`.
- [ ] Commit with message: `Add WeChat MP import panel`.

## Task 7: End-to-End Verification and Safety Review

**Files**

- No new files expected.
- Modify only if verification exposes a bug.

**Why**

This feature handles login state and private cookies, so completion requires security and runtime checks, not just unit tests.

**Impact/Compatibility**

Confirms the new flow does not break existing content production.

**Verification**

```powershell
python -m pytest
Set-Location apps/frontend
npm run build
```

Manual smoke after automated tests:

```powershell
uvicorn app.main:app --app-dir apps/backend --reload --host 0.0.0.0 --port 8000
Set-Location apps/frontend
npm run dev
```

Expected manual result:

- Open `http://localhost:3000`.
- WeChat MP panel shows logged-out state.
- QR login can be initiated.
- After login, account search works.
- Article preview works for a searchable account.
- Import creates rows in `Tracked Articles`.
- Imported rows can generate topics.
- Logout clears session.

**Steps**

- [ ] Run all backend tests.
- [ ] Run frontend build.
- [ ] Perform real-login local smoke with a personal subscription account.
- [ ] Inspect logs to confirm Cookie/Token are not printed.
- [ ] Check `git status --short` and confirm only expected files changed.
- [ ] Commit with message: `Verify WeChat MP import flow`.

## Risks

- **Internal API drift**: WeChat may change parameters or response shapes. Mitigation: isolate all WeChat-specific code in `wechat_mp_client.py` and cover parsing with fixtures.
- **Login/session expiry**: Cookie and token may expire quickly. Mitigation: surface explicit `login_expired` errors and provide logout/relogin controls.
- **Account search limits**: Some public accounts may not appear in `searchbiz`. Mitigation: show a clear empty state and keep manual tracked article entry available.
- **Rate limiting or risk control**: Repeated scraping may trigger WeChat protections. Mitigation: first version uses small page sizes, user-triggered pulls, no background crawling loop.
- **Sensitive credential leakage**: Cookie/Token could leak through logs or frontend state. Mitigation: never return raw credentials, never log headers, store only server-side local JSON with explicit clear action.

## Retirement

- Keep the current manual `POST /tracked-articles` flow. It remains the fallback when WeChat search fails or login is unavailable.
- Do not add a parallel reference-article store. If a temporary preview cache is added for UX, it must be short-lived and deletable, not a second source of truth.
- Retire any temporary mock endpoints after real adapter tests and API tests are stable.
- Revisit whether `structure_notes` needs richer extraction only after imported articles are reliably flowing into topic generation.

## Self-Review

- Spec coverage: covers principle port, no original project deployment, and maps to existing `tracked_articles`.
- Placeholder scan: no implementation step depends on undefined files or vague “add error handling”; each task names concrete files and verification commands.
- Type consistency: all new API responses are modeled in backend schemas and frontend types.
- Compatibility: existing tracked article and content generation contracts stay stable.
- Verification: backend, frontend, and manual login smoke are all required before claiming completion.
- Dual-track: manual tracked article entry remains an intentional fallback; no duplicate canonical owner is introduced.
- Decision hygiene: durable decision is adapter isolation plus `tracked_articles` as canonical content owner; source protocol refs are preserved above.

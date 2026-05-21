# GankAIGC 内容域重构文件映射表

**说明**

- 本表基于上一轮对 `GankAIGC` 的目录分析结果，以及当前工作区中的实施方案文档整理
- 当前工作区未挂载 `GankAIGC` 源码仓库，因此这里给的是**落地映射方案**，不是基于最新仓库 HEAD 的二次扫描结果
- 目标方向：把原有“论文/降 AI/文本优化”业务域，改造成“公众号内容全流程工作台”

**目标产品语义**

- 赛道：女性情感成长
- 形式：故事情感文
- 工作流：`热点 -> 选题 -> 大纲 -> 初稿 -> 精修 -> 发布包`
- V1 交付：可复制发布内容 + 发布前检查清单

## 1. 总体改造原则

1. 保留基础设施，不在基础设施层大动刀
2. 旧论文域不要继续扩展，改为新建内容域模型和服务
3. 路由名、页面名、接口语义全部切换到内容生产域
4. 先共存，再下线，避免一口气硬删导致全站不可用

## 2. 后端文件映射

| 旧文件/目录 | 当前职责推测 | 新职责 | 动作 |
| --- | --- | --- | --- |
| `package/main.py` | 应用启动、路由注册 | 保留启动骨架，注册新的内容域路由 | 中改 |
| `package/backend/app/models/models.py` | 论文域核心模型混合定义 | 拆成“基础模型 + 内容域模型”；逐步让内容域成为主域 | 重写 |
| `package/backend/app/routes/optimization.py` | 论文优化/降 AI 主业务入口 | 改成内容项目主工作流路由，或拆成 `projects.py` / `drafts.py` | 重写 |
| `package/backend/app/routes/prompts.py` | Prompt 模板或提示词接口 | 改成内容生产 prompt 配置与风格配置接口 | 中改 |
| `package/backend/app/services/optimization_service.py` | 核心文本处理服务 | 改成内容生成服务编排层 | 重写 |
| `package/backend/app/routes/*auth*` | 登录鉴权 | 保留 | 保留 |
| `package/backend/app/routes/*admin*` | 后台管理 | 保留，增加内容域配置入口 | 中改 |
| `package/backend/app/routes/*user*` | 用户信息与账户配置 | 保留，补公众号账号配置字段 | 中改 |
| `package/backend/app/services/*provider*` | 模型调用封装 | 保留 | 保留 |
| `package/backend/app/services/*task*` | 异步任务、队列、任务状态 | 保留，承接批量写稿任务 | 保留 |
| `package/backend/app/services/*export*` | 导出能力 | 保留，输出正文稿/摘要/检查清单 | 中改 |
| `package/backend/app/routes/*history*` | 历史记录 | 改成选题历史、稿件版本历史、发布包历史 | 中改 |

## 3. 建议新增的后端文件结构

下面这部分不是“旧文件映射”，而是建议你在重构时直接补出来的内容域落点。

| 新文件 | 职责 |
| --- | --- |
| `package/backend/app/models/content_models.py` | 内容域主模型：`accounts` `trend_items` `topic_candidates` `content_projects` `content_outlines` `content_drafts` `content_assets` `publish_packages` `tone_profiles` `generation_tasks` |
| `package/backend/app/routes/dashboard.py` | 工作台汇总接口 |
| `package/backend/app/routes/trends.py` | 热点抓取、热点列表、转选题 |
| `package/backend/app/routes/topics.py` | 选题库接口 |
| `package/backend/app/routes/projects.py` | 文章项目详情、状态推进 |
| `package/backend/app/routes/drafts.py` | 大纲、初稿、精修、版本切换 |
| `package/backend/app/routes/publish_packages.py` | 发布包构建与检查清单 |
| `package/backend/app/routes/tone_profiles.py` | 账号风格配置 |
| `package/backend/app/routes/batch_jobs.py` | 批量生成选题、批量生成初稿 |
| `package/backend/app/services/trend_service.py` | 热榜抓取与标准化 |
| `package/backend/app/services/topic_service.py` | 热点转选题、原创灵感转选题 |
| `package/backend/app/services/project_service.py` | 内容项目状态机 |
| `package/backend/app/services/draft_service.py` | 大纲生成、初稿生成、精修 |
| `package/backend/app/services/publish_service.py` | 标题组、摘要、封面文案、检查清单生成 |
| `package/backend/app/services/tone_profile_service.py` | 风格规则读取与组装 |
| `package/backend/app/prompts/content/` | 内容域 prompt 模板目录 |

## 4. 前端文件映射

| 旧文件/目录 | 当前职责推测 | 新职责 | 动作 |
| --- | --- | --- | --- |
| `package/frontend/src/pages/*` | 原论文业务页面 | 全部切到内容生产语义 | 大部分重写 |
| `package/frontend/src/api/*` | 原论文接口封装 | 切换到 `dashboard/trends/topics/projects/publish` | 大部分重写 |
| `package/frontend/src/router/*` | 页面路由 | 改成工作台型导航结构 | 中改 |
| `package/frontend/src/components/*layout*` | 通用布局 | 保留 | 保留 |
| `package/frontend/src/components/*table*` | 通用列表/表格组件 | 保留复用 | 保留 |
| `package/frontend/src/components/*form*` | 通用表单能力 | 保留复用 | 保留 |
| `package/frontend/src/store/*` | 全局状态 | 保留，补内容项目状态 | 中改 |
| `package/frontend/src/utils/*` | 工具函数 | 保留 | 保留 |

## 5. 建议新增的前端页面结构

| 新页面/模块 | 职责 |
| --- | --- |
| `package/frontend/src/pages/Dashboard` | 今日热点、待写选题、待精修稿件、待发布项目 |
| `package/frontend/src/pages/Trends` | 今日热榜聚合入口、热点过滤、收藏、一键转选题 |
| `package/frontend/src/pages/Topics` | 选题池管理 |
| `package/frontend/src/pages/Projects` | 文章项目列表 |
| `package/frontend/src/pages/ProjectWorkbench` | 单篇文章工作台：标题/大纲/初稿/精修/发布包 |
| `package/frontend/src/pages/BatchProduction` | 批量生成选题、批量生成初稿 |
| `package/frontend/src/pages/PublishCenter` | 发布包预览、摘要、封面文案、检查清单 |
| `package/frontend/src/pages/ToneProfiles` | 账号风格配置 |

## 6. 旧业务能力的去留映射

| 旧能力 | 新去向 | 处理建议 |
| --- | --- | --- |
| 论文降重/降 AI | 不再作为主业务 | 下线 |
| 文本优化 | 保留为“精修”子能力 | 改名后复用部分能力 |
| 历史结果记录 | 改成稿件版本记录 | 迁移语义 |
| 项目列表 | 改成内容项目列表 | 重命名并改字段 |
| 导出结果 | 改成发布包导出 | 扩展 |
| Prompt 管理 | 改成内容生产 Prompt 管理 | 重构 |
| 模型调用配置 | 保留 | 原样沿用 |
| 用户系统 | 保留 | 原样沿用 |
| 后台配置 | 保留 | 增加热榜源/风格模板配置 |

## 7. 数据模型迁移策略

| 旧表/旧模型类型 | 新表/新模型类型 | 处理方式 |
| --- | --- | --- |
| 论文任务表 | `generation_tasks` | 不直接复用业务字段，只复用任务框架 |
| 论文项目表 | `content_projects` | 新建 |
| 论文结果表 | `content_drafts` / `content_assets` / `publish_packages` | 拆开重建 |
| 用户配置表 | `accounts` / `tone_profiles` 的关联配置 | 扩展 |
| 历史记录表 | 稿件版本历史、发布历史 | 视旧表结构决定迁移或废弃 |

**推荐原则**

- 不要把 `paper_id`、`rewrite_type`、`ai_rate` 一类旧语义字段继续留在新主流程里
- 如果旧系统已有通用 `task_id`、`user_id`、`created_at`、`status` 这类基础字段，可以复用
- 旧数据若无保留价值，允许不迁移，只保留基础账号和系统配置

## 8. 路由替换映射

| 旧路由语义 | 新路由语义 |
| --- | --- |
| `/optimization/*` | `/projects/*` `/drafts/*` `/publish-packages/*` |
| `/prompts/*` | `/tone-profiles/*` `/prompt-templates/*` |
| `/history/*` | `/topics/*` `/projects/*/versions` `/publish-packages/*` |
| `/project/*` | `/projects/*` |

**建议的新接口分组**

- `GET /dashboard/summary`
- `GET /trends`
- `POST /trends/fetch`
- `POST /trends/{id}/to-topic`
- `GET /topics`
- `POST /topics`
- `PATCH /topics/{id}`
- `POST /topics/{id}/create-project`
- `GET /projects/{id}`
- `POST /projects/{id}/generate-outline`
- `POST /projects/{id}/generate-draft`
- `POST /projects/{id}/polish`
- `POST /projects/{id}/generate-assets`
- `POST /projects/{id}/build-publish-package`
- `GET /publish-packages/{projectId}`
- `GET /tone-profiles`
- `POST /tone-profiles`
- `PATCH /tone-profiles/{id}`
- `POST /batch/topics/generate`
- `POST /batch/projects/draft`

## 9. Prompt 体系映射

| 旧 Prompt 方向 | 新 Prompt 方向 | 动作 |
| --- | --- | --- |
| 学术降重 | 不需要 | 删除 |
| 学术润色 | 改为情感文精修 | 重写 |
| AI 检测规避 | 不作为产品主卖点 | 删除 |
| 文本改写 | 改为热点改写/情绪重写 | 重写 |
| 摘要生成 | 改为公众号摘要 | 中改 |

**新 Prompt 最小集合**

- `trend-to-topic`
- `topic-to-outline`
- `outline-to-draft`
- `draft-polisher`
- `title-summary-generator`
- `wechat-publish-package`

## 10. 分阶段实施文件动作

### Phase 1：内容域骨架落地

| 文件 | 动作 |
| --- | --- |
| `package/backend/app/models/models.py` | 停止继续塞论文字段，抽出内容域模型 |
| `package/backend/app/models/content_models.py` | 新建 |
| `package/main.py` | 注册新路由 |
| `package/frontend/src/router/*` | 增加新导航入口 |
| `package/frontend/src/pages/Dashboard` | 新建 |

### Phase 2：打通最小生产链

| 文件 | 动作 |
| --- | --- |
| `package/backend/app/routes/trends.py` | 新建 |
| `package/backend/app/routes/topics.py` | 新建 |
| `package/backend/app/routes/projects.py` | 新建 |
| `package/backend/app/services/topic_service.py` | 新建 |
| `package/backend/app/services/draft_service.py` | 新建 |
| `package/frontend/src/pages/Trends` | 新建 |
| `package/frontend/src/pages/Topics` | 新建 |
| `package/frontend/src/pages/ProjectWorkbench` | 新建 |

### Phase 3：批量日更能力

| 文件 | 动作 |
| --- | --- |
| `package/backend/app/routes/batch_jobs.py` | 新建 |
| `package/backend/app/services/project_service.py` | 扩展状态机 |
| `package/backend/app/services/*task*` | 接入批量任务 |
| `package/frontend/src/pages/BatchProduction` | 新建 |

### Phase 4：发布包与检查清单

| 文件 | 动作 |
| --- | --- |
| `package/backend/app/routes/publish_packages.py` | 新建 |
| `package/backend/app/services/publish_service.py` | 新建 |
| `package/frontend/src/pages/PublishCenter` | 新建 |

## 11. 第一批最值得先改的文件

如果你准备正式开改，我建议第一批只碰这 8 个点：

1. `package/backend/app/models/models.py`
2. `package/backend/app/models/content_models.py`
3. `package/backend/app/routes/optimization.py`
4. `package/backend/app/services/optimization_service.py`
5. `package/main.py`
6. `package/frontend/src/api/*`
7. `package/frontend/src/pages/ProjectWorkbench`
8. `package/frontend/src/pages/Topics`

## 12. 最终判断

这次改造不是“小修小补改文案”，而是：

- 基础设施保留
- 业务域整体替换
- 后端主流程重写
- 前端业务页面大面积重做

所以最稳的做法不是继续修旧论文链路，而是以“**新内容域并行落地**”的方式推进，等 `热点 -> 选题 -> 大纲 -> 初稿 -> 精修 -> 发布包` 全链路跑通后，再逐步清理旧论文能力。

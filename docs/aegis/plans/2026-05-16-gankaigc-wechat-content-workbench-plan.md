# GankAIGC 改造为公众号内容全流程工作台实施计划

**目标**

把 `GankAIGC` 从“论文文本处理工具”改造成面向**女性情感成长**赛道的**公众号内容全流程工作台**，服务单账号、自用、批量日更生产场景。

**产品定位**

- 账号定位：女性情感成长
- 内容类型：故事情感文
- 内容结构：共鸣叙述 + 场景铺陈 + 观点升华 + 自我和解收束
- 素材来源：原创灵感 + 热点改写
- 热点入口：今日热榜聚合 + 公众号内容跟踪
- 交付目标：生成可复制发布内容 + 发布前检查清单
- 非目标：自动接入公众号发布、多账号协作、复杂运营 BI

**总体策略**

- 保留 `GankAIGC` 的基础设施层：用户、任务、项目归档、导出、后台、AI 调用
- 重写业务语义层：从论文处理域切换到公众号内容生产域
- 新建内容域模型，不在旧论文表上硬改
- 优先打通 `热点 -> 选题 -> 大纲 -> 初稿 -> 精修 -> 发布包`

## 1. 范围定义

**MVP 范围**

- 热点抓取：今日热榜聚合，保存热点卡片
- 公众号跟踪：手动录入参考文章链接，提取标题、摘要、结构要点
- 选题库：从热点生成情感向选题，管理选题状态
- 批量写稿：批量生成标题、大纲、正文初稿
- 文章精修：改写、扩写、缩写、统一语气、提炼观点
- 发布包：公众号可复制正文、摘要、封面文案、发布前检查清单
- 风格设置：账号风格、禁用表达、结尾方式、目标字数

**明确不做**

- 直接自动发布到公众号
- 多账号 / 多角色协作
- 复杂权限系统
- 自动抓取已关注公众号后台内容
- 重运营数据报表

## 2. 核心用户工作流

1. 抓取今日热榜
2. 收藏热点并转成情感成长向选题
3. 为选题创建文章项目
4. 生成大纲
5. 生成初稿
6. 对选中稿件做精修
7. 生成标题组、摘要、金句、封面文案
8. 生成发布包与发布前检查清单
9. 手动发布并记录复盘

## 3. 页面结构

**工作台**

- 今日热点数
- 待写选题
- 待精修稿件
- 待发布项目
- 最近任务状态

**热点池**

- 热点列表、来源、热度、关键词
- 一键转选题
- 收藏与过滤

**选题库**

- 选题状态：`待写 / 写作中 / 已成稿 / 已发布 / 废弃`
- 来源类型：`原创 / 热点`
- 主题标签、情绪标签、角度标签

**文章工作台**

- 标题
- 大纲
- 正文版本
- 精修结果
- 金句、摘要、封面文案
- 发布包预览

**批量生产**

- 批量生成选题
- 批量生成初稿
- 查看异步任务结果

**发布中心**

- 公众号正文稿
- 标题备选
- 摘要
- 封面文案
- 发布检查清单

**风格设置**

- 开头风格
- 段落节奏
- 结尾风格
- 禁用表达
- 目标字数

## 4. 内容域数据模型

**accounts**

- 公众号账号配置
- 字段建议：`name` `positioning` `audience` `tone_profile_id` `target_word_count` `status`

**trend_items**

- 热点卡片
- 字段建议：`source` `title` `url` `summary` `heat_score` `keywords` `published_at` `raw_payload`

**tracked_articles**

- 参考公众号文章
- 字段建议：`source_name` `title` `url` `author` `summary` `structure_notes` `tags`

**topic_candidates**

- 选题池
- 字段建议：`account_id` `title` `source_type` `trend_item_id` `tracked_article_id` `emotion_tag` `theme_tag` `angle` `status` `priority`

**content_projects**

- 一篇文章的主项目
- 字段建议：`account_id` `topic_candidate_id` `working_title` `target_word_count` `status` `scheduled_for` `published_at`

**content_outlines**

- 大纲版本
- 字段建议：`project_id` `version` `outline_json` `hook` `core_conflict` `turning_points` `ending_style`

**content_drafts**

- 正文版本
- 字段建议：`project_id` `outline_id` `version` `title` `subtitle` `body_markdown` `word_count` `draft_stage`

**content_assets**

- 附属内容
- 字段建议：`project_id` `draft_id` `asset_type` `content`
- `asset_type`：`summary` `golden_sentence` `cover_copy` `lead` `tags` `comment_guide`

**publish_packages**

- 发布包
- 字段建议：`project_id` `final_draft_id` `wechat_body` `abstract` `cover_title` `publish_checklist_json` `status`

**tone_profiles**

- 风格中心
- 字段建议：`name` `opening_style` `paragraph_rhythm` `forbidden_phrases` `closing_style` `value_constraints`

**generation_tasks**

- AI 异步任务
- 字段建议：`project_id` `task_type` `input_snapshot` `output_snapshot` `status` `model_name` `cost_meta`

## 5. 状态设计

**topic_candidates.status**

- `new`
- `picked`
- `drafting`
- `used`
- `dropped`

**content_projects.status**

- `idea`
- `outline_ready`
- `draft_ready`
- `polishing`
- `publish_ready`
- `published`

**publish_packages.status**

- `building`
- `ready`
- `checked`
- `archived`

## 6. API 设计

**工作台**

- `GET /dashboard/summary`

**热点池**

- `GET /trends`
- `POST /trends/fetch`
- `POST /trends/{id}/to-topic`

**选题库**

- `GET /topics`
- `POST /topics`
- `PATCH /topics/{id}`
- `POST /topics/{id}/create-project`

**文章工作台**

- `GET /projects/{id}`
- `POST /projects/{id}/generate-outline`
- `POST /projects/{id}/generate-draft`
- `POST /projects/{id}/polish`
- `POST /projects/{id}/generate-assets`

**批量生产**

- `POST /batch/topics/generate`
- `POST /batch/projects/draft`

**发布中心**

- `GET /publish-packages/{projectId}`
- `POST /projects/{id}/build-publish-package`
- `POST /publish-packages/{id}/checklist`

**风格设置**

- `GET /tone-profiles`
- `POST /tone-profiles`
- `PATCH /tone-profiles/{id}`

## 7. Prompt / Skill 工作流

不要做一个万能 prompt，拆成稳定的 6 段：

1. `trend-to-topic`
- 输入：热点标题、摘要、关键词
- 输出：3-5 个女性情感成长向选题

2. `topic-to-outline`
- 输入：选题、风格、字数
- 输出：文章大纲、开头钩子、结尾方向

3. `outline-to-draft`
- 输入：大纲
- 输出：完整初稿

4. `draft-polisher`
- 输入：初稿
- 输出：更顺滑、更统一语气的版本

5. `title-summary-generator`
- 输入：正文
- 输出：标题组、摘要、金句、封面文案

6. `wechat-publish-package`
- 输入：最终稿
- 输出：公众号正文稿 + 发布前检查清单

**风格配置项**

- 账号定位：女性情感成长
- 开头方式：共鸣句 / 反问句 / 情境切入
- 中段节奏：场景铺陈 / 情绪递进 / 观点提炼
- 结尾方式：和解 / 自醒 / 放下 / 成长
- 禁用表达：硬说教、过度鸡汤、敏感词
- 字数范围：`1200-1800`

## 8. 模块复用与重写策略

**保留**

- 用户系统
- 任务系统
- 项目归档框架
- 导出能力
- 后台设置
- OpenAI-compatible / BYOK 调用层

**中改**

- 额度系统，改为成本控制或调用统计
- 历史记录，改为选题/写稿/发布包历史
- 项目列表与详情页，切换到内容项目语义
- 前端导航结构

**重写**

- 论文/降 AI 相关核心模型
- 主业务工作流
- Prompt 体系
- 前台交互文案
- 学术结果展示模块

## 9. 实施里程碑

**Phase 1：换领域骨架**

- 去掉论文域文案
- 新建内容域核心表
- 改导航结构

**Phase 2：打通最小生产链**

- 热点池
- 选题库
- 文章项目
- 大纲生成
- 初稿生成

**Phase 3：支持批量日更**

- 批量选题生成
- 批量初稿生成
- 异步任务管理

**Phase 4：精修与发布包**

- 精修
- 标题/摘要/封面文案
- 发布包输出
- 检查清单

**Phase 5：风格沉淀与复盘**

- 风格中心
- 发布后复盘
- 高表现结构沉淀

**里程碑定义**

- `M1`：能建选题，能生成大纲
- `M2`：能从大纲生成初稿
- `M3`：能批量生成多篇候选稿
- `M4`：能输出发布包
- `M5`：能沉淀账号风格

## 10. 风险与边界

**产品风险**

- 过早做自动发布会显著增加维护成本
- 过早做复杂抓取会拖慢首版交付
- 批量生产如果没有版本控制，后续很难复盘

**技术风险**

- 旧论文域字段和新内容域字段混用会造成语义污染
- Prompt 写死风格会导致后续难调优
- 同步生成接口会拖垮批量生产体验

**应对策略**

- 先人工发布，后考虑半自动发布辅助
- 先做热点聚合与手动参考文章录入
- 全部生成动作异步化
- 每一步保存输入快照和输出版本

## 11. 最小验收标准

- 能抓到热点并保存
- 能从热点生成选题
- 能从选题生成大纲和初稿
- 能一次批量产出多篇候选稿
- 能对选中稿件做精修
- 能导出公众号可复制正文、摘要、封面文案和发布检查清单

## 12. 下一步建议

1. 拿到 `GankAIGC` 本地仓库后，先做目录和文件级改造映射
2. 先落内容域表结构和状态机
3. 再逐页替换前端入口
4. 最后清理旧论文域残留

# 公众号内容工作台 UI 信息架构设计

## Status

Draft for review

## Goal

冻结当前工作台 UI 重构的一级导航、页面职责、单篇工作台交互边界，作为后续界面拆分和实现的共同基线。

## Scope

- 前端信息架构
- 页面职责边界
- 单篇 `Workbench` 主交互模型
- 现有单页模块的去留与归位

## Out Of Scope

- 视觉风格、配色、品牌语言
- 组件级像素排版
- 后端接口改造细节
- 本轮直接进入 UI 实现

## Source References

- `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
- `docs/aegis/baseline/2026-05-16-gankaigc-content-domain-file-mapping.md`
- `apps/frontend/src/App.tsx`

## TaskIntentDraft

- Outcome: 把当前“大单页工作台”拆成清晰的多页工作模式，降低认知负担，让主任务更突出。
- Success Evidence: 一级导航与主要页面职责清晰，`Workbench` 不再是长页面中的一个 section，而是独立专注页；旧的 `Task Center` 和 `Version History` 有明确归位。
- Stop Condition: 信息架构、页面边界、`Workbench` 主交互模型写成可执行设计说明，并经用户审阅。
- Non-goals: 本轮不定视觉细节，不写实现代码，不做接口联调。

## BaselineReadSetHint

- `docs/aegis/BASELINE-GOVERNANCE.md`
- `docs/aegis/specs/2026-05-18-spec-kit-aegis-operating-model.md`
- `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
- `docs/aegis/baseline/2026-05-16-gankaigc-content-domain-file-mapping.md`
- `apps/frontend/src/App.tsx`

## ImpactStatementDraft

- Affected Layers: `apps/frontend` 页面路由、布局层、工作台容器组件
- Owners: 本设计属于项目级 UI 架构边界，记录在 `docs/aegis/specs/`
- Invariants:
  - 保持内容域主链路 `topic -> outline -> draft -> assets -> publish`
  - 不再把采集、批量推进、单篇精修、历史、任务混放在同一页面
  - 不新建与 `spec-kit` 冲突的功能级实施计划
- Compatibility Boundary:
  - 允许页面重组
  - 不要求本轮改变后端业务归属
  - 不要求本轮定义最终视觉规范

## Problem Statement

当前 `apps/frontend/src/App.tsx` 承担了过多同层级职责：

- 快速录入、参考文章录入、风格配置、热点列表、参考文章列表、选题列表、项目列表、单篇工作台、版本历史、任务中心、批量结果全部堆在一个页面
- 首屏无法明确表达“今天该做什么”
- 列表管理和单篇生产抢同一层级
- 批量推进和单条操作混在一起，用户容易误判操作范围
- `Workbench` 被埋在长页面中间，缺少专注感

这不是视觉样式问题，而是信息架构失衡问题。

## Design Goals

1. 让“今天该做什么”比“系统里有什么”先被看见
2. 把“来源采集”“流程推进”“项目管理”“单篇工作台”拆成不同工作模式
3. 保留批量能力，但不让它淹没单篇主路径
4. 保留版本与审核能力，但让它们回到业务上下文，而不是继续占据独立大页
5. 让 `Workbench` 成为真正的单篇生产台

## Decision Summary

本次 UI 重构采用“一级按工作模式、二级按业务对象”的混合型导航。

核心决策如下：

1. 一级导航固定为 `Dashboard / Sources / Pipeline / Projects / Settings`
2. `Workbench` 不进入一级导航，而是从 `Projects` 进入的全屏专注页
3. `Dashboard` 采用“任务优先”而不是“数据优先”
4. `Sources` 允许单条快捷动作，`Pipeline` 统一承接批量推进与任务结果
5. `Projects` 采用“顶部筛选 + 按阶段分组的高密度列表”
6. `Workbench` 采用“左链路 + 右工作区”结构
7. 阶段顺序为推荐而非强锁定，允许跳转和回看
8. 每个阶段默认只展示当前版本，历史版本进入阶段抽屉
9. 阶段内可见质量问题，但最终审核集中在 `Publish`
10. 取消独立 `Task Center` 和独立 `Version History` 页面

## Primary Navigation

### 1. Dashboard

职责：展示“今天该推进什么”。

必须包含：

- 待转选题
- 待生成初稿
- 待审核项目
- 待复盘项目
- 最近任务摘要

规则：

- 首页不展开大列表
- 每张卡片都必须能跳到对应工作区
- 统计数据只能做辅助信息，不能压过待办优先级

### 2. Sources

职责：管理内容输入来源，以及来源层的单条处理动作。

二级结构：

- `Trends`
- `Tracked Articles`
- `WeChat Import`

规则：

- 这里负责采集、录入、浏览、筛选、单条处理
- 允许单条快捷动作，例如“转选题”“建项目”
- 不承担批量任务总览、异步结果汇总、失败重试中心

### 3. Pipeline

职责：承接从来源到项目的批量推进和异步运行。

二级结构：

- `Topic Queue`
- `Batch Runs`
- `Task Log`

说明：

- `Topic Queue` 作为选题阶段的集中管理区，承接热点和参考文章转出的选题
- `Batch Runs` 负责批量转选题、批量建项目、批量续跑内容链
- `Task Log` 负责异步状态、失败重试、结果汇总

规则：

- 任何会产生“批量结果”和“失败项重试”的动作，都应在这里有明确归位
- `Topics` 不再作为一级导航存在，而是作为 `Pipeline` 中的过渡对象管理区

### 4. Projects

职责：管理已经成为项目的内容生产对象，并作为进入 `Workbench` 的主入口。

页面形态：

- 顶部筛选、搜索、快捷过滤
- 主区按阶段分组展示高密度列表

推荐分组：

- `待补链`
- `待审核`
- `已发布`
- `待复盘`

规则：

- 不把单篇深度编辑塞回这个页面
- 这里负责“找项目”“看状态”“进入工作台”

### 5. Settings

职责：承接不属于日常生产主链路的配置能力。

优先纳入：

- `Tone Profiles`
- 规则配置
- 后续系统设置项

规则：

- 配置型能力不得与主生产链抢一级视觉注意力

## Workbench Entry Model

`Workbench` 是从 `Projects` 进入的全屏专注页，而不是一级导航项。

原因：

- 单篇生产属于高专注场景
- 如果长期挂在一级导航，会让导航重新膨胀为“功能清单”
- `Projects -> Workbench` 更符合“先选对象，再进入深度工作”的生产节奏

## Workbench Layout

## Top Summary Bar

顶部摘要栏至少包含：

- 项目标题
- 当前状态
- 当前推荐下一步
- 绑定风格
- 最近更新时间
- 当前卡点或审核状态

## Main Layout

采用“左链路 + 右工作区”：

- 左侧固定链路阶段
- 右侧展示当前阶段内容和操作

阶段固定为：

- `Topic`
- `Outline`
- `Draft`
- `Assets`
- `Publish`

## Interaction Rules

- 系统高亮当前推荐下一步
- 用户允许自由切换阶段
- 用户允许回看前序内容
- 用户允许基于审核或人工判断回退处理
- 不采用硬锁死流程

## Version Model

每个阶段采用“当前版本 + 历史抽屉”模式。

规则：

- 默认只显示当前有效版本
- 历史版本在抽屉中查看
- 恢复、对比、回看都从抽屉进入
- 不再保留全局独立版本历史页

## Review Model

审核机制采用“阶段可见问题，最终审核集中在 `Publish`”。

规则：

- `Outline / Draft / Assets` 阶段允许展示问题提示或返工上下文
- 最终通过、打回、要求重生成等操作集中在 `Publish`
- 打回后回到对应阶段处理，再回 `Publish` 复核

## Current Page To Future Structure Mapping

当前单页中的主要区块，后续应按以下方式迁移：

- `Quick Entry` -> `Sources` 中的快捷录入或全局快捷入口
- `Reference Article Entry` -> `Sources / Tracked Articles`
- `Tone Profile` -> `Settings`
- `Trends` -> `Sources / Trends`
- `Tracked Articles` -> `Sources / Tracked Articles`
- `Topics` -> `Pipeline / Topic Queue`
- `Projects` -> `Projects`
- `Project Workbench` -> 独立 `Workbench` 路由
- `Version History` -> 业务上下文内的历史抽屉与活动记录
- `Task Center` -> `Dashboard` + `Pipeline`
- `Batch Continue Results` 等批量结果 -> `Pipeline / Task Log`

## Retired Standalone Pages

本轮设计明确取消以下独立大页：

- `Task Center`
- `Version History`

这些能力并未消失，只是回归到更合适的业务上下文。

## Non-Goals And Deferrals

本设计明确不在本轮解决以下问题：

- 视觉风格与品牌表达
- 精细化组件布局与响应式细节
- 是否引入全局命令面板
- 是否引入复杂多栏看板视图
- 是否在 `Workbench` 中加入并列对照编辑器

## Compatibility Boundaries

后续实现必须保持以下边界：

1. 不允许再次把 `Sources`、`Pipeline`、`Projects`、`Workbench` 混回单页
2. 不允许为“任务”“历史”“审核”再各自拉出新的一级大页
3. `Topics` 作为过渡对象管理区，默认挂在 `Pipeline`，除非后续业务体量证明其需要独立升级
4. `Workbench` 的主职责是单篇推进，不承担批量总览
5. `Settings` 只承接配置，不承接主流程日常操作

## ADR Signals

本设计涉及项目级长期边界，存在 ADR 信号：

- 导航 owner 从“单页 section 堆叠”转为“多页工作模式”
- `Workbench` 被定义为独立专注页，而不是列表页子区块
- `Topics` 被定义为 `Pipeline` 内的过渡对象，而不是一级导航对象
- `Task Center` 和 `Version History` 从独立页面退役，改为上下文内能力

如果后续实现发现以下情况，需要回到设计层复核：

- `Topics` 的日常操作量超过 `Pipeline` 的容纳边界
- `Workbench` 需要同时承载多个并列阶段对照
- `Dashboard` 重新滑向“统计首页”而不是“任务首页”

## Review Checklist

- 是否保持了 `topic -> outline -> draft -> assets -> publish` 主链路
- 是否把列表管理、批量推进、单篇工作台分开
- 是否明确取消了独立 `Task Center` 和 `Version History`
- 是否给 `Topics`、`Workbench`、审核、版本历史都找到了明确归位
- 是否仍然保留了后续实现自由度，而没有过早压到视觉细节

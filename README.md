# gankaigc-wechat-workbench

公众号内容工作台。当前目标是把“热点发现 -> 选题沉淀 -> 项目推进 -> 发布准备”这条最小内容生产链打通，服务于女性情感成长方向的单账号日更生产场景。

## 当前阶段

项目已从“只读样例骨架”推进到“可运行 MVP”阶段，当前已经具备：

- 路由化工作台界面：`Dashboard / Sources / Pipeline / Projects / Settings / Workbench`
- SQLite 持久化存储，默认写入 `DB_PATH`
- 热点来源抓取与导入汇总
- 参考文章池与公众号文章导入
- 选题池、批量转选题、单条/批量建项目
- 创作工作流：策略包、问题说明书、对标分析、策略卡采纳
- 项目生产链：`outline -> draft -> assets -> publish package`
- 草稿诊断、AI 指纹与原创隔离提示、按诊断目标精修
- 创作复盘报告与可复用模式沉淀
- 发布审核、退回重生成、版本恢复与任务日志
- Settings 中的 AI 配置检测、风格配置、赛道包与 prompt 模板可见性

当前实现仍然是本地优先、单账号优先，不包含自动发布、多账号协作和复杂运营分析。

## 技术栈

- 前端：React 19 + TypeScript + Vite
- 后端：FastAPI + Pydantic Settings + SQLite
- AI 接入：OpenAI-compatible text + image generation
- 测试：pytest + FastAPI TestClient + 前端轻量 TypeScript harness

## 目录结构

```text
apps/
  backend/
    app/
      api/        # HTTP 路由
      core/       # 配置
      schemas/    # Pydantic 数据结构
      services/   # 业务聚合、持久化与 AI/微信适配
    tests/        # 后端测试
  frontend/
    src/
      api/        # 前端接口请求
      app/        # 路由壳与导航
      components/ # 通用组件（含公众号导入面板）
      pages/      # Dashboard / Sources / Pipeline / Projects / Settings / Workbench
      view-models/# 纯派生逻辑与测试
scripts/          # 自动化验证脚本
specs/            # feature-level spec / plan / tasks
docs/aegis/       # 基线、方案与实施记录
```

## 本地启动

### 1. 后端

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
Copy-Item .env.example .env
uvicorn app.main:app --app-dir apps/backend --reload --host 0.0.0.0 --port 8000
```

如果当前机器使用 Windows Store 版 Python，`python -m venv .venv` 可能会遇到 `ensurepip` 异常；此时可以先跳过虚拟环境，直接执行 `python -m pip install -e .[dev]`。

关键环境变量见 `.env.example`：

- `DB_PATH`：SQLite 数据库路径
- `GENERATED_ASSETS_DIR`：生成的封面图和素材文件目录
- `WECHAT_MP_SESSION_PATH`：公众号本地登录态存储路径
- `TREND_FEED_URLS`：RSS 热点源列表
- `OPENAI_*`：文本/图片模型与超时配置

### 2. 前端

```powershell
Set-Location apps/frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

默认访问地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`
- API 前缀：`http://localhost:8000/api`

## 测试与构建

```powershell
python -m pytest apps/backend/tests -q
Set-Location apps/frontend
npm test
npm run build
```

## 当前页面结构

- `Dashboard`
  - 首页待办队列、来源新鲜度、最近任务摘要
- `Sources`
  - 热点来源、参考文章、公众号文章导入
- `Pipeline`
  - Topic Queue、Batch Runs、Task Log、失败重跑入口
- `Projects`
  - 分组项目列表与检索筛选
- `Workbench`
  - 单项目生产工作台，支持策略生成、诊断精修、审核、回退与版本恢复
- `Settings`
  - Tone Profiles、AI 配置检测、Domain Packs、Prompt Templates

## 当前业务能力

### `trends`

- 手动录入热点
- 从配置的 RSS 源执行 `POST /trends/fetch`
- 批量将合格热点转成选题
- 记录来源抓取批次与重复跳过结果

### `tracked_articles`

- 手动录入参考文章
- 通过公众号后台会话搜索公众号并导入文章
- 对已导入文章批量生成选题
- 记录来源导入批次与新鲜度

### `topics`

- 手动创建原创选题
- 编辑标题、角度、状态
- 单条建项目与批量建项目
- 建项后自动把选题状态推进到 `drafting`

### `projects`

- 查看项目分组、阶段与下一步动作
- 进入单项目 Workbench
- 执行 `generate-strategy-package / adopt-strategy-card / generate-outline / generate-draft / diagnose-draft / polish-draft / generate-assets / build-publish-package`
- 发布审核通过、退回修改、按审核意见后台重生成
- 恢复历史版本并查看任务来源
- 生成创作复盘并沉淀可复用模式

### `assets / publish`

- 生成标题备选、摘要、封面文案、分发导语
- 调用图片模型生成横版封面图文件
- 生成发布包与审核状态

## 已知边界

- 不自动发布到公众号
- 不支持多账号协作与权限系统
- 公众号导入依赖 `mp.weixin.qq.com` 登录态，属于本地使用型适配能力
- 热点抓取目前以 RSS 源为主，还不是多平台统一采集框架

## 下一步建议

- 抽出内容账号配置中心，而不只是在风格配置里承载账号语义
- 扩展更多真实趋势源适配器，而不只依赖 RSS
- 对公众号导入流程补一轮真实账号 smoke 与日志脱敏复核
- 继续收紧 README、内部方案文档与代码状态的一致性

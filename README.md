# gankaigc-wechat-workbench

公众号内容工作台。当前目标是把“热点发现 -> 选题沉淀 -> 项目推进 -> 发布准备”这条最小内容生产链先打通，服务于女性情感成长方向的日更账号。

## 当前阶段

项目处于 MVP 骨架期，已经有前后端基础框架，正在补第一批核心业务模块：

- `trends`：热点线索池，记录来源、摘要、热度和跟进状态
- `topics`：选题池，从热点沉淀成可写选题
- `projects`：内容生产项目，承载从提纲、写作到发布前的推进状态

当前版本先提供只读样例数据和总览能力，目标是先让业务模型、接口结构和前端工作台界面稳定下来，再接入持久化和写入流程。

## 技术栈

- 前端：React 19 + TypeScript + Vite
- 后端：FastAPI + Pydantic Settings
- 测试：pytest + FastAPI TestClient

## 目录结构

```text
apps/
  backend/
    app/
      api/        # HTTP 路由
      core/       # 配置
      models/     # 预留：持久化模型
      schemas/    # Pydantic 数据结构
      services/   # 业务聚合与样例数据
      tasks/      # 预留：异步任务
    tests/        # 后端测试
  frontend/
    src/
      api/        # 前端接口请求
      components/ # 预留：通用组件
      pages/      # 预留：页面拆分
      router/     # 预留：路由配置
      store/      # 预留：状态管理
infra/            # 预留：部署与环境脚本
scripts/          # 预留：自动化脚本
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
python -m pytest
Set-Location apps/frontend
npm run build
```

## 第一批业务模块范围

### `trends`

- 目标：沉淀每日热点线索，区分“已抓取、待评估、已采纳”等状态
- 当前：只读列表接口 + 首页展示

### `topics`

- 目标：把热点转换成可执行选题，记录内容角度、预期读者收益和状态
- 当前：只读列表接口 + 首页展示

### `projects`

- 目标：承接选题后的生产过程，管理“待提纲、可成稿、待发布”等阶段
- 当前：只读列表接口 + 首页展示

## 下一步

- 接入数据库，替换内存样例数据
- 为 `trends / topics / projects` 增加创建、编辑、状态流转接口
- 引入任务中心，打通近期待办与首页统计
- 拆分前端页面和筛选视图，进入可运营的工作台形态

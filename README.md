# GradeWise

GradeWise 是一个面向单校试运行的学生成绩智能查询项目。项目采用 Vue 3、FastAPI、PostgreSQL、Redis、LangGraph 和官方 `deepagents`，当前已完成 MVP、P1 与 P2 功能。

## 当前交付范围

- 三个页面：登录、智能问数、数据看板。
- 四个角色：学生、任课教师、班主任、教务管理员。
- Deep Agents 主智能体、六个同步子智能体，以及批量报告/批量预警两个异步子智能体。
- LangGraph 固定执行链，安全审计不能被主智能体跳过。
- SQLGlot AST 白名单、参数化、只读 PostgreSQL 用户、超时、500 行限制和服务端权限范围注入。
- Redis 保存最近 12 条对话消息，默认 TTL 24 小时。
- Faker 生成 1 所学校及初一、初二、初三各 6 个班、每个年级 252 名学生的模拟数据；三个年级按独立课程方案、教师、班主任、考试和账号组织，成绩只能为整数或以 `.5` 结尾。
- 默认使用通义千问，并保留 DeepSeek 的 OpenAI-compatible 接口切换；未配置模型密钥时使用有限的安全查询模板，便于本地演示。
- P1 看板洞察：最近一次考试的学生均分分布（每名学生计一次）、统计异常、跨考试波动和最新不及格记录，全部由确定性 SQL 计算；关注记录支持分类分页查看。
- P1 个性化报告：学生生成本人成绩报告，教师与教务生成权限范围学情简报；姓名不发送给模型。
- P2 透明风险估计：基于最近成绩、历史不及格比例、趋势和波动生成可解释风险分数并保存快照。
- P2 数据导入：教务可导入 CSV、XLSX、JSON；包含标准化、实体匹配、分数边界、重复记录和批次审计。
- P2 交互与可视化：Web Speech API 中文语音输入、高风险集合变化浏览器提醒、独立图表 MCP 容器和 SVG 导出。
- P2 异步任务：独立 Agent Protocol 容器，支持按账号权限选择班级/科目/考试范围、任务历史、跨页面轮询、完成提醒、运行中更新、取消和结构化脱敏结果；任务台账与结果保存在 PostgreSQL，worker 状态丢失时可识别中断并重新执行。
- 跨学年分析：统一支持学年、年级、届别、学期、考试类型、班级、科目和考试范围；管理员可下钻，教师/班主任/学生只显示授权筛选项，多学年或多年级时自动切换为可比的得分率/及格率口径。
- 工程化基线：Alembic 版本化迁移、GitHub Actions 持续集成、structlog 结构化日志、数据库/Redis 就绪检查，以及登录到问数看图的 Playwright E2E。
- 前端按 ZRender 拆包，原 582.51 KB 的分析页大块降至 407.07 KB，构建不再触发 Vite 500 KB 警告。

当前 Docker Compose 启动 PostgreSQL、Redis、图表 MCP、Agent worker、后端和前端六个服务；后端启动前自动执行 `alembic upgrade head`。设计说明见 [架构基线](docs/architecture.md)、[阶段计划](docs/phases.md) 和 [最新测试报告](docs/test-report-2026-09-10.md)。

> 当前 `agent-worker` 使用官方 LangGraph 本地 Agent Server，提供真实 Agent Protocol，但运行时为内存模式，适合本地开发与验收。正式生产部署需替换为带持久化和服务端认证的 LangGraph/LangSmith Deployment 或兼容 Agent Protocol 运行时。

## 快速启动

1. 复制 `.env.example` 为 `.env`。
2. 至少修改 `POSTGRES_PASSWORD`、`APP_READONLY_PASSWORD` 和 `JWT_SECRET`。
3. 默认填写 `QWEN_API_KEY` 使用通义千问；如需切回 DeepSeek，设置 `LLM_PROVIDER=deepseek` 并填写 `LLM_API_KEY`。
4. 启动：

```bash
docker compose up --build
```

Compose 会先应用全部 Alembic 迁移，再启动 API；应用生命周期内不再通过 `create_all` 隐式修改数据库结构。

访问 `http://localhost:8080`，后端 OpenAPI 位于 `http://localhost:8080/api/docs`。

首次初始化会创建演示账号，密码均为 `GradeWise123!`：

| 账号 | 角色 | 权限范围 |
| --- | --- | --- |
| `student01` | 学生 | 本人数据 |
| `teacher01` | 任课教师 | 所授班级与科目 |
| `headteacher01` | 班主任 | 所管理班级全部科目 |
| `academic01` | 教务管理员 | 当前学校 |
| `g1_student01` | 初一学生 | 本人数据 |
| `g1_teacher01` | 初一任课教师 | 所授班级与科目 |
| `g1_headteacher01` | 初一班主任 | 所管理班级全部科目 |
| `g2_student01` | 初二学生 | 本人数据 |
| `g2_teacher01` | 初二任课教师 | 所授班级与科目 |
| `g2_headteacher01` | 初二班主任 | 所管理班级全部科目 |

此外提供 `teacher01`–`teacher17`（任课教师）与 `headteacher01`–`headteacher06`
（班主任）用于验证不同班级、科目和角色的数据权限，密码均与上表一致。

2026-2027 学年的课程方案为：初一开设语文、数学、英语、政治、历史、地理、生物；初二在此基础上开设物理；初三开设语文、数学、英语、政治、历史、物理、化学。语文、数学、英语满分 150、及格线 90，其余科目满分 100、及格线 60。年级课程配置是成绩导入与统计的权威规则，未开设科目不会被当作缺考或零分。

## 本地开发

前端：

```bash
cd frontend
npm install
npm run dev
```

后端需要 PostgreSQL 和 Redis。配置本机 `.env` 后：

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload
```

验证：

```bash
cd frontend && npm run build
cd backend && .venv/Scripts/ruff check --no-cache app tests alembic
cd backend && .venv/Scripts/python -m alembic check
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npm exec vue-tsc -- --noEmit -p tsconfig.app.json
```

核心浏览器 E2E 使用隔离的端口、数据库卷和空模型密钥运行：

```bash
docker compose -p gradewise-e2e -f docker-compose.yml -f docker-compose.e2e.yml up --build --detach --wait
cd frontend && npm run test:e2e
docker compose -p gradewise-e2e -f docker-compose.yml -f docker-compose.e2e.yml down --volumes --remove-orphans
```

## 关键安全边界

模型只能提出查询草案。最终 SQL 是否执行完全由确定性规则决定：

1. 解析 PostgreSQL AST，拒绝解析失败、注释、堆叠语句和 CTE。
2. 只接受单条 `SELECT`，只允许访问 `score_facts`。
3. 聚合函数采用白名单，拒绝 `pg_sleep`、文件读取、扩展调用等未知函数。
4. 所有模型生成的字面量由服务端转为命名参数。
5. 执行前将 `score_facts` 替换为服务端构造的授权 CTE，并按当前角色注入范围。
6. 使用独立 `gradewise_ro` 账号和只读事务执行，LLM 审计输出只作解释。

## 目录

```text
backend/app/agents       Deep Agents 注册与 LangGraph 查询链
backend/alembic          数据库版本化迁移脚本
backend/app/api          登录、问数、看板、洞察和报告 API
backend/app/core         配置、数据模型、结构化日志和 Faker 数据
backend/app/services     Redis 记忆、健康检查、脱敏与确定性 SQL 安全执行
agent-worker             独立批量报告/预警 Agent Protocol 服务
chart-mcp                独立 ECharts SVG 渲染 MCP 服务
frontend/src/views       仅三个业务页面
frontend/e2e             Playwright 核心端到端用例
.github/workflows        GitHub Actions 持续集成质量门
postgres/init            只读数据库角色初始化
docs                     架构与阶段计划
```

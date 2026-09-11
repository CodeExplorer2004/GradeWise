# GradeWise Agent 任务可靠性、安全与依赖基线测试报告（2026-09-10）

## 本次交付

- 新增 PostgreSQL `agent_tasks` 台账和 Alembic `20260910_0004` 迁移，任务所有权、范围、状态、尝试次数和结果不再依赖 Redis TTL。
- 后端持久化任务每个对外状态；只在 worker 明确返回 404 时将非终态任务标为 `interrupted`，临时连接失败保持原状态。
- 新增权限安全的 `POST /api/tasks/{task_id}/retry`；重试重新校验保存的请求范围，保留应用任务 ID，并创建新的 worker 执行。
- 创建和重试的数据准备/提交失败均保存安全错误码与用户提示，不暴露内部地址、异常文本或学生身份数据。
- 前端展示排队/运行/中断阶段、状态说明、尝试次数和更新时间，并只为可重试任务提供“重新执行”。
- Playwright 新增 Agent 中断与重试 UI 用例，并让核心问数用例在已有历史会话数据下保持幂等。
- 登录失败使用 Redis 按客户端 IP 与规范化账号摘要限流，默认 60 秒内第 5 次失败返回 429；成功登录清零，Redis 异常时按演示边界放行基础认证流程。
- FastAPI API 与 Nginx 静态页面增加 CSP、防嗅探、防嵌入、Referrer 和 Permissions Policy，Nginx 隐藏版本号；后端镜像 pip 固定为 26.2.1。
- backend 运行时、backend 开发工具和 Agent worker 运行时分别生成 Linux Python 3.12 精确哈希锁；Docker 与 CI 按锁安装，CI 同时检查锁漂移并分别执行漏洞审计。

## 验证环境

- 日期：2026-09-10
- 隔离 Compose 项目：`gradewise-hardening`
- 入口：`http://127.0.0.1:28080`
- 数据库：PostgreSQL 16；迁移版本 `20260910_0004 (head)`
- Agent worker：LangGraph 本地开发运行时；仅配置 E2E 占位密钥，未配置可用模型密钥

## 自动化结果

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量测试 | `python -m pytest -q -p no:cacheprovider` | 149 项通过，12.72 秒 |
| Ruff | `python -m ruff check --no-cache app tests alembic` | 全部通过 |
| Alembic 漂移 | `alembic check` | `No new upgrade operations detected` |
| Alembic 当前版本 | `alembic current` | `20260910_0004 (head)` |
| 前端生产构建 | `docker compose ... build frontend` | Vue TypeScript 检查与 Vite 构建通过；4,497 个模块，最大业务异步块约 407.20 KB，无 500 KB 警告 |
| Playwright E2E | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:28080 npm run test:e2e` | 3 项通过，7.1 秒；同时验证 API/SPA 安全头和 Nginx 版本隐藏 |
| 登录限流实链路 | 经 Nginx 连续提交 5 次无效探针账号 | 前 4 次返回 401，第 5 次返回 429，`Retry-After: 60` |
| 后端镜像 pip | `docker run --rm --entrypoint python gradewise-hardening-backend -m pip --version` | `pip 26.2.1`，Python 3.12 |
| Python 精确锁 | `./scripts/compile-python-locks.ps1` 后再次无升级生成并比较 SHA-256 | backend 运行时 86 包、开发锁 118 包、worker 运行时 81 包；三份锁均逐包固定版本与哈希，重复生成无漂移 |
| CI 锁安装模拟 | 干净 `python:3.12-slim` 中 `pip install --require-hashes -r backend/requirements-dev.lock` | 118 个包安装成功，`pip check` 无破损依赖 |
| Docker 锁安装 | `docker compose ... build backend agent-worker`，随后逐包比较 `pip freeze --all` | 两镜像构建通过；86/81 个运行时锁定包无缺失、无版本偏差、无额外业务包，两个镜像 `pip check` 均通过 |
| Python 漏洞审计 | `python -m pip_audit --disable-pip --require-hashes -r <runtime-lock>` | backend 与 Agent worker 均返回 `No known vulnerabilities found` |
| Compose 健康检查 | `docker compose ... up --build --detach --wait --wait-timeout 240` | PostgreSQL、Redis、图表 MCP、Agent worker、backend、frontend 六个服务全部健康 |

Playwright 覆盖：公开存活/就绪检查、教务登录后问数并显示图表与数据表、Agent 中断状态/尝试次数/重新执行交互。Agent UI 用例模拟后端任务协议，不调用外部模型。

## Docker 状态丢失与重试演练

使用 `academic01` 通过真实 `/api/tasks` 创建批量报告任务。首次真实请求暴露了 PostgreSQL `updated_at` 在异步 ORM 提交后未立即加载的问题，响应序列化触发 `MissingGreenlet`；新增回归断言并为 `AgentTask` 启用 `eager_defaults` 后，真实 API 路径恢复。

随后执行以下验收：

1. 创建任务，返回 `running / agent_running / attempt_count=1`。
2. 重建后端容器后重新登录并读取任务列表，任务仍存在，证明 PostgreSQL 台账不依赖后端进程内存。
3. 使用 `docker compose ... up --detach --force-recreate --no-deps agent-worker` 替换 worker 实例。普通 `restart` 会复用容器可写层，不能稳定模拟状态真正丢失，因此验收采用容器替换。
4. 查询原任务，返回 `interrupted / worker_state_missing / can_retry=true`，状态说明为“Agent 运行环境已重启，可重新执行”。
5. 调用 `POST /api/tasks/{task_id}/retry`，应用任务 ID 保持不变，返回 `running / attempt_count=2`。

演练创建的三条任务记录已从隔离数据库精确删除。由于 E2E 只有无效占位密钥，真实模型生成结果检查为：**未执行：未配置可用模型密钥**。本报告不将其计为通过。

## 当前边界

- worker 仍是内存开发运行时；数据库保留应用任务和结果，但不能恢复模型执行到精确中间步骤，重试是一次新执行。
- 已有基础登录失败限流与常见安全响应头，但 Redis 故障时采用演示优先的 fail-open；服务间鉴权、刷新令牌撤销、HttpOnly Cookie、可信代理 IP 解析和生产级 CSP 运维仍未实施。
- 尚未执行负载测试、系统化故障注入和备份恢复演练。
- 导入仍缺少批次回滚和大文件队列化。
- 通知主要依赖浏览器会话，没有持久站内信或外部消息通道。

这些边界不阻塞实习项目的本地体验与汇报演示，但在生产部署前仍需单独规划和验收。

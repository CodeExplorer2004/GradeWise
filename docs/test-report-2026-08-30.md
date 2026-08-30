# GradeWise 工程化升级测试报告（2026-08-30）

## 本次交付

- Alembic 版本化数据库迁移，应用启动不再调用 `create_all` 或内联结构变更。
- GitHub Actions 持续集成，覆盖后端、前端、迁移、服务配置和 E2E 质量门。
- structlog 结构化日志、请求 ID、耗时与敏感字段屏蔽。
- Vite 对 ZRender 独立分包，消除 500 KB 分块警告和循环依赖警告。
- 智能问数问题、历史、SQL 审计和结果行统一使用学生别名后再发送模型。
- liveness/readiness 健康检查，readiness 同时检查 PostgreSQL 与 Redis。
- Playwright 核心 E2E：教务登录、确定性问数、图表与结果表格渲染。

## 验证结果

| 范围 | 结果 |
| --- | --- |
| 后端测试 | 93 项通过，16.54 秒 |
| Ruff | `app`、`tests`、`alembic` 全部通过 |
| Alembic 现有库接管 | 升级到 `20260830_0002`，27,720 条成绩迁移前后不变 |
| Alembic 空库迁移 | 成功创建 14 张业务表、版本表及 `score_facts` 视图 |
| Alembic 漂移检查 | `No new upgrade operations detected` |
| Alembic 唯一性对齐 | 空库升至 `20260830_0003`；重复唯一约束 0 个，保留唯一索引 3 个 |
| 前端类型检查 | `vue-tsc --noEmit` 通过 |
| 前端生产构建 | 通过，无 500 KB 分块警告、无循环块警告 |
| 最大业务分块 | 由 582.51 KB 降至 407.07 KB；ZRender 独立为 177.02 KB |
| npm 生产依赖审计 | 前端与图表服务均为 0 项漏洞 |
| structlog | 生产 JSON 输出通过，`api_key` 输出为 `[REDACTED]` |
| 健康检查 | 隔离服务栈中 PostgreSQL、Redis 与 `/health/ready` 均健康 |
| Playwright E2E | 1 项通过，覆盖登录→问数→图表与表格，耗时 4.0 秒 |
| 模型隔离 | E2E 后端模型密钥为空，使用确定性查询路径，未产生外部模型调用 |
| CI YAML | 语法解析通过 |
| Docker Compose | 默认配置和 E2E 合并配置均通过校验 |

## E2E 隔离策略

E2E 使用 `gradewise-e2e` 独立 Compose 项目、独立 PostgreSQL/Redis 卷和
`127.0.0.1:28080` 入口。测试完成后删除隔离容器、网络和临时卷，不接触开发数据卷。
Agent worker 使用不会被调用的占位密钥满足图加载校验；后端模型密钥保持为空。

## 保留风险

- Agent worker 仍是官方内存开发运行时，不具备生产任务持久化和服务认证。
- 登录限流、刷新令牌撤销、HttpOnly Cookie、安全响应头和生产弱配置校验尚未实施。
- Python 依赖仍使用版本范围，尚未引入锁文件与 Python 漏洞审计。
- 尚未执行负载测试、故障注入和备份恢复演练。
- 浏览器通知仍依赖前端会话，没有站内信、邮件或企业消息通道。

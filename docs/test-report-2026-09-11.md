# GradeWise 平衡路线最终验收报告（2026-09-11）

## 最终结论

本轮“平衡路线”已完成。基础功能、Agent 可靠性、安全与依赖工程保持通过；Playwright 已由 3 项扩展到 7 项，汇报架构图、演示脚本和检查清单已补齐。

生产级精确断点恢复、令牌体系、服务间鉴权、压测、灾备、大文件队列和外部通知仍属于后续生产仿真路线，不计入本轮完成条件。

## 本次收尾交付

- 新增四角色端到端权限范围验证：学生 1 人、任课教师 84 人、班主任 42 人、教务管理员 756 人。
- 新增任课教师请求未授权班级返回 403 的数据越权拒绝验证。
- 新增同一客户端与账号组合第 5 次登录失败返回 429，并携带 Retry-After 的验证。
- 新增教务导入缺少必填字段的 CSV 时，整行拒绝且不写入的验证。
- 新增面向汇报的一页式 Mermaid 架构图。
- 新增 8–10 分钟演示脚本、演示前/中/后检查清单和故障回退表。
- 同步 README、架构基线和阶段交付状态。

## 验证环境

- 日期：2026-09-11
- 代码分支：codex/recent-exam-scope，已线性快进并包含 codex/production-hardening 全部提交
- 隔离 Compose 项目：gradewise-hardening
- 入口：http://127.0.0.1:28080
- 数据库：PostgreSQL 16
- Agent worker：LangGraph 本地开发运行时；E2E 不调用外部模型

## 最终自动化结果

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量测试 | python -m pytest -q -p no:cacheprovider | 149 项通过，11.69 秒 |
| Ruff | python -m ruff check --no-cache app tests alembic | 全部通过 |
| 前端生产构建 | npm run build | 4,497 个模块构建通过，43.24 秒；最大业务异步块 407.20 KB |
| Playwright E2E | npm run test:e2e | 7 项通过，9.0 秒 |
| Alembic 当前版本 | python -m alembic current | 20260910_0004 (head) |
| Alembic 漂移检查 | python -m alembic check | No new upgrade operations detected |
| Compose 配置 | docker compose ... config --quiet | 通过 |
| 六服务健康 | docker ps 按 gradewise-hardening 项目筛选 | PostgreSQL、Redis、chart-mcp、agent-worker、backend、frontend 全部 healthy |
| Readiness | GET /health/ready | status=ok，database=ok，redis=ok |
| backend Python 漏洞审计 | pip-audit 对 requirements.lock | No known vulnerabilities found |
| worker Python 漏洞审计 | pip-audit 对 agent-worker/requirements.lock | No known vulnerabilities found |
| 前端生产依赖审计 | npm audit --omit=dev --registry=https://registry.npmjs.org | found 0 vulnerabilities |
| 图表服务生产依赖审计 | npm audit --omit=dev --registry=https://registry.npmjs.org | found 0 vulnerabilities |
| 千问真实 API | qwen-plus-2025-07-28，完全合成数据 | 成功，2.8 秒，147 tokens，finish_reason=stop |

pip-audit 曾提示本机 Windows 缓存目录无法原子移动临时文件，但命令退出码为 0，两个锁文件均完成在线审计并返回无已知漏洞。默认 npmmirror 未实现 npm 安全公告端点，因此 npm 审计命令只在本次调用中显式使用官方 registry，未修改项目或用户配置。

## Playwright 7 项覆盖

1. 四角色登录与服务端数据范围。
2. 任课教师请求未授权班级被拒绝。
3. 登录失败达到阈值后返回 429。
4. 教务导入缺少字段的文件时逐行拒绝。
5. Agent 中断状态、原因、尝试次数与重新执行交互。
6. 网关 liveness/readiness、安全响应头和 Nginx 版本隐藏。
7. 教务登录、确定性问数、图表与数据表展示。

其中四角色权限用例直接调用真实登录和看板接口，不依赖前端隐藏逻辑；失败路径用例直接断言 403、429、Retry-After 和导入批次统计。

## 环境处理说明

首次尝试启动 gradewise-e2e 时发现 28080 已由健康的 gradewise-hardening 前端占用。验收未停止来源明确且正在使用的 hardening 环境，而是直接将它作为 Playwright 目标；本次创建但未完整启动的 gradewise-e2e 容器、网络和两个临时卷随后已精确删除，不影响 hardening 数据。

## 汇报材料

- [GradeWise 汇报架构图](demo-architecture.md)
- [GradeWise 最终演示运行手册](demo-runbook.md)
- [千问真实 API 测试报告](qwen-live-test-2026-09-11.md)
- [架构基线](architecture.md)
- [阶段交付](phases.md)

## 保留边界

- Agent worker 仍为内存开发运行时；PostgreSQL 可恢复应用任务状态和结果，但 worker 状态丢失后采用新执行，不恢复到模型执行的精确中间节点。
- 登录限流在 Redis 不可用时按演示优先策略 fail-open；刷新令牌撤销、HttpOnly Cookie、可信代理 IP、服务间鉴权和生产 CSP 运维尚未实施。
- 未执行负载测试、系统化故障注入和备份恢复演练。
- 大文件导入队列、导入批次回滚以及站内信/邮件/企业消息通知尚未实施。

这些事项不阻塞本轮单校本地试运行和项目汇报验收，但生产部署前必须单独设计和验证。

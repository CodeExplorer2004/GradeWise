# GradeWise 千问真实 API 测试报告（2026-09-11）

## 结论

千问 OpenAI-compatible API 的真实连通性、鉴权、指定模型选择和 JSON 响应均通过。测试只发送完全虚构的 DEMO-001 数据，没有发送数据库中的学生成绩、姓名、令牌或任何密钥。

## 测试配置

| 项目 | 值 |
| --- | --- |
| Provider | qwen |
| Base URL | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| 请求模型 | qwen-plus-2025-07-28 |
| 返回模型 | qwen-plus-2025-07-28 |
| API Key | 已配置，报告中不记录值 |
| 温度 | 0 |
| 最大输出 | 180 tokens |
| 响应格式 | json_object |

## 合成测试输入

系统提示要求只分析完全虚构的数据并严格返回 JSON。用户提示中的唯一成绩数据为：

- 学生代号：DEMO-001
- 最近三次数学得分率：72%、76%、81%
- data_classification 必须返回 synthetic

## 实际结果

| 指标 | 结果 |
| --- | --- |
| 请求状态 | 成功 |
| 耗时 | 2.8 秒 |
| finish_reason | stop |
| prompt_tokens | 96 |
| completion_tokens | 51 |
| total_tokens | 147 |

返回内容：

~~~json
{
  "status": "success",
  "trend": "improving",
  "advice": "继续保持当前学习节奏，建议针对薄弱知识点进行强化训练以维持上升趋势。",
  "data_classification": "synthetic"
}
~~~

## 验收断言

- 请求模型与服务返回模型完全一致。
- 响应以 stop 正常结束。
- 响应正文可以解析为 JSON。
- status 为 success。
- data_classification 为 synthetic。
- token 用量字段完整。

## 安全边界

原计划曾考虑通过学生报告接口验证完整链路，但该路径会把数据库中的学业上下文发送到外部服务。为了避免不必要的数据出站，本次改为使用同一 .env 中的 Base URL、模型和密钥直接调用千问，并只传输合成数据。因此本报告证明千问账户、模型和 API 兼容性可用，但不把“数据库学业数据经完整报告链路调用千问”列为已验证项。

## Docker 清理结果

真实模型测试后，已删除以下无容器引用的临时镜像：

- gradewise-e2e-backend:latest
- gradewise-e2e-agent-worker:latest
- gradewise-e2e-frontend:latest
- gradewise-e2e-chart-mcp:latest

删除后再次查询，gradewise-e2e 镜像列表为空。默认 gradewise 与 gradewise-hardening 两套环境各六个服务仍全部 healthy，8080 与 28080 的 readiness 均返回 PostgreSQL、Redis 正常。

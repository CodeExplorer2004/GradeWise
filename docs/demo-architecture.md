# GradeWise 汇报架构图

## 一页架构

~~~mermaid
flowchart LR
    subgraph U[使用者与权限边界]
        S[学生<br/>仅本人]
        T[任课教师<br/>所授班级与科目]
        H[班主任<br/>所管班级全部科目]
        A[教务管理员<br/>全校范围]
    end

    subgraph W[Web 入口]
        V[Vue 3<br/>问数 · 看板 · 任务]
        N[Nginx<br/>反向代理 · 安全响应头]
    end

    subgraph B[FastAPI 可信服务端]
        AUTH[JWT 登录<br/>Redis 失败限流]
        RBAC[RBAC + 分析范围校验<br/>服务端注入数据边界]
        API[确定性业务 API<br/>统计 · 风险 · 导入 · 报告]
        Q[LangGraph 问数编排<br/>近期考试确定性路径]
        GATE[SQLGlot 安全门<br/>只读 · 参数化 · 行数限制]
        TASK[Agent 任务服务<br/>中断识别 · 安全重试]
        PRIV[HMAC 身份脱敏<br/>模型前隐私边界]
    end

    subgraph D[数据与专用服务]
        PG[(PostgreSQL<br/>业务数据 · score_facts<br/>agent_tasks 账本)]
        R[(Redis<br/>会话 · 登录限流)]
        AW[Agent worker<br/>Agent Protocol]
        CM[Chart MCP<br/>ECharts SVG]
    end

    subgraph QL[工程质量门]
        CI[CI<br/>149 后端测试 · 7 E2E<br/>锁漂移 · 漏洞审计]
        LOCK[三套 Python 精确哈希锁<br/>Docker 按锁安装]
    end

    S & T & H & A --> V --> N --> AUTH --> RBAC
    AUTH <--> R
    RBAC --> API --> PG
    RBAC --> Q --> GATE --> PG
    Q --> PRIV --> AW
    API --> CM
    RBAC --> TASK --> PG
    TASK --> AW
    LOCK --> CI
    CI -.验证.-> N
    CI -.验证.-> B
    CI -.验证.-> D
~~~

## 汇报时只讲三条主线

1. **权限先于智能。** 四种角色的最大数据范围由 FastAPI 注入，筛选只能收窄范围，模型不能扩大范围。
2. **确定性规则决定能否执行。** SQLGlot、只读账号、参数化和行数限制共同构成执行门；LLM 只负责生成或解释。
3. **任务和依赖可追踪。** Agent 应用任务写入 PostgreSQL，worker 状态丢失时标记中断并允许安全重试；Python 镜像由精确哈希锁和 CI 审计约束。

## 当前边界

当前目标是单校本地试运行和项目汇报。worker 精确断点恢复、生产级令牌与服务鉴权、压测、灾备、大文件队列以及外部通知属于后续生产仿真路线，不计入本轮验收。

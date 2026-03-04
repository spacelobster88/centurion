# Centurion 工业级引擎升级报告

**项目**: Centurion — AI Agent Orchestration Engine
**仓库**: https://github.com/spacelobster88/centurion
**版本**: v0.1.0 (Alpha)
**日期**: 2026-03-04
**编制**: Claude Opus 4.6（综合两份独立评审意见）

---

## 一、项目现状评估

### 1.1 架构概览

Centurion 采用罗马军团隐喻的分层架构：

```
Centurion (Engine)          ← 顶层编排器
  └── Legion (部署组)        ← 资源配额隔离
       └── Century (Agent 分队) ← 同类 Agent 共享优先级队列 + 自动伸缩
            └── Legionary (个体 Agent) ← 单 Agent 实例，状态机管理
```

辅助系统：
- **Aquilifer (EventBus)**: 发布-订阅事件总线，1000 事件环形缓冲区
- **Optio (Autoscaler)**: 每个 Century 独立的自动伸缩控制器
- **CenturionScheduler**: K8s 风格的资源准入控制（CPU millicores / Memory MB）

### 1.2 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+，全异步 (async/await) |
| Web 框架 | FastAPI + Uvicorn |
| 数据库 | SQLite (WAL mode) + aiosqlite |
| API 模型 | Pydantic v2 |
| Agent 后端 | Claude CLI (subprocess) / Claude API (anthropic SDK) / Shell |
| 构建 | Hatchling (pyproject.toml) |
| 测试 | pytest + pytest-asyncio |

### 1.3 代码规模

| 指标 | 数值 |
|------|------|
| 主代码 | ~1,960 行 |
| 测试代码 | ~369 行 |
| 核心模块 | 13 个 |
| Agent 类型 | 3 种 |
| REST 端点 | 16 个 + 1 WebSocket |
| 类型注解覆盖 | 68%（19/28 文件） |
| 异步函数 | 66 个 |

### 1.4 已完成功能

- [x] 完整的分层架构（Engine → Legion → Century → Legionary）
- [x] 3 种 Agent 类型 + 插件注册表
- [x] REST API + WebSocket 事件流
- [x] K8s 风格资源调度（准入控制、资源配额）
- [x] 自动伸缩器（Optio）
- [x] 优先级任务队列
- [x] SQLite 持久化层（schema 已定义）
- [x] 硬件探测与节流
- [x] 基础测试套件（17-21 tests 通过）
- [x] 三种部署模式（独立服务器 / 嵌入路由 / 库）

### 1.5 生产就绪度评分

| 维度 | 评分 (0-10) | 说明 |
|------|:-----------:|------|
| 核心逻辑 | 7 | 架构清晰，异步原语使用正确 |
| 测试覆盖 | 3 | ~19% 覆盖率，无集成/压力测试 |
| 可观测性 | 2 | 仅 EventBus，无日志/metrics/tracing |
| 错误处理 | 4 | 有基础处理，缺乏重试/熔断 |
| 持久化 | 3 | Schema 存在但未接入引擎 |
| 部署就绪 | 2 | 无 Docker/CI/健康检查 |
| 安全 | 1 | 无认证/授权/速率限制 |
| 文档 | 6 | README 完整，缺运维文档 |
| **综合** | **3.5/10** | **Alpha 阶段，基础扎实但远未生产就绪** |

---

## 二、两份评审意见对比

本报告综合了两份独立评审意见（代号 **Plan-A** 与 **Plan-B**），以下是关键分歧分析：

### 2.1 优先级排序分歧

| 事项 | Plan-A 排序 | Plan-B 排序 | 最终裁定 |
|------|:-----------:|:-----------:|----------|
| 结构化日志 | P0 (第1天) | 未单独列出 | **P0** — 基础中的基础，一天可完成 |
| CI/CD | P0 (第1天) | P3 (第3-4周) | **P0** — 无自动化测试=沙上建塔 |
| 健康检查 | P0 | P0 | **P0** — 共识 |
| 测试补齐 | P1 (70%+) | P3 (90%+) | **P1** — 先到 70%，再迭代到 90% |
| 重试/熔断 | P2 | P0 | **P1** — 在测试保障下尽早实现 |
| 速率限制 | 未列入 | P0 | **P3** — v0.1 本地引擎暂不需要 |
| 性能优化 | 未单独列 | P1 | **P2** — 先正确，后快速 |
| 认证/RBAC | 未列入 | P2 | **P3** — 多租户需求明确后再做 |
| 混沌工程 | 未列入 | P3 | **P4** — 好主意，但需要前置基础 |

### 2.2 关键技术决策

| 决策点 | Plan-A | Plan-B | 最终裁定 |
|--------|--------|--------|----------|
| 任务队列 | 保留原生 asyncio.PriorityQueue | 引入 Celery + Redis | **保留原生** — Centurion 本身就是调度器，Celery 架构冗余 |
| 分布式协调 | Redis Sorted Set | Redis 缓存 + Celery | **Redis 协调层**（仅 Sorted Set + 分布式锁），不引入 Celery |
| 可观测性路径 | logging → Prometheus → OTel | 直接上 OTel | **渐进式** — logging 先行，OTel 基础设施就绪后接入 |
| 测试粒度 | 具体到文件/函数名 | 分类框架 | **合并** — 框架指导 + 具体清单执行 |

### 2.3 互补价值

Plan-B 补充的优秀建议（Plan-A 遗漏）:

| 建议 | 价值评估 |
|------|----------|
| 混沌工程（故障注入、网络分区） | 高 — 工业级韧性验证必备 |
| Webhook 回调 | 高 — 外部集成刚需 |
| 配置热更新 | 中 — 减少生产环境重启 |
| Postman 集合 | 中 — 开发者体验 |
| SDK/CLI 工具 | 中 — 降低使用门槛 |
| 速率限制（令牌桶） | 低（当前）→ 高（SaaS 化时） |

---

## 三、合并升级路线图

### Phase 0: 地基加固（Day 1-3）🔴 立即启动

> **目标**: 让项目具备最基本的工程化基础设施

#### 0.1 结构化日志系统

**范围**: 全模块添加 Python `logging`，JSON formatter

```
优先级：CRITICAL
工作量：0.5 天
依赖：无
```

- 统一日志配置（`centurion/logging.py`）
- JSON 格式化器（生产环境 JSON，开发环境彩色文本）
- 日志级别规范：
  - `DEBUG`: 调度决策细节、队列深度变化、资源探测值
  - `INFO`: Agent 生命周期、任务提交/完成、伸缩事件
  - `WARNING`: 资源压力、连续失败、队列积压
  - `ERROR`: Agent 崩溃、任务失败、数据库错误
  - `CRITICAL`: 引擎启动失败、系统资源耗尽
- 关键插入点：
  - `engine.py`: 引擎启动/关闭、Legion 创建/销毁
  - `century.py`: worker loop 异常（当前无日志！）、Optio 伸缩决策
  - `legionary.py`: 任务执行结果、失败计数、替换触发
  - `scheduler.py`: 准入决策、资源分配/释放
  - `router.py`: 请求日志（借助 FastAPI middleware）

#### 0.2 CI/CD Pipeline

**范围**: GitHub Actions 自动化

```
优先级：CRITICAL
工作量：0.5 天
依赖：无
```

`.github/workflows/ci.yml`:
- **Lint**: `ruff check` + `ruff format --check`
- **Type Check**: `mypy --strict` (渐进式，先 `--ignore-missing-imports`)
- **Test**: `pytest --cov --cov-report=xml` + coverage gate (初始 50%，逐步提升)
- **Build**: `python -m build` 验证 wheel 构建
- 触发条件: push to main, PR

`.github/workflows/release.yml`:
- Tag 触发 → 构建 → PyPI 发布
- Docker 镜像构建推送

#### 0.3 健康检查与优雅关闭

**范围**: 生产级生命周期管理

```
优先级：CRITICAL
工作量：1 天
依赖：0.1（日志）
```

健康检查端点：
- `GET /health` — 基础存活检查（返回 200 即可）
- `GET /health/ready` — 就绪探针：
  - 数据库连接可用
  - 调度器初始化完成
  - EventBus 运行中

优雅关闭增强：
- `shutdown_timeout` 纳入 `CenturionConfig`（当前硬编码 60s）
- SIGTERM/SIGINT 信号处理器
- 关闭顺序：停止接受新任务 → 等待进行中任务完成 → 终止 Agent → 关闭数据库连接 → 清理资源
- 关闭进度日志

---

### Phase 1: 可靠性基石（Week 1-2）🟡 高优先级

> **目标**: 测试保障 + 状态持久化 + 错误恢复

#### 1.1 测试覆盖率提升至 70%

**范围**: 补齐关键路径测试

```
优先级：HIGH
工作量：3-4 天
依赖：Phase 0（CI/CD 就绪）
```

**新增单元测试:**

| 模块 | 新增测试 | 覆盖点 |
|------|---------|--------|
| `test_events.py` 🆕 | 4 tests | 事件发布/订阅、环形缓冲溢出、慢消费者丢弃、序列化 |
| `test_claude_cli.py` 🆕 | 5 tests | subprocess 生成/超时/崩溃、环境清理、二进制不存在 |
| `test_claude_api.py` 🆕 | 4 tests | API 调用成功/失败、速率限制、token 统计 |
| `test_shell.py` 🆕 | 3 tests | 命令执行、超时、危险命令防护 |
| `test_registry.py` 🆕 | 3 tests | 注册/创建、重复注册、未知类型 |
| `test_router.py` 🆕 | 5 tests | CRUD 端点、404/409 错误码、任务提交 |
| `test_websocket.py` 🆕 | 2 tests | 事件流、客户端断开 |
| `test_repository.py` 🆕 | 4 tests | CRUD、任务生命周期、状态恢复、并发写入 |

**补充现有测试:**

| 模块 | 新增测试 | 覆盖点 |
|------|---------|--------|
| `test_engine.py` | +4 tests | 并发 Legion 创建、带运行任务关闭、状态恢复 |
| `test_century.py` | +8 tests | Optio 伸缩触发/冷却、worker 异常处理、Agent 替换、超时、并发提交 |
| `test_legion.py` | +5 tests | CPU/内存配额、least_loaded/random 策略、活跃任务中 dismiss |
| `test_legionary.py` | +3 tests | 超时处理、状态转换完整性、指标准确性 |
| `test_scheduler.py` | +3 tests | 并发分配、探测准确性、资源泄漏检测 |

**集成测试 🆕:**

```
tests/integration/
├── test_full_lifecycle.py
│   ├── test_create_legion_submit_task_get_result   ← 端到端黄金路径
│   ├── test_autoscale_under_load                   ← Optio 实际工作验证
│   └── test_graceful_shutdown_drains_tasks          ← 优雅关闭不丢任务
└── test_stress.py
    ├── test_100_concurrent_tasks                    ← 并发压力
    ├── test_rapid_scale_up_down                     ← 快速伸缩稳定性
    └── test_memory_leak_long_running                ← 内存泄漏检测
```

#### 1.2 持久化层接通

**范围**: 将已定义的 CenturionDB 接入核心引擎

```
优先级：HIGH
工作量：2-3 天
依赖：1.1（测试保障）
```

- Legion/Century/Legionary 状态写入 SQLite
- 任务状态全生命周期持久化：`PENDING → QUEUED → RUNNING → COMPLETED/FAILED`
- 进程重启恢复：
  - 重建 Legion/Century 结构
  - 未完成任务重新入队
  - 已完成任务结果可查
- 定期清理：过期任务记录（可配置保留天数）

#### 1.3 错误处理强化

**范围**: 分类异常 + 重试 + 熔断

```
优先级：HIGH
工作量：2 天
依赖：0.1（日志）
```

**具体代码修复点：**

| 文件 | 位置 | 当前问题 | 修复方案 |
|------|------|----------|----------|
| `century.py` | worker loop (~L250) | generic Exception catch 无日志 | 分类异常 + 结构化日志 + 指标 |
| `century.py` | Optio autoscaler | 无异常保护 | try/except + 自动重试 + 降级 |
| `century.py` | task futures dict | 已完成 future 无清理 | 定期清理 + 内存上限 |
| `legionary.py` | execute() | 不区分 timeout vs crash | 细粒度异常：`TimeoutError` / `ProcessError` / `APIError` |
| `scheduler.py` | probe_system() | 每次调用都探测系统 | 缓存 + 5s TTL |
| `router.py` | 全部端点 | 数据库异常未处理（500） | HTTPException 包装 + 日志 |
| `claude_cli.py` | subprocess 管理 | 无 zombie process 清理 | 显式 wait + SIGKILL fallback |
| `events.py` | ring buffer | 硬编码 1000 | 纳入 CenturionConfig |
| `config.py` | shutdown timeout | 硬编码 60s | 新增 `CENTURION_SHUTDOWN_TIMEOUT` |

**重试策略：**
- 任务级：指数退避（1s → 2s → 4s → 8s），最多 3 次
- 区分可重试错误（timeout, 临时网络故障）vs 不可重试错误（认证失败, 无效输入）
- 重试次数/状态纳入任务元数据

**熔断器：**
- Per-Century 熔断：连续失败 N 次（可配置，默认 5）→ 进入 OPEN 状态
- 冷却期（默认 30s）后 → HALF-OPEN（试探性放行 1 个任务）
- 试探成功 → CLOSED；失败 → 重回 OPEN

---

### Phase 2: 可观测性与容器化（Week 3-4）🟢 中优先级

> **目标**: 生产级可观测性 + 标准化部署

#### 2.1 Prometheus Metrics

```
优先级：MEDIUM
工作量：2 天
依赖：Phase 0
```

核心指标：

| 指标名 | 类型 | Labels | 说明 |
|--------|------|--------|------|
| `centurion_tasks_total` | Counter | status, century, legion | 任务总数 |
| `centurion_task_duration_seconds` | Histogram | century, agent_type | 任务耗时分布 |
| `centurion_active_agents` | Gauge | century, status | 活跃 Agent 数 |
| `centurion_queue_depth` | Gauge | century | 队列深度 |
| `centurion_agent_failures_total` | Counter | century, error_type | Agent 失败次数 |
| `centurion_resource_cpu_allocated` | Gauge | — | 已分配 CPU (millicores) |
| `centurion_resource_memory_allocated_mb` | Gauge | — | 已分配内存 (MB) |
| `centurion_autoscale_events_total` | Counter | century, direction | 伸缩事件 |
| `centurion_circuit_breaker_state` | Gauge | century | 熔断器状态 (0=closed, 1=open, 2=half-open) |

端点: `GET /metrics` (Prometheus text format)

#### 2.2 Docker 化

```
优先级：MEDIUM
工作量：1.5 天
依赖：0.2（CI/CD）
```

- 多阶段 Dockerfile（builder + runtime）
- `docker-compose.yml`:
  - `centurion` — 引擎服务
  - `prometheus` — 指标收集
  - `grafana` — 可视化（预配置 dashboard）
- 健康检查集成: `HEALTHCHECK CMD curl -f http://localhost:8100/health`
- 非 root 用户运行
- `.dockerignore` 优化镜像大小

#### 2.3 数据库优化

```
优先级：MEDIUM
工作量：1 天
依赖：1.2（持久化接通）
```

- aiosqlite 连接池（限制并发连接数）
- 关键查询索引（task status, legion_id, created_at）
- 任务记录归档策略（保留 N 天，历史迁移到冷存储）

---

### Phase 3: 企业集成能力（Week 5-6）🔵 中长期

> **目标**: 外部集成 + 动态配置 + 深度追踪

#### 3.1 Webhook 回调

```
优先级：MEDIUM
工作量：2 天
```

- 任务完成/失败时 POST 回调到指定 URL
- 配置: per-Century 或 per-Task webhook URL
- 重试策略: 指数退避，最多 3 次
- 幂等性: 每个回调携带唯一 delivery_id
- 签名验证: HMAC-SHA256 签名头

#### 3.2 配置热更新

```
优先级：MEDIUM
工作量：1.5 天
```

- 运行时可调参数（无需重启）：
  - Optio 伸缩阈值/冷却期
  - 任务超时
  - 熔断器参数
  - 日志级别
- API 端点: `PUT /config` + `GET /config`
- 变更事件通过 EventBus 广播
- 不可热更新的参数（需重启）：数据库路径、监听端口

#### 3.3 OpenTelemetry 分布式追踪

```
优先级：MEDIUM
工作量：2-3 天
依赖：0.1（日志）, 2.1（metrics）
```

- 任务从提交到完成的完整 trace
- Span 层级: API Request → Century Queue → Legionary Execute → Agent Backend
- 集成: Jaeger / Grafana Tempo
- 日志关联: trace_id 注入日志记录
- W3C TraceContext propagation

#### 3.4 审计日志

```
优先级：LOW-MEDIUM
工作量：1 天
```

- 管理操作记录: Legion/Century CRUD, 伸缩操作, 配置变更
- 不可变存储（append-only 表）
- 字段: timestamp, actor, action, resource, old_value, new_value
- API 端点: `GET /audit-log`

---

### Phase 4: 韧性验证（Week 7-8）🟣 高级

> **目标**: 通过混沌工程证明系统韧性

#### 4.1 混沌测试框架

```
优先级：MEDIUM
工作量：3 天
依赖：Phase 1-2 完成
```

**故障注入场景：**

| 场景 | 注入方式 | 预期行为 |
|------|----------|----------|
| Agent 随机崩溃 | Mock agent 随机抛异常 | 自动替换，任务重试 |
| 任务超时风暴 | 所有任务延迟 > timeout | 熔断器打开，队列积压告警 |
| 数据库连接断开 | Mock 数据库连接失败 | 降级运行（内存模式），恢复后同步 |
| 资源耗尽 | Mock scheduler 报告 0 可用资源 | 拒绝新 Agent，排队等待 |
| EventBus 分区 | 阻塞事件消费者 | 慢消费者被丢弃，不影响核心 |

**验证标准：**
- 系统在故障注入后 30s 内自动恢复
- 无数据丢失（已提交任务最终完成或明确失败）
- 内存/CPU 无泄漏
- 优雅降级（部分功能可用 > 完全不可用）

#### 4.2 负载测试

```
优先级：MEDIUM
工作量：2 天
```

使用 Locust 或自定义 asyncio 负载生成器：

| 测试 | 参数 | 通过标准 |
|------|------|----------|
| API 吞吐量 | 1000 req/s, 60s | P99 < 100ms, 0 error |
| 并发任务提交 | 100 tasks 同时提交 | 全部完成，无丢失 |
| 持续运行 | 10 tasks/min, 24h | 内存稳定，无泄漏 |
| 快速伸缩 | 每 10s 伸缩 1→10→1 | 无 zombie agent，资源正确释放 |

建立性能基线，纳入 CI 回归检测。

---

### Phase 5: 分布式与企业特性（Week 9+）⚪ 按需

> **目标**: 多机部署 + 多租户

#### 5.1 Redis 协调层

- 任务队列: asyncio.PriorityQueue → Redis Sorted Set
- 分布式锁: Optio Leader Election（多实例仅一个活跃伸缩器）
- 状态共享: Legion/Century 元数据跨进程可见
- **不引入 Celery** — Centurion 本身就是调度器

#### 5.2 多进程部署

- Gunicorn + uvicorn workers
- 共享状态通过 Redis
- Sticky session（WebSocket 连接亲和）

#### 5.3 认证与授权

- JWT 令牌认证
- API Key 管理
- RBAC: admin / operator / viewer
- 多租户隔离（per-tenant Legion 命名空间）

#### 5.4 SDK & CLI

- `centurion-cli`: 命令行管理工具
- `centurion-sdk`: Python SDK（封装 REST API）
- Postman 集合 + OpenAPI spec 自动生成

---

## 四、完整测试矩阵

### 4.1 测试金字塔

```
                    ╱╲
                   ╱  ╲         混沌测试 (5 scenarios)
                  ╱────╲
                 ╱      ╲       负载/压力测试 (4 benchmarks)
                ╱────────╲
               ╱          ╲     集成测试 (6 tests)
              ╱────────────╲
             ╱              ╲   API 测试 (7 tests)
            ╱────────────────╲
           ╱                  ╲  单元测试 (~70 tests)
          ╱────────────────────╲
```

### 4.2 单元测试清单（按模块）

#### Core 模块

**test_engine.py** (现有 4 + 新增 4 = 8)
- ✅ `test_raise_legion` — 创建 Legion
- ✅ `test_fleet_status` — 舰队状态
- ✅ `test_duplicate_legion_raises` — 重复 ID 报错
- ✅ `test_shutdown` — 关闭引擎
- 🆕 `test_concurrent_legion_creation` — 并发创建不冲突
- 🆕 `test_shutdown_with_running_tasks` — 关闭时等待任务完成
- 🆕 `test_fleet_status_accuracy_under_load` — 高负载下状态准确
- 🆕 `test_engine_state_recovery` — 重启后状态恢复

**test_century.py** (现有 3 + 新增 8 = 11)
- ✅ `test_muster_legionaries` — 召集 Agent
- ✅ `test_submit_task` — 提交任务
- ✅ `test_priority_ordering` — 优先级排序
- 🆕 `test_autoscaler_scale_up_trigger` — Optio 扩容触发条件
- 🆕 `test_autoscaler_scale_down_delay` — 缩容延迟生效
- 🆕 `test_autoscaler_cooldown_period` — 冷却期内不重复伸缩
- 🆕 `test_worker_loop_exception_handling` — worker 异常不崩溃
- 🆕 `test_legionary_replacement_on_failure` — 3 次失败自动替换
- 🆕 `test_task_timeout_handling` — 超时任务正确标记失败
- 🆕 `test_queue_overflow_behavior` — 队列满时的行为
- 🆕 `test_concurrent_task_submission` — 100 并发提交

**test_legion.py** (现有 4 + 新增 5 = 9)
- ✅ `test_add_century` — 添加 Century
- ✅ `test_batch_round_robin` — round_robin 分发
- ✅ `test_quota_enforcement` — 配额限制
- ✅ `test_dismiss` — 解散
- 🆕 `test_quota_cpu_enforcement` — CPU 配额
- 🆕 `test_quota_memory_enforcement` — 内存配额
- 🆕 `test_batch_least_loaded_strategy` — least_loaded 策略
- 🆕 `test_batch_random_strategy` — random 策略
- 🆕 `test_dismiss_with_active_tasks` — 活跃任务中解散

**test_legionary.py** (现有 5 + 新增 3 = 8)
- ✅ `test_creation` — 创建
- ✅ `test_execute_success` — 成功执行
- ✅ `test_execute_failure` — 失败执行
- ✅ `test_needs_replacement` — 替换判断
- ✅ `test_failure_reset` — 失败计数重置
- 🆕 `test_execute_timeout` — 超时处理
- 🆕 `test_status_transitions` — 完整状态转换链
- 🆕 `test_metrics_accuracy` — 任务计数/耗时准确

**test_scheduler.py** (现有 5 + 新增 3 = 8)
- ✅ `test_system_probe` — 系统探测
- ✅ `test_allocate_release` — 分配/释放
- ✅ `test_can_schedule` — 准入检查
- ✅ `test_hard_limits` — 硬限制
- ✅ `test_available_slots` — 可用槽位
- 🆕 `test_concurrent_allocation` — 并发分配安全
- 🆕 `test_system_probe_caching` — 探测结果缓存
- 🆕 `test_resource_leak_detection` — 资源泄漏检测

**test_events.py** 🆕 (4 tests)
- 🆕 `test_event_emit_and_subscribe` — 发布/订阅
- 🆕 `test_ring_buffer_overflow` — 超 1000 事件环形覆盖
- 🆕 `test_slow_subscriber_drop` — 慢消费者 QueueFull 丢弃
- 🆕 `test_event_serialization` — JSON 序列化

#### Agent 类型模块

**test_claude_cli.py** 🆕 (5 tests)
- 🆕 `test_subprocess_spawn` — 正常生成子进程
- 🆕 `test_subprocess_timeout` — 超时杀进程
- 🆕 `test_subprocess_crash` — 崩溃后状态正确
- 🆕 `test_env_sanitization` — 环境变量清理
- 🆕 `test_binary_not_found` — 二进制不存在错误

**test_claude_api.py** 🆕 (4 tests)
- 🆕 `test_api_call_success` — 正常调用
- 🆕 `test_api_rate_limit` — 429 处理
- 🆕 `test_api_auth_failure` — 401 处理
- 🆕 `test_token_usage_tracking` — token 计数

**test_shell.py** 🆕 (3 tests)
- 🆕 `test_command_execution` — 正常执行
- 🆕 `test_command_timeout` — 超时
- 🆕 `test_dangerous_command_prevention` — 危险命令（如适用）

**test_registry.py** 🆕 (3 tests)
- 🆕 `test_register_and_create` — 注册并实例化
- 🆕 `test_duplicate_registration` — 重复注册
- 🆕 `test_unknown_type` — 未知类型报错

#### API 模块

**test_router.py** 🆕 (5 tests, 使用 httpx AsyncClient)
- 🆕 `test_create_legion_201` — 创建返回 201
- 🆕 `test_submit_task_202` — 提交返回 202
- 🆕 `test_unknown_legion_404` — 未知 Legion 404
- 🆕 `test_duplicate_legion_409` — 重复 Legion 409
- 🆕 `test_scale_endpoint` — 伸缩端点

**test_websocket.py** 🆕 (2 tests)
- 🆕 `test_event_stream` — 事件流接收
- 🆕 `test_client_disconnect` — 断开不影响服务

#### 数据库模块

**test_repository.py** 🆕 (4 tests)
- 🆕 `test_save_and_load_legion` — CRUD
- 🆕 `test_task_lifecycle_persist` — 任务生命周期持久化
- 🆕 `test_state_recovery` — 状态恢复
- 🆕 `test_concurrent_writes` — 并发写入安全

### 4.3 集成测试

**test_full_lifecycle.py** 🆕
- 🆕 `test_create_legion_submit_task_get_result` — 端到端黄金路径
- 🆕 `test_autoscale_under_load` — Optio 真实伸缩
- 🆕 `test_graceful_shutdown_drains_tasks` — 优雅关闭不丢任务

**test_stress.py** 🆕
- 🆕 `test_100_concurrent_tasks` — 100 并发
- 🆕 `test_rapid_scale_up_down` — 快速伸缩
- 🆕 `test_memory_leak_long_running` — 长时间运行内存稳定

### 4.4 混沌测试

| # | 场景 | 注入 | 验证 |
|---|------|------|------|
| C1 | Agent 随机崩溃 | Mock agent 50% 失败率 | 自动替换，任务最终完成 |
| C2 | 全部 Agent 超时 | timeout=0.001s | 熔断器打开，不无限重试 |
| C3 | 数据库不可用 | Mock DB raise IOError | 降级运行或明确报错 |
| C4 | 资源耗尽 | scheduler.can_schedule→False | 排队等待，不崩溃 |
| C5 | EventBus 阻塞 | 消费者永不消费 | 生产者不阻塞，慢消费者被丢弃 |

### 4.5 性能基线

| 指标 | 基线目标 |
|------|----------|
| API P99 延迟 | < 50ms (无 Agent 调用) |
| 任务提交吞吐量 | > 500 tasks/s (入队) |
| Agent 启动时间 | < 2s (Claude CLI), < 100ms (API) |
| 内存 (1000 完成任务后) | 增长 < 50MB |
| EventBus 吞吐 | > 10,000 events/s |

---

## 五、稳定性升级关键修复点

### 5.1 按紧急程度排序

#### 🔴 紧急（Phase 0-1 必修）

| # | 文件 | 位置 | 问题 | 修复 |
|---|------|------|------|------|
| S1 | `century.py` | worker loop ~L250 | generic Exception 无日志 | 分类异常 + 结构化日志 + 指标上报 |
| S2 | `century.py` | Optio autoscaler | 无异常保护，崩溃则伸缩停止 | try/except + 自动重启 + 告警 |
| S3 | `century.py` | task futures dict | 已完成 future 不清理 → 内存泄漏 | 定期清理 + 内存上限 |
| S4 | `legionary.py` | execute() | timeout vs crash 不区分 | `TimeoutError` / `ProcessError` / `APIError` 三分类 |
| S5 | `claude_cli.py` | subprocess | 无 zombie process 防护 | 显式 wait() + SIGKILL fallback + 超时强杀 |
| S6 | `config.py` | shutdown timeout | 硬编码 60s | 新增 `CENTURION_SHUTDOWN_TIMEOUT` 环境变量 |
| S7 | `events.py` | ring buffer | 硬编码 1000 | 新增 `CENTURION_EVENT_BUFFER_SIZE` |
| S8 | `router.py` | 所有端点 | 数据库异常 → 裸 500 | HTTPException 包装 + 错误日志 |

#### 🟡 重要（Phase 1-2）

| # | 文件 | 位置 | 问题 | 修复 |
|---|------|------|------|------|
| S9 | `scheduler.py` | probe_system() | 每次调用都系统探测 | 缓存结果 + 5s TTL |
| S10 | `db/repository.py` | 整体 | 未接入核心引擎 | 完成持久化集成 |
| S11 | `__main__.py` | uvicorn 启动 | 单 worker，无生产配置 | 支持 gunicorn + 多 worker |
| S12 | `century.py` | PriorityQueue | 无队列深度上限 | 添加 maxsize + 拒绝策略 |
| S13 | 全局 | 无日志模块 | 无法调试生产问题 | 统一 logging 配置 |

#### 🟢 改进（Phase 3+）

| # | 文件 | 位置 | 问题 | 修复 |
|---|------|------|------|------|
| S14 | `mcp/tools.py` | 整个文件 | 1 行 stub | 实现完整 MCP tool 集 |
| S15 | `hardware/throttle.py` | 整体 | 未接入 EventBus | 资源告警事件接入 |
| S16 | `api/schemas.py` | 部分 response | `dict[str, Any]` | 更精确的 Pydantic 模型 |

---

## 六、实施时间表

```
Week 0 ──────────────────────────────────────────────────────────
  Day 1   [0.1] 结构化日志 ████████
  Day 2   [0.2] CI/CD Pipeline ████████
  Day 3   [0.3] 健康检查 + 优雅关闭 ████████

Week 1-2 ────────────────────────────────────────────────────────
  Day 4-7  [1.1] 测试覆盖率 → 70% ████████████████
  Day 8-10 [1.2] 持久化接通 ████████████
  Day 11-12 [1.3] 重试/熔断 + 错误处理 ████████

Week 3-4 ────────────────────────────────────────────────────────
  Day 13-14 [2.1] Prometheus Metrics ████████
  Day 15-16 [2.2] Docker 化 ██████
  Day 17    [2.3] 数据库优化 ████

Week 5-6 ────────────────────────────────────────────────────────
  Day 18-19 [3.1] Webhook 回调 ████████
  Day 20    [3.2] 配置热更新 ██████
  Day 21-23 [3.3] OpenTelemetry ████████████
  Day 24    [3.4] 审计日志 ████

Week 7-8 ────────────────────────────────────────────────────────
  Day 25-27 [4.1] 混沌测试框架 ████████████
  Day 28-29 [4.2] 负载测试 + 基线 ████████

Week 9+ (按需) ──────────────────────────────────────────────────
  [5.1] Redis 协调层
  [5.2] 多进程部署
  [5.3] 认证/RBAC
  [5.4] SDK/CLI
```

---

## 七、关键里程碑与验收标准

| 里程碑 | 时间 | 验收标准 |
|--------|------|----------|
| **M0: 工程化基础** | Day 3 | CI 绿灯 + 日志可搜索 + `/health` 返回 200 |
| **M1: 可靠性达标** | Week 2 末 | 测试 70%+ 覆盖率 + 重启后状态恢复 + 熔断器工作 |
| **M2: 可观测** | Week 4 末 | Grafana dashboard 可视化 + Docker 一键部署 |
| **M3: 可集成** | Week 6 末 | Webhook 可用 + OTel trace 端到端 |
| **M4: 韧性验证** | Week 8 末 | 混沌测试全通过 + 性能基线建立 |
| **M5: 生产就绪** | Week 9+ | 多机部署 + 认证 + SDK |

---

## 八、风险与缓解

| 风险 | 影响 | 概率 | 缓解 |
|------|------|------|------|
| 持久化接通改动面大 | 核心架构变更 | 中 | 先做测试保障（1.1），再接入（1.2） |
| Redis 引入增加运维复杂度 | 部署门槛 | 中 | Phase 5 按需，先用 SQLite 单机 |
| OTel 基础设施依赖外部 | 集成复杂 | 低 | 先独立 logging + metrics，OTel 延后 |
| 混沌测试可能暴露深层问题 | 延期 | 中 | 预留 buffer time，发现问题即修 |

---

*报告完*

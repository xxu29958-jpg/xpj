# 0030 Use in-process thread pool with SQLite progress table for v1.0 long tasks

- Status: accepted
- Date: 2026-05-23
- Decision makers: 项目维护者

## Context and Problem Statement

v1.0 V10-03（10k 行 CSV 导入）和 V10-04（v0.x → v1.0 迁移）会持续数分钟。当前 backend 只有两个"准长任务"：`fx_rate_scheduler.py` (daemon thread) 和 `uploads.py` 用 FastAPI `BackgroundTasks` 做 fire-and-forget OCR。

[[0016]] 红线明文"不引入额外 DB/后台任务框架"，写于 v0.3 时点，那时最大批量是单张小票。v1.0 多分钟任务需要：进度可查、可取消、崩溃恢复、并发上限。问题：[[0016]] 红线松到什么程度？

## Decision Drivers

- 单实例量级（≤5 并发用户、≤2 并发任务）；不是多机调度场景
- 已有 Windows Task Scheduler 4 个任务在管，不要再加 broker 进程
- 进度可查、可取消、崩溃自愈是 v1.0 强需求
- `fx_rate_scheduler` 跑得好好的，不要为长任务推翻现有 scheduler 模型
- 跟 [[0017]] 灰度产品边界一致（不引入 Linux/Docker/外部基础设施）

## Considered Options

- Stay strictly on [[0016]] red line: stdlib `ThreadPoolExecutor` + new `background_tasks` table + client polling
- Use [Huey + SQLite as broker][huey-sqlite] (lightweight queue, no Redis)
- Use ARQ / RQ + Redis (lightweight queue with broker process)
- Use Celery + Redis/RabbitMQ
- Use SQLite as ad-hoc queue with `BEGIN IMMEDIATE` write locks

## Decision Outcome

Chosen option: **Stay on [[0016]] red line — `ThreadPoolExecutor(max_workers=2)` + `background_tasks` progress table + 2s client polling**.

Tasks run in-process. Progress writes go to a new `background_tasks` table with `status / progress_current / progress_total / last_progress_at / cancellation_requested_at` columns. Long work is chunked into 50-100 row transactions so a crash mid-way leaves committed prefix intact. Backend startup force-fails every `status=running` **or** `status=queued` task it sees — single-process model means the previous executor died with the previous process, so anything not already terminal is an orphan the instant a new process starts. **No heartbeat threshold** (a previous draft of this ADR proposed a 5-min `last_progress_at` cutoff borrowed from distributed worker patterns; that's wrong here — fast restarts inside 5 min would leak phantom `running` rows, and `queued` rows would never be cleaned up at all).

Polling is GET `/api/tasks/{public_id}` every 2 s; no WebSocket / SSE. `fx_rate_scheduler` 保留不动——它是系统定时驱动，不是用户触发，跟 background_tasks 模型不重叠。

不选 Huey：虽然 Huey + SQLite broker ([MarkTechPost 2026][huey-sqlite]) 跟单机场景匹配，但仍引入框架抽象层，增加调试面、维护版本升级、跟 [[0016]] 文字红线相悖。stdlib 已经够这个量级，不付额外抽象成本。

不选 RQ/Celery/外部 broker：直接违反 [[0016]]，且 single-instance 量级用不上多 worker 多机调度。

## Consequences

Good:

- 零新外部依赖（Redis / broker / framework）
- 跟 [[0016]] 红线兼容，[[0017]] 灰度边界保持
- chunked transaction 让"崩在第 8000 行"也保留前 7950 行
- max_workers=2 封死"用户连点 10 次 import 把机器吃垮"

Bad:

- 进度上报靠每 chunk 写一次 DB，比 Huey/Celery 的 broker 模型粗糙
- 没有 retry 自动机制（失败任务用户手动重试）
- polling 比 push 多一些请求；2 s × 5 min ≈ 150 请求/任务（量级可忽略）
- 任务历史无 dashboard，需要走 `/api/tasks` 列表

## Confirmation

- chunked transaction 崩溃测试：100 行任务在 60 行处异常 → 前 50 行已 commit，result_summary 记 last_committed_row=50
- orphan recovery 测试：startup 时把 `running` 与 `queued` 全部 force-fail（无 heartbeat 阈值，单进程模型重启即 orphan）
- cancellation latency 测试：cancel 后 ≤100 ms 任务循环退出
- concurrent_limit 测试：第 3 个任务入队后 `status=queued`，第 1 个完成才开始
- account isolation 测试：account A 看不到 account B 的任务列表
- [[0031]] 联动：v1 迁移作为 `task_type=v1_migration` 跑同一框架

## More Information

- [[0016]] 不引入额外 DB/后台任务框架（本 ADR 是其 v1.0 例外，但**仅限**内嵌 stdlib 模型，不含外部 broker）
- [[0017]] 灰度版产品边界
- [[0031]] v1.0 迁移协议（复用本 ADR 执行框架）
- [Python sqlite3 progress handler][sqlite-progress]：长 SQL 操作的进度回调底层 API，可作为单 chunk 内的进度上报机制
- [Huey + SQLite as broker (MarkTechPost 2026)][huey-sqlite]：v1.x 如果实测 stdlib 不够再回顾的候选

[sqlite-progress]: https://docs.python.org/3/library/sqlite3.html
[huey-sqlite]: https://www.marktechpost.com/2026/04/17/a-coding-guide-to-build-a-production-grade-background-task-processing-system-using-huey-with-sqlite-scheduling-retries-pipelines-and-concurrency-control/

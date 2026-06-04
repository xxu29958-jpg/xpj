package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

/**
 * codex P1 #7 默认上限——指的是**总尝试次数**(N attempts total, 不是 "N 次重试再加首
 * 次")。换句话说 maxAttempts=10 表示 dispatcher 最多被调 10 次, 第 10 次仍 retryable
 * 失败就 FAILED, 跟 OkHttp / urllib3 `Retry(total=N)` 一致。
 *
 * 10 次足够覆盖典型瞬时故障(每次绑 back-off, 总跨度可超过半小时);仍卡住更可能是
 * 结构性问题(后端版本不兼容、payload 损坏等), 不该继续盲重试。
 *
 * `internal` 因为只该 engine + 同 module 测试用; 外部调优应该通过 engine 构造参数传入。
 */
internal const val DEFAULT_MAX_ATTEMPTS: Int = 10

/**
 * ADR-0042 §4.10 client-outbox PENDING age-cap.
 *
 * A PENDING row carries an [idempotencyKey] (intent-time UUID). The server keeps
 * the matching key in `api_idempotency_keys` for only ~30 days, then purges it.
 * If a row sits PENDING **longer than that retention** and *then* replays, the
 * server no longer holds its key → it reads the replay as a brand-new request →
 * **double-apply**: the idempotency protection that the whole ADR-0042 plumbing
 * exists to provide is silently gone (a confirm fires twice, an edit re-applies
 * to a now-different state, etc).
 *
 * So a row older than this cap must be **reaped — flipped to FAILED and NEVER
 * replayed** — and surfaced to the user, who can redo the action by hand against
 * fresh server state. The reaper is a keys-to-production prerequisite.
 *
 * 7 days is chosen to stay **safely under** the server's ~30-day key retention:
 * we fail the row with weeks of head-room, so a reaped row is never one that
 * *would* have replayed against a still-valid key — we always give up well before
 * the key could expire, never after. (If the server retention is ever shortened,
 * this cap must shrink in lock-step to preserve the same margin.)
 *
 * `internal` for the same reason as [DEFAULT_MAX_ATTEMPTS]: engine + same-module
 * tests only; production tuning would go through an engine constructor param.
 */
internal const val OUTBOX_PENDING_AGE_CAP_MILLIS: Long = 7L * 24 * 60 * 60 * 1000

/**
 * ADR-0038 PR-2g drain engine.
 *
 * Pure orchestration: dequeue → dispatch → status transition. The
 * engine itself is unit-testable on the JVM — no Android primitives,
 * no WorkManager. PR-2g.2 will wire a WorkManager-backed scheduler
 * that triggers [drainOnce] on connectivity-up + a periodic tick;
 * PR-2g.3 will route the mutation call sites through the outbox so
 * actual rows land in the queue.
 *
 * Invariants the engine preserves:
 * 1. Dequeue order is causal (``createdAt`` ASC) — guaranteed by
 *    [OutboxRepository.dequeueNextRunnable].
 * 2. Same target serial — also guaranteed by the repository.
 * 3. Each row gets exactly one in-flight ApiService call per
 *    [drainOnce] invocation; status transitions persist before the
 *    next row is dequeued, so a crash mid-drain leaves the queue
 *    in a consistent state on restart.
 * 4. Unknown mutation types ([PendingMutationType.Unknown]) and
 *    types with no registered dispatcher are marked FAILED with
 *    ``no_dispatcher_registered:<wireType>`` (codex round-1 P2#5).
 *    They leave the PENDING queue so newer same-or-later rows
 *    can proceed; the user clears them via
 *    [OutboxRepository.resolveFailed] (Retry after app upgrade
 *    that supplies the missing dispatcher, or Drop).
 *
 * retryCount 语义:由 [OutboxRepository.tryClaim](DAO ``markInFlightIfPending``)在
 * 每次 claim 时 +1, 由 [maxAttempts] 检查时读取。**只计真正调到 dispatcher 的 claim**:
 * epoch-abort 和 CancellationException 两条 abort-before-dispatch 路径都用
 * [OutboxRepository.revertClaimWithoutAttempt] 把这次 +1 抵消掉(否则 session 反复 flap
 * 或 WorkManager 反复 cancel 会让 retryCount 静默累积到 max_attempts, 用户毫不知情就被
 * 推到 FAILED)。
 *
 * [recoverStaleInFlight][PendingMutationDao.recoverStaleInFlight] 故意 NOT 抵消
 * retryCount——能滞留 5 min 的 IN_FLIGHT row 说明 dispatcher 已经被调过(可能服务端已经
 * 收到了 mutation),那次 claim 计入 retryCount 是正确的。
 */
class OutboxDrainEngine(
    private val outbox: OutboxRepository,
    dispatchers: Iterable<OutboxMutationDispatcher>,
    /**
     * codex P1 #7: dispatcher 的最大尝试总次数(含首次)。第 N 次仍 RetryableFailure 就
     * markFailed 让用户在 SyncStatusScreen 手动 retry/丢弃(retryCount 在用户 retry 时
     * 由 DAO 重置 0,获得完整新预算)。值选理由 / 命名约定见 [DEFAULT_MAX_ATTEMPTS]。
     */
    private val maxAttempts: Int = DEFAULT_MAX_ATTEMPTS,
    /**
     * Wall-clock source for the ADR-0042 §4.10 PENDING age-cap reaper (see
     * [OUTBOX_PENDING_AGE_CAP_MILLIS]). A ``() -> Long`` lambda — NOT a Clock /
     * Instant — keeps the engine Android- and java.time-free and makes the cap
     * trivially testable: a test injects a fixed clock and sets a row's
     * ``createdAt`` either side of ``now - cap``. Production uses the default
     * [System.currentTimeMillis].
     */
    private val now: () -> Long = System::currentTimeMillis,
) {
    init {
        // 防止 DI 或 env 误配置成 0/负——会让 attempts = retryCount + 1 >= 0/-N 永远
        // 成真, 第一次 dispatch 失败就立刻 FAILED, 整条队列退化成 "一次性尝试"。
        require(maxAttempts > 0) {
            "OutboxDrainEngine maxAttempts must be > 0, was $maxAttempts"
        }
    }

    private val registry: Map<PendingMutationType, OutboxMutationDispatcher> =
        dispatchers.associateBy { it.type }

    /**
     * Replay every currently-runnable row exactly once. Returns the
     * summary so the caller (worker / UI / tests) can decide whether
     * to re-enqueue itself.
     *
     * Sweeps stale IN_FLIGHT rows (left behind by a cancelled or
     * crashed worker) back to PENDING before dequeueing so the
     * same-target dedup doesn't permanently block siblings.
     * [codex round-2 P1#2] companion.
     */
    suspend fun drainOnce(): DrainSummary {
        // v9 → v10 one-time backfill: adopt any rows the schema migration left
        // with an empty binding into the current one before the binding-scoped
        // reads run, so pre-upgrade offline edits aren't stranded. No-op once
        // adopted / while unbound.
        outbox.adoptLegacyRowsForCurrentBinding()
        outbox.recoverStaleInFlight()
        // [ADR-0042 §4.10] PENDING age-cap reaper: terminally FAIL (never replay)
        // any row that has sat PENDING past OUTBOX_PENDING_AGE_CAP_MILLIS, BEFORE
        // we dequeue runnable work. A row older than the cap can no longer trust
        // its idempotency key (server retention has likely purged it), so a replay
        // would double-apply; flipping it to FAILED here means the row never
        // reaches a dispatcher and instead surfaces in the user's "manual retry /
        // drop" banner. Done before dequeueNextRunnable so the just-reaped (now
        // FAILED) rows are excluded from this very pass's batch.
        val reaped = outbox.reapExpiredPending(now())
        // [codex round-9 P1] session-boundary epoch: capture the
        // counter BEFORE dequeue. A binding transition between this snapshot
        // and the dispatch loop will bump the counter; the post-claim
        // check below will see it and abort the rest of the batch
        // before any in-memory row is sent under the new session.
        val capturedEpoch = outbox.currentSessionEpoch()
        val batch = outbox.dequeueNextRunnable()
        // Even with no runnable work, a reap mutated the DB — return a summary
        // carrying ``reaped`` (not the shared IDLE constant) so a reap-only pass
        // still reports anythingChanged to the scheduler / UI.
        if (batch.isEmpty()) return DrainSummary(attempted = 0, done = 0, conflicts = 0, failures = 0, reaped = reaped)

        var done = 0
        var conflicts = 0
        var failures = 0
        var retryable = 0
        var discarded = 0
        var unsupported = 0
        var raced = 0
        var aborted = 0
        for (row in batch) {
            val dispatcher = registry[row.type]
            if (dispatcher == null || row.type == PendingMutationType.Unknown) {
                // [codex finding P2#5] fix: rows with no registered
                // dispatcher used to stay PENDING forever, blocking
                // newer same-or-later rows behind them in the
                // ``ORDER BY createdAt`` window. Move them to FAILED
                // with a structured ``lastError`` so a UI affordance
                // can offer "upgrade the app, then manual retry" or
                // "drop". The user-visible behaviour is identical to
                // a 4xx that needs human action.
                outbox.markFailed(row.id, "no_dispatcher_registered:${row.type.wireValue}")
                unsupported++
                continue
            }
            // [codex finding P1#2] fix: atomic PENDING → IN_FLIGHT
            // claim. If another drain pass beat us to it, the
            // dispatcher MUST NOT be called.
            if (!outbox.tryClaim(row.id)) {
                raced++
                continue
            }
            // [codex round-10 P1] Hold the dispatch lease across
            // BOTH the epoch check AND the dispatcher.dispatch(row)
            // call. Without the lease, a binding transition that fires
            // AFTER the epoch check but BEFORE dispatch resolves
            // apiProvider() / OkHttp reads the token would let the
            // old row be sent under the NEW session. With the
            // lease:
            //   - the binding transition blocks until our dispatch returns,
            //   - credentials writes happen inside that locked transition,
            //   - so dispatcher.dispatch(row) always sees the
            //     credentials it was queued under.
            //
            // ``signalAbort = true`` returned from inside the
            // lease means "epoch check failed, abort the remainder
            // of the batch". We propagate that up after the lease
            // releases so the abort accounting reads the same
            // counters the dispatch result handlers updated.
            val signalAbort = outbox.withDispatchLease {
                // [codex round-9 P1] post-claim epoch check.
                // Binding transition bumps the epoch before credentials
                // change;
                // if the epoch changed between our snapshot and the
                // moment we acquired the lease, the row was loaded under
                // a stale binding and must not dispatch under whatever
                // session the user just bound. Abort the rest of the
                // batch.
                if (outbox.currentSessionEpoch() != capturedEpoch) {
                    // codex P2 #10: tryClaim 已经把 row 推到 IN_FLIGHT + retryCount++,
                    // 这里直接 return 会让它一直 IN_FLIGHT, 要等下次 drain 的
                    // recoverStaleInFlight(5min 阈值)兜底, 中间 same-target serial 卡住后续 row。
                    // 用 revertClaimWithoutAttempt 而不是 markRetryable, 抵消 tryClaim 的
                    // retryCount++: 这次根本没 dispatch, 不该算成一次"尝试"。否则 session
                    // 反复 flap 会让 retryCount 静默累积到 max_attempts 阈值, 用户毫不知情
                    // 就被推到 FAILED。lastError 不写——保留先前 markRetryable 留下的诊断
                    // (如 "server 503"), abort 只是窗口期事件不该淹没根因。
                    outbox.revertClaimWithoutAttempt(row.id)
                    return@withDispatchLease true
                }
                // [codex round-2 P1#2] fix: do NOT let runCatching
                // swallow CancellationException — that would let a
                // structured-concurrency cancel mark the row as
                // RetryableFailure mid-shutdown. Catch it
                // explicitly and roll the row back to PENDING in a
                // NonCancellable context so a fresh drain can
                // re-claim it after the worker restarts.
                //
                // PR review #3: 用 revertClaimWithoutAttempt 而不是 markRetryable, 跟
                // epoch-abort 对称——WorkManager OS-kill 也是 "dispatcher 没真正完成",
                // 不该算一次尝试消耗 max_attempts 配额。否则反复 cancel 会让 retryCount
                // 静默爬到 cap, 用户毫不知情就被推到 FAILED。
                val result = try {
                    dispatcher.dispatch(row)
                } catch (e: CancellationException) {
                    withContext(NonCancellable) {
                        outbox.revertClaimWithoutAttempt(row.id)
                    }
                    throw e
                } catch (e: Exception) {
                    // [codex round-5 P3] catch Exception, not
                    // Throwable — Error subclasses (OOM, Linkage,
                    // StackOverflow, VirtualMachineError) indicate
                    // JVM-level damage that the per-row retry
                    // policy can't recover from; let them propagate
                    // up to the worker so WorkManager's own restart
                    // semantics handle it. CancellationException is
                    // already taken by the catch above (it extends
                    // Exception, but the more-specific catch binds
                    // first).
                    DispatchResult.RetryableFailure(e.message ?: "dispatch threw")
                }
                when (result) {
                    is DispatchResult.Success -> {
                        outbox.markDone(row.id)
                        // [codex finding P1#1] fix: cascade the
                        // server's post-mutation token to same-
                        // target PENDING rows so the next chained
                        // mutation against this row doesn't replay
                        // with a now-stale snapshot.
                        val newToken = result.newRowVersion
                        if (newToken != null && newToken != 0L) {
                            outbox.cascadeFreshToken(row.targetId, newToken)
                        }
                        done++
                    }
                    is DispatchResult.Conflict -> {
                        outbox.markConflict(row.id, result.serverMessage)
                        conflicts++
                    }
                    is DispatchResult.RetryableFailure -> {
                        // codex P1 #7: tryClaim 把 retryCount 加了 1, row.retryCount 是
                        // dequeue 时(claim 前)的快照, attempts = row.retryCount + 1。超出
                        // maxAttempts 转 FAILED, lastError 带 attempt 计数和原始错误, UI
                        // 经 SyncStatusScreen 的 friendlyLastError 翻译成中文展示。
                        //
                        // PR review #5: displayedAttempts 用 coerceAtMost(maxAttempts) 防
                        // pre-PR 旧 row(retryCount 已经远超 cap)输出 "16/10" 这种 N>M 看
                        // 起来像 cap 漏掉的分数。语义层面 retryCount 仍是真实值, 只是 UI
                        // 显示 cap 住。
                        val attempts = row.retryCount + 1
                        if (attempts >= maxAttempts) {
                            val displayedAttempts = attempts.coerceAtMost(maxAttempts)
                            outbox.markFailed(
                                row.id,
                                "max_attempts_exceeded(${displayedAttempts}/${maxAttempts}): ${result.message}",
                            )
                            failures++
                        } else {
                            // 此前 finding P1#3 fix: keep the row in PENDING so the next
                            // drain tick picks it up. The retryCount was already bumped
                            // by tryClaim; the scheduler can apply back-off based on it.
                            outbox.markRetryable(row.id, result.message)
                            retryable++
                        }
                    }
                    is DispatchResult.Failure -> {
                        outbox.markFailed(row.id, result.message)
                        failures++
                    }
                    is DispatchResult.Discarded -> {
                        // Discarded rows are gone from the user's
                        // view — there's nothing for them to
                        // resolve. Mark DONE and let cleanup
                        // garbage-collect after retention.
                        outbox.markDone(row.id)
                        discarded++
                    }
                }
                false  // not aborting
            }
            if (signalAbort) {
                val processed = done + conflicts + failures + retryable +
                    discarded + unsupported + raced
                aborted = batch.size - processed
                break
            }
        }
        return DrainSummary(
            attempted = batch.size,
            done = done,
            conflicts = conflicts,
            failures = failures,
            retryable = retryable,
            discarded = discarded,
            unsupported = unsupported,
            raced = raced,
            aborted = aborted,
            reaped = reaped,
        )
    }
}

data class DrainSummary(
    val attempted: Int,
    val done: Int,
    val conflicts: Int,
    val failures: Int,
    /** Transient failure — row stayed PENDING for the next drain. */
    val retryable: Int = 0,
    val discarded: Int = 0,
    /** No dispatcher registered for the row's type → markFailed. */
    val unsupported: Int = 0,
    /** Atomic claim lost a race with a concurrent drain. */
    val raced: Int = 0,
    /**
     * [codex round-9 P1] rows in the batch that were skipped
     * because a session boundary ([OutboxRepository.withBindingTransition])
     * fired mid-drain. The in-memory copies were loaded under the
     * old binding, so the drain aborted the remaining batch.
     */
    val aborted: Int = 0,
    /**
     * [ADR-0042 §4.10] PENDING rows reaped to FAILED at the start of this pass
     * because they sat PENDING past [OUTBOX_PENDING_AGE_CAP_MILLIS] and could no
     * longer trust their idempotency key. These rows are NOT in [attempted] —
     * they were terminally failed before dequeue, never handed to a dispatcher.
     */
    val reaped: Int = 0,
) {
    /**
     * 任何一行真的改了 DB(状态、retryCount、lastError 等)就为 true。
     *
     * PR review #12: aborted 在 PR-C 之前是 no-op return(只设 abort signal,不动 DB),
     * 所以历史上不计入 anythingChanged。现在 aborted 路径调 [revertClaimWithoutAttempt]
     * 真改了 status + retryCount + attemptedAt, 必须计入, 否则观察 anythingChanged 的
     * caller 会错过 abort 引起的 DB 失效信号。raced 仍排除——它表示这条 row 被别的 drain
     * 抢了, 本 drain 没动它。
     *
     * [ADR-0042 §4.10] reaped 也计入: 它把 row PENDING→FAILED, 真改了 DB, 且需要 UI
     * 刷新 FAILED banner 让用户看到过期的改动。
     */
    val anythingChanged: Boolean
        get() = done > 0 || conflicts > 0 || failures > 0 ||
            retryable > 0 || discarded > 0 || unsupported > 0 || aborted > 0 ||
            reaped > 0

    companion object {
        val IDLE = DrainSummary(0, 0, 0, 0)
    }
}

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

    /** Fired after a SUCCESSFULLY replayed mutation whose kind changes the
     *  server-side inputs the budget advisor consumes
     *  ([ADVICE_INPUT_MUTATION_TYPES]). Wired in AppContainer to the advice
     *  cache — var with a no-op default per the onConfirmedCommitted
     *  precedent (constructor baseline). */
    var onAdviceInputReplaySucceeded: () -> Unit = {}

    private companion object {
        const val MAX_DRAIN_ITEMS = 100
        /** Mutation kinds whose replay moves the budget advisor's server-side
         *  inputs (_inputs_builder.py: confirmed-expense aggregates, income
         *  plans). Create/confirm/patch change confirmed-expense rows;
         *  income-plan update changes the income leg. Excluded on purpose:
         *  pending-side kinds (reject / OCR / recognize / not-duplicate /
         *  items-mismatch) never touch confirmed aggregates; splits only
         *  re-share an unchanged total; rules / aliases / goals are not
         *  inputs; recurring create/update now travel the outbox and change
         *  the fixed-expense leg. Monthly-budget saves also invalidate advice
         *  after their accepted receipt. ReplaceItems only rewrites
         *  ExpenseItem sub-lines
         *  (+ updated_at / items_sum_status) — the advisor aggregates
         *  Expense.category / amount_cents / month via confirmed_amount_query
         *  (monthly_report_service.py), never line items, so item replacement
         *  leaves every advisor aggregate byte-identical. */
        val ADVICE_INPUT_MUTATION_TYPES: Set<PendingMutationType> = setOf(
            PendingMutationType.ConfirmExpense,
            PendingMutationType.CreateExpense,
            PendingMutationType.CreateExpenseOffset,
            PendingMutationType.PatchExpense,
            PendingMutationType.CorrectExpense,
            PendingMutationType.UpdateIncomePlan,
            PendingMutationType.SaveMonthlyBudget,
            PendingMutationType.CreateRecurringItem,
            PendingMutationType.UpdateRecurringItem,
            PendingMutationType.SetRecurringOccurrencePayment,
            PendingMutationType.VoidExpenseOffset,
        )
    }

    /**
     * Replay at most 100 original rows, each once, continuing newly released
     * FIFO tails. The summary preserves unfinished work for the existing worker.
     *
     * Sweeps stale IN_FLIGHT rows (left behind by a cancelled or
     * crashed worker) back to PENDING before dequeueing so the
     * same-target dedup doesn't permanently block siblings.
     * [codex round-2 P1#2] companion.
     */
    suspend fun drainOnce(): DrainSummary {
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
        var summary = DrainSummary(0, 0, 0, 0, reaped = reaped)
        val visited = mutableSetOf<Long>()
        while (visited.size < MAX_DRAIN_ITEMS) {
            val batch = outbox.dequeueNextRunnable(
                limit = minOf(OutboxRepository.DEFAULT_DRAIN_BATCH, MAX_DRAIN_ITEMS - visited.size),
                excludedIds = visited.toList(),
            )
            if (batch.isEmpty()) {
                // A stale claim can become runnable after its retried predecessor settles.
                // Preserve a wakeup without attempting that same id twice in this pass.
                return summary.copy(continuationRequired = outbox.dequeueNextRunnable(limit = 1).isNotEmpty())
            }
            visited.addAll(batch.map { it.id })
            val result = drainBatch(batch, capturedEpoch)
            summary += result
            if (result.aborted > 0) return summary
        }
        return summary.copy(continuationRequired = outbox.dequeueNextRunnable(limit = 1).isNotEmpty())
    }

    private suspend fun drainBatch(batch: List<OutboxRow>, capturedEpoch: Long): DrainSummary {
        var summary = DrainSummary.IDLE
        for ((index, row) in batch.withIndex()) {
            val result = dispatchRow(row, capturedEpoch)
            summary += result
            if (result.aborted > 0) {
                return summary.copy(attempted = batch.size, aborted = batch.size - index)
            }
        }
        return summary
    }

    /** The original dispatch lease covers claim, binding proof, HTTP and its local result. */
    private suspend fun dispatchRow(row: OutboxRow, capturedEpoch: Long): DrainSummary {
        val dispatcher = registry[row.type]
        if (dispatcher == null || row.type == PendingMutationType.Unknown) {
            outbox.markFailed(row.id, "no_dispatcher_registered:${row.type.wireValue}")
            return DrainSummary(1, 0, 0, 0, unsupported = 1)
        }
        return outbox.withDispatchLease {
            // Recheck FIFO atomically. Stop cannot delete a claimed original before its send.
            if (!outbox.tryClaim(row.id)) return@withDispatchLease DrainSummary(1, 0, 0, 0, raced = 1)
            if (outbox.currentSessionEpoch() != capturedEpoch) {
                outbox.revertClaimWithoutAttempt(row.id)
                return@withDispatchLease DrainSummary(1, 0, 0, 0, aborted = 1)
            }
            settle(row, dispatchSafely(row, dispatcher))
        }
    }

    private suspend fun dispatchSafely(row: OutboxRow, dispatcher: OutboxMutationDispatcher): DispatchResult =
        try {
            dispatcher.dispatch(row)
        } catch (error: CancellationException) {
            withContext(NonCancellable) { outbox.revertClaimWithoutAttempt(row.id) }
            throw error
        } catch (error: Exception) {
            DispatchResult.RetryableFailure(error.message ?: "dispatch threw")
        }

    /** Only this result handler settles a claimed command; the immutable receipt shares its Done update. */
    private suspend fun settle(row: OutboxRow, result: DispatchResult): DrainSummary {
        val summary = DrainSummary(1, 0, 0, 0)
        return when (result) {
            is DispatchResult.Success -> {
                outbox.markDone(row.id, cacheRefreshVersion = result.cacheRefreshVersion, receiptJson = result.receiptJson)
                result.newRowVersion?.takeIf { it != 0L }?.let { outbox.cascadeFreshToken(row.targetId, it) }
                if (row.type in ADVICE_INPUT_MUTATION_TYPES) onAdviceInputReplaySucceeded()
                summary.copy(done = 1)
            }
            is DispatchResult.Conflict -> {
                outbox.markConflict(row.id, result.serverMessage)
                summary.copy(conflicts = 1)
            }
            is DispatchResult.RetryableFailure -> recordRetryable(row, result.message)
            is DispatchResult.Failure -> {
                outbox.markFailed(row.id, result.message, blocksFollowing = result.blocksFollowing)
                summary.copy(failures = 1)
            }
            is DispatchResult.Discarded -> {
                outbox.markDone(row.id)
                summary.copy(discarded = 1)
            }
        }
    }

    private suspend fun recordRetryable(row: OutboxRow, message: String): DrainSummary {
        val attempts = row.retryCount + 1
        return if (attempts >= maxAttempts) {
            val displayedAttempts = attempts.coerceAtMost(maxAttempts)
            outbox.markFailed(row.id, "max_attempts_exceeded(${displayedAttempts}/${maxAttempts}): $message")
            DrainSummary(1, 0, 0, 1)
        } else {
            outbox.markRetryable(row.id, message)
            DrainSummary(1, 0, 0, 0, retryable = 1)
        }
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
    /** The bounded pass left a runnable original for the existing worker's next attempt. */
    val continuationRequired: Boolean = false,
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

private operator fun DrainSummary.plus(other: DrainSummary) = DrainSummary(
    attempted = attempted + other.attempted, done = done + other.done,
    conflicts = conflicts + other.conflicts, failures = failures + other.failures,
    retryable = retryable + other.retryable, discarded = discarded + other.discarded,
    unsupported = unsupported + other.unsupported, raced = raced + other.raced,
    aborted = aborted + other.aborted, reaped = reaped + other.reaped,
    continuationRequired = continuationRequired || other.continuationRequired,
)

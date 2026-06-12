package com.ticketbox.notification.recurring

import com.ticketbox.domain.model.RecurringItem
import java.time.LocalDate

/**
 * ADR-0046 测试替身（纯 JVM，本模块无 Robolectric，SharedPreferences / WorkManager 取不到真实例）。
 *
 * [InMemoryRecurringReminderStore] 用 Map 实现 [RecurringReminderStore] 契约，prune 复用生产侧
 * 同一个纯函数 [recurringReminderKeyExpectedDate]，故它与 [SharedPrefsRecurringReminderStore]
 * 的 prune 语义同源——StoreTest 对它的断言即对该共享逻辑的断言。
 */
class InMemoryRecurringReminderStore(
    initial: Set<String> = emptySet(),
) : RecurringReminderStore {
    private val sent = LinkedHashSet(initial)
    val keys: Set<String> get() = sent.toSet()

    override fun wasSent(key: String): Boolean = sent.contains(key)

    override fun markSent(key: String) {
        sent.add(key)
    }

    override fun prune(cutoff: LocalDate) {
        sent.removeAll { key ->
            val expectedDate = recurringReminderKeyExpectedDate(key) ?: return@removeAll false
            expectedDate.isBefore(cutoff)
        }
    }
}

/** 可编程 source：返回固定 [Result]，记录调用次数（验证「开关关 → 不拉 source」）。 */
class FakeRecurringReminderSource(
    private val result: Result<List<RecurringItem>>,
) : RecurringReminderSource {
    var calls = 0
        private set

    override suspend fun activeItems(): Result<List<RecurringItem>> {
        calls++
        return result
    }

    companion object {
        fun of(vararg items: RecurringItem) = FakeRecurringReminderSource(Result.success(items.toList()))
        fun failing(error: Throwable) = FakeRecurringReminderSource(Result.failure(error))
    }
}

/**
 * 可编程 dispatcher：按 decision.key 返回预设 outcome（默认 SENT），记录每次 dispatch 的 key。
 * 用于钉「SENT 才 markSent」「skipped 不 markSent」「已提醒不再 dispatch」。
 */
class FakeRecurringReminderDispatcher(
    private val outcomeFor: (RecurringReminderDecision) -> RecurringReminderDispatchOutcome = {
        RecurringReminderDispatchOutcome.SENT
    },
) : RecurringReminderDispatcher {
    val dispatchedKeys = mutableListOf<String>()

    override fun dispatch(decision: RecurringReminderDecision): RecurringReminderDispatchOutcome {
        dispatchedKeys.add(decision.key)
        return outcomeFor(decision)
    }
}

/** EngineTest / StoreTest 共用的 RecurringItem 工厂（默认 active + 窗口内）。 */
fun recurringItemFixture(
    publicId: String = "rec-1",
    ledgerId: String = "ledger-a",
    merchant: String = "房租",
    status: String = "active",
    nextExpectedDate: String? = "2026-06-12",
): RecurringItem = RecurringItem(
    publicId = publicId,
    ledgerId = ledgerId,
    merchant = merchant,
    merchantKey = merchant.lowercase(),
    frequency = "monthly",
    baselineAmountCents = 9900,
    lastAmountCents = 9900,
    occurrenceCount = 3,
    lastSeenAt = "2026-05-01T00:00:00Z",
    nextExpectedDate = nextExpectedDate,
    status = status,
    confidence = "high",
    source = "candidate",
    anomalyStatus = "normal",
    currentMonthAmountCents = null,
    historicalAverageAmountCents = null,
    amountDeltaPercent = null,
    createdAt = "2026-05-01T00:00:00Z",
    updatedAt = "2026-05-01T00:00:00Z",
    rowVersion = 1L,
    pausedAt = null,
    archivedAt = null,
)

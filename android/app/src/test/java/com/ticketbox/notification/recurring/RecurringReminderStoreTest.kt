package com.ticketbox.notification.recurring

import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0046 Slice 3：[RecurringReminderStore] 去重契约（Confirmation「Store tests」照单）。
 *
 * 用 [InMemoryRecurringReminderStore] 钉契约——它的 prune 复用生产同一纯函数
 * [recurringReminderKeyExpectedDate]，故对它的断言即对 [SharedPrefsRecurringReminderStore]
 * 共享 prune 逻辑的断言（本模块无 Robolectric，真 SharedPreferences 取不到）。
 * key 一律用 [recurringReminderSentKey] 生成，与策略层同源。
 */
class RecurringReminderStoreTest {

    private val date = LocalDate.parse("2026-06-12")

    private fun key(
        ledgerId: String = "ledger-a",
        itemPublicId: String = "rec-1",
        expectedDate: LocalDate = date,
        kind: RecurringReminderKind = RecurringReminderKind.DUE_SOON,
    ): String = recurringReminderSentKey(ledgerId, itemPublicId, expectedDate, kind)

    @Test
    fun markedKeyIsRemembered() {
        val store = InMemoryRecurringReminderStore()
        val k = key()
        assertFalse(store.wasSent(k))
        store.markSent(k)
        assertTrue(store.wasSent(k))
    }

    @Test
    fun markSentIsIdempotentForSameKey() {
        // 同一 key 标两次仍只「已提醒一次」——wasSent 恒 true，不爆条目。
        val store = InMemoryRecurringReminderStore()
        val k = key()
        store.markSent(k)
        store.markSent(k)
        assertEquals(setOf(k), store.keys)
    }

    @Test
    fun differentLedgerDoesNotCollide() {
        val store = InMemoryRecurringReminderStore()
        store.markSent(key(ledgerId = "ledger-a"))
        assertFalse(store.wasSent(key(ledgerId = "ledger-b")))
    }

    @Test
    fun differentItemDoesNotCollide() {
        val store = InMemoryRecurringReminderStore()
        store.markSent(key(itemPublicId = "rec-1"))
        assertFalse(store.wasSent(key(itemPublicId = "rec-2")))
    }

    @Test
    fun differentExpectedDateCanFireAgain() {
        // 下一周期换了 expectedDate → 视为新提醒（去重不跨周期粘住）。
        val store = InMemoryRecurringReminderStore()
        store.markSent(key(expectedDate = LocalDate.parse("2026-06-12")))
        assertFalse(store.wasSent(key(expectedDate = LocalDate.parse("2026-07-12"))))
    }

    @Test
    fun dueSoonAndOverdueAreDistinctKeys() {
        // 同 item 同 expectedDate，到期前提醒一次 + 逾期再提醒一次，互不抑制。
        val store = InMemoryRecurringReminderStore()
        store.markSent(key(kind = RecurringReminderKind.DUE_SOON))
        assertFalse(store.wasSent(key(kind = RecurringReminderKind.OVERDUE)))
    }

    @Test
    fun pruneDropsOldKeysButKeepsFreshAndAtCutoffKeys() {
        // cutoff=2026-06-01：严格早于它的 expectedDate key 删除；当天（== cutoff，isBefore 严格小于
        // → 保留）和之后的保留——证明 prune 不会清掉「同一 expectedDate 仍可能被检查」的刚写入 key
        // 及恰在 cutoff 当天的 key（Contract 5 边界）。
        val oldKey = key(expectedDate = LocalDate.parse("2026-01-15"))
        val atCutoff = key(expectedDate = LocalDate.parse("2026-06-01"))
        val freshKey = key(expectedDate = LocalDate.parse("2026-06-12"))
        val store = InMemoryRecurringReminderStore(setOf(oldKey, atCutoff, freshKey))
        store.prune(cutoff = LocalDate.parse("2026-06-01"))
        assertFalse(store.wasSent(oldKey))
        assertTrue(store.wasSent(atCutoff))
        assertTrue(store.wasSent(freshKey))
    }

    @Test
    fun pruneLeavesUnparsableKeysUntouched() {
        // 格式异常 key 保守保留，不误删（不解析出日期 → 跳过）。
        val store = InMemoryRecurringReminderStore(setOf("garbage", "v1:only:three"))
        store.prune(cutoff = LocalDate.parse("2999-01-01"))
        assertTrue(store.wasSent("garbage"))
        assertTrue(store.wasSent("v1:only:three"))
    }

    @Test
    fun keyExpectedDateParsesSecondToLastSegment() {
        // 纯函数直测：kind 恒最后段、expectedDate 恒倒数第二段，对含冒号 id 也稳健。
        assertEquals(
            LocalDate.parse("2026-06-12"),
            recurringReminderKeyExpectedDate("v1:ledger-a:rec-1:2026-06-12:OVERDUE"),
        )
        // 段数不足 → null。
        assertNull(recurringReminderKeyExpectedDate("v1:ledger:item"))
        // 倒数第二段不是日期 → null。
        assertNull(recurringReminderKeyExpectedDate("v1:ledger:item:not-date:DUE_SOON"))
    }
}

package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * 连续审阅（快补 sheet「保存并下一笔」/「跳过」/「还剩 N 条」/「失败留守」）VM 行为测试。
 *
 * 这是 /web 批 10 抽屉复核流水线的 Android 镜像：批量过堆积的待确认票时，快补 sheet
 * 存完一笔自动载入下一条仍缺同字段的票、不关 sheet，队列耗尽才关。四个核心行为各钉一条：
 * 存后推进 / 跳过推进 / 耗尽关闭 / 失败留守。序列与「还剩 N 条」口径见 [PendingReviewQueue]，
 * 纯函数另有 [PendingReviewQueueTest] 直测。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelReviewQueueTest : PendingViewModelReviewTestBase() {

    /** 三张都缺商家的待确认票，按列表顺序 A→B→C。 */
    private fun threeMissingMerchant() = listOf(
        expense(id = 1L, merchant = null),
        expense(id = 2L, merchant = null),
        expense(id = 3L, merchant = null),
    )

    @Test
    fun saveQuickMerchantAdvancesToNextMissingTicketWithoutClosing() = review {
        val fake = FakeReviewActions(pending = threeMissingMerchant())
        // 保存后该票补上商家（不再缺），其余两张仍缺。
        fake.updateResponder = { id, draft -> Result.success(expense(id = id, merchant = draft.merchant)) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        // 从列表点开 A 的快补 sheet：开启一轮连续审阅，还剩 3 条（含当前 A）。
        vm.openQuickMerchant(vm.uiState.value.items.first { it.id == 1L })
        advanceUntilIdle()
        assertEquals(3, vm.uiState.value.reviewRemaining)

        // 存 A 的商家 → 自动载入下一条仍缺商家的票 B，sheet 不关，计数降到 2。
        vm.saveQuickMerchant(1L, "星巴克")
        advanceUntilIdle()

        val sheet = vm.uiState.value.activeSheet
        assertTrue(sheet is PendingSheet.QuickMerchant, "存完应推进到下一条快补 sheet，而非关闭")
        assertEquals(2L, sheet.expense.id)
        assertEquals(2, vm.uiState.value.reviewRemaining)
        // 推进时清掉成功提示，sheet 内状态行只在失败时留守。
        assertEquals(null, vm.uiState.value.message)
        assertEquals(1, fake.updateCalls)
    }

    @Test
    fun skipReviewFieldAdvancesToNextWithoutSavingOrMutating() = review {
        val fake = FakeReviewActions(pending = threeMissingMerchant())
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openQuickMerchant(vm.uiState.value.items.first { it.id == 1L })
        advanceUntilIdle()

        // 跳过 A：不保存、不触网，载入下一条仍缺商家的票 B。
        vm.skipReviewField()
        advanceUntilIdle()

        val sheet = vm.uiState.value.activeSheet
        assertTrue(sheet is PendingSheet.QuickMerchant)
        assertEquals(2L, sheet.expense.id)
        // 跳过把 A 排除出本轮 → 还剩 B、C 两条。
        assertEquals(2, vm.uiState.value.reviewRemaining)
        // 跳过不调用任何 repository 写操作，A 仍留在 pending 列表。
        assertEquals(0, fake.updateCalls)
        assertEquals(0, fake.confirmCalls)
        assertEquals(0, fake.rejectCalls)
        assertTrue(vm.uiState.value.items.any { it.id == 1L }, "跳过的票不出队，仍在列表里")
    }

    @Test
    fun skippingLastTicketExhaustsQueueAndClosesSheet() = review {
        // 只有一张缺商家的票：跳过它 = 队列耗尽。
        val fake = FakeReviewActions(pending = listOf(expense(id = 1L, merchant = null)))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openQuickMerchant(vm.uiState.value.items.first { it.id == 1L })
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.reviewRemaining)

        vm.skipReviewField()
        advanceUntilIdle()

        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals(0, vm.uiState.value.reviewRemaining)
        assertEquals(UiText.res(R.string.pending_review_queue_skip_last), vm.uiState.value.message)
        assertEquals(0, fake.updateCalls)
    }

    @Test
    fun savingLastTicketExhaustsQueueAndClosesSheet() = review {
        val fake = FakeReviewActions(pending = listOf(expense(id = 1L, merchant = null)))
        fake.updateResponder = { id, draft -> Result.success(expense(id = id, merchant = draft.merchant)) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openQuickMerchant(vm.uiState.value.items.first { it.id == 1L })
        advanceUntilIdle()

        // 存唯一一张缺商家的票 → 没有下一条 → sheet 关闭，保留成功文案。
        vm.saveQuickMerchant(1L, "美团外卖")
        advanceUntilIdle()

        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals(0, vm.uiState.value.reviewRemaining)
        assertEquals(UiText.res(R.string.pending_review_merchant_updated), vm.uiState.value.message)
    }

    @Test
    fun saveFailureStaysOnCurrentTicketWithErrorAndDoesNotAdvance() = review {
        val fake = FakeReviewActions(pending = threeMissingMerchant())
        fake.updateResponder = { _, _ -> Result.failure(RuntimeException("网络忙")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openQuickMerchant(vm.uiState.value.items.first { it.id == 1L })
        advanceUntilIdle()

        vm.saveQuickMerchant(1L, "星巴克")
        advanceUntilIdle()

        // 失败不跳转：仍停在 A 的 sheet，错误反馈进 message（sheet 内可见），计数不变。
        val sheet = vm.uiState.value.activeSheet
        assertTrue(sheet is PendingSheet.QuickMerchant)
        assertEquals(1L, sheet.expense.id)
        assertEquals(UiText.raw("网络忙"), vm.uiState.value.message)
        assertEquals(3, vm.uiState.value.reviewRemaining)
        assertTrue(vm.uiState.value.actionInProgressIds.isEmpty())
    }
}

package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * v0.4-alpha4 M1：PendingViewModel quick-edit / 金额 review action 单元测试。
 *
 * 覆盖 QuickCategory / QuickMerchant / MissingAmount（saveAmountDraft /
 * saveAmountAndConfirm）三条「单条编辑」action 的核心契约。批量确认、
 * 重复处理、ADR-0038 撤销 banner、只读 / sheet / reducer / ledger-change
 * 等场景拆到同包姊妹类（见 PendingViewModelReviewTestSupport.kt）。
 *
 * 共享脚手架（review 计时器卫生 helper、expense / image 样本构造器、
 * FakeReviewActions）见 [PendingViewModelReviewTestBase] /
 * [FakeReviewActions]。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelReviewActionsTest : PendingViewModelReviewTestBase() {

    @Test
    fun saveQuickCategorySendsTrimmedDraftAndUpdatesItem() = review {
        val target = expense(id = 1L, category = "未分类")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { id, draft ->
            assertEquals(1L, id)
            assertEquals("交通", draft.category)
            assertNull(draft.amountCents)
            assertNull(draft.merchant)
            Result.success(target.copy(category = "交通"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickCategory(target.id, "  交通  ")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("交通", state.items.single().category)
        assertEquals(PendingSheet.None, state.activeSheet)
        assertEquals(UiText.res(R.string.pending_review_category_updated), state.message)
        assertTrue(state.actionInProgressIds.isEmpty())
        assertEquals(1, fake.updateCalls)
    }

    @Test
    fun saveQuickCategoryShowsErrorOnFailure() = review {
        val target = expense(id = 2L, category = "未分类")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, _ -> Result.failure(RuntimeException("网络忙")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickCategory(target.id, "餐饮")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("未分类", state.items.single().category)
        assertEquals(UiText.raw("网络忙"), state.message)
        assertTrue(state.actionInProgressIds.isEmpty())
    }

    @Test
    fun saveQuickMerchantRejectsBlankAndDoesNotCallRepository() = review {
        val target = expense(id = 3L, merchant = null)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickMerchant(target.id, "   ")
        advanceUntilIdle()

        assertEquals(0, fake.updateCalls)
        assertEquals(UiText.res(R.string.pending_review_merchant_blank), vm.uiState.value.message)
    }

    @Test
    fun saveQuickMerchantSubmitsTrimmedValue() = review {
        val target = expense(id = 4L, merchant = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals("星巴克", draft.merchant)
            Result.success(target.copy(merchant = "星巴克"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickMerchant(target.id, "  星巴克 ")
        advanceUntilIdle()

        assertEquals("星巴克", vm.uiState.value.items.single().merchant)
        assertEquals(UiText.res(R.string.pending_review_merchant_updated), vm.uiState.value.message)
    }

    @Test
    fun saveAmountDraftRejectsZeroAndNegative() = review {
        val target = expense(id = 5L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountDraft(target.id, 0L)
        advanceUntilIdle()
        assertEquals(0, fake.updateCalls)
        assertEquals(UiText.res(R.string.pending_review_amount_not_positive), vm.uiState.value.message)

        vm.saveAmountDraft(target.id, -100L)
        advanceUntilIdle()
        assertEquals(0, fake.updateCalls)
    }

    @Test
    fun saveAmountDraftPatchesWithoutConfirm() = review {
        val target = expense(id = 6L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals(null, draft.amountCents)
            assertEquals(CurrencyCode.CNY, draft.originalCurrencyCode)
            assertEquals(1234L, draft.originalAmountMinor)
            Result.success(target.copy(amountCents = 1234L, originalAmountMinor = 1234L))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountDraft(target.id, 1234L)
        advanceUntilIdle()

        assertEquals(1234L, vm.uiState.value.items.single().amountCents)
        assertEquals(0, fake.confirmCalls)
        assertEquals(UiText.res(R.string.pending_review_amount_saved), vm.uiState.value.message)
    }

    @Test
    fun saveAmountDraftPatchesOriginalForeignAmount() = review {
        val target = expense(
            id = 16L,
            amountCents = null,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = null,
        )
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals(null, draft.amountCents)
            assertEquals(CurrencyCode.USD, draft.originalCurrencyCode)
            assertEquals(12345L, draft.originalAmountMinor)
            Result.success(target.copy(originalAmountMinor = 12345L))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountDraft(target.id, 12345L)
        advanceUntilIdle()

        assertEquals(12345L, vm.uiState.value.items.single().originalAmountMinor)
    }

    @Test
    fun saveAmountAndConfirmRunsUpdateThenConfirm() = review {
        val target = expense(id = 7L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals(null, draft.amountCents)
            assertEquals(4200L, draft.originalAmountMinor)
            Result.success(target.copy(amountCents = 4200L, originalAmountMinor = 4200L))
        }
        fake.confirmResponder = { Result.success(target.copy(amountCents = 4200L, status = "confirmed")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountAndConfirm(target.id, 4200L)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.items.isEmpty(), "已确认条目应该从 pending 列表中移除")
        assertEquals(UiText.res(R.string.pending_review_amount_saved_confirmed), state.message)
        assertEquals(1, fake.updateCalls)
        assertEquals(1, fake.confirmCalls)
    }

    @Test
    fun saveAmountAndConfirmKeepsItemWhenUpdateFails() = review {
        val target = expense(id = 8L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, _ -> Result.failure(RuntimeException("amount_required")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountAndConfirm(target.id, 5000L)
        advanceUntilIdle()

        assertEquals(1, vm.uiState.value.items.size)
        assertEquals(0, fake.confirmCalls)
        assertEquals(UiText.raw("amount_required"), vm.uiState.value.message)
    }
}

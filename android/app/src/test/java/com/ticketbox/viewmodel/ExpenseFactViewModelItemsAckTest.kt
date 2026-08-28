package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.ItemsAckOutcome
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

/** A1: 事实页「原小票如此」——动作可达、调用正确的 offline-capable Owner、四态诚实。 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelItemsAckTest : ExpenseFactViewModelTestBase() {

    private fun mismatchedItems() = ExpenseItems(
        expenseId = 7L,
        parentAmountCents = 1000L,
        itemsTotalAmountCents = 700L,
        mismatchCents = 300L,
        itemsSumStatus = ItemsSumStatus.MISMATCH_KNOWN,
        items = emptyList(),
        parentRowVersion = 1L,
    )

    @Test
    fun `mismatch known action reaches the owner and applies the server snapshot`() = edit { fake ->
        fake.itemsResult = Result.success(mismatchedItems())
        val vm = viewModel(fake)

        vm.acknowledgeItemsMismatch()
        advanceUntilIdle()

        assertEquals(1, fake.ackCalls, "命令必须到达 acknowledgeItemsMismatchAllowingOffline owner")
        assertEquals(7L, fake.lastAckExpense?.id)
        assertEquals(
            ItemsSumStatus.MISMATCH_KNOWN,
            fake.lastAckItems?.itemsSumStatus,
            "owner 收到的是确认前的当前明细快照",
        )
        assertEquals(ItemsSumStatus.MISMATCH_ACKNOWLEDGED, vm.uiState.value.expenseItems?.itemsSumStatus)
        assertEquals(2L, vm.uiState.value.expense?.rowVersion, "Synced 后父行版本采用服务端快照")
        assertEquals(R.string.expense_edit_items_ack_synced, (vm.uiState.value.message as? UiText.Res)?.id)
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
    }

    @Test
    fun `offline queued keeps the optimistic acknowledged projection and says so`() = edit { fake ->
        fake.itemsResult = Result.success(mismatchedItems())
        fake.ackResult = { _, items ->
            Result.success(
                ItemsAckOutcome.Queued(items.copy(itemsSumStatus = ItemsSumStatus.MISMATCH_ACKNOWLEDGED)),
            )
        }
        val vm = viewModel(fake)

        vm.acknowledgeItemsMismatch()
        advanceUntilIdle()

        assertEquals(1, fake.ackCalls)
        assertEquals(ItemsSumStatus.MISMATCH_ACKNOWLEDGED, vm.uiState.value.expenseItems?.itemsSumStatus)
        assertEquals(1L, vm.uiState.value.expense?.rowVersion, "Queued 保留当前 token，不伪造版本")
        assertEquals(R.string.expense_edit_items_ack_offline_queued, (vm.uiState.value.message as? UiText.Res)?.id)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
    }

    @Test
    fun `failure keeps the mismatch actionable and reports honestly`() = edit { fake ->
        fake.itemsResult = Result.success(mismatchedItems())
        fake.ackResult = { _, _ ->
            Result.failure(RepositoryException(errorCode = "network_unreachable", message = "boom"))
        }
        val vm = viewModel(fake)

        vm.acknowledgeItemsMismatch()
        advanceUntilIdle()

        assertEquals(1, fake.ackCalls)
        assertEquals(
            ItemsSumStatus.MISMATCH_KNOWN,
            vm.uiState.value.expenseItems?.itemsSumStatus,
            "失败不得伪造已确认",
        )
        assertFalse(vm.uiState.value.itemsLoading)
        // 未知错误码 + 有 message：原样透出（UiText.Raw），不伪装成固定文案。
        assertEquals("boom", (vm.uiState.value.message as? UiText.Raw)?.text)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }

    @Test
    fun `items not loaded never reaches the owner`() = edit { fake ->
        fake.itemsResult = Result.failure(RepositoryException(errorCode = "network_unreachable", message = "down"))
        val vm = viewModel(fake)
        assertNull(vm.uiState.value.expenseItems)

        vm.acknowledgeItemsMismatch()
        advanceUntilIdle()

        assertEquals(0, fake.ackCalls)
        assertEquals(R.string.expense_edit_items_not_loaded_tap, (vm.uiState.value.message as? UiText.Res)?.id)
    }

    @Test
    fun `read only ledger never reaches the owner`() = edit { fake ->
        fake.canModifyLedgerFlag = false
        fake.itemsResult = Result.success(mismatchedItems())
        val vm = viewModel(fake)

        vm.acknowledgeItemsMismatch()
        advanceUntilIdle()

        assertEquals(0, fake.ackCalls)
        assertEquals(R.string.expense_correction_readonly_blocked, (vm.uiState.value.message as? UiText.Res)?.id)
    }
}

package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

/** A1: confirmed bill-split consumer moved from the legacy editor to the fact owner. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelBillSplitTest : ExpenseFactViewModelTestBase() {
    @Test
    fun `sent invitations are filtered to this fact`() = edit { fake ->
        fake.billSplitSentResult = {
            Result.success(
                listOf(
                    fake.sentInvite(publicId = "mine", senderExpenseId = 7L),
                    fake.sentInvite(publicId = "other", senderExpenseId = 99L),
                ),
            )
        }

        val vm = viewModel(fake)

        assertEquals(listOf("mine"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertEquals(BillSplitSentLoadState.Loaded, vm.uiState.value.billSplitSentLoadState)
    }

    @Test
    fun `failed refresh keeps the last sent projection`() = edit { fake ->
        var failNextLoad = false
        fake.billSplitSentResult = {
            if (failNextLoad) {
                Result.failure(RuntimeException("boom"))
            } else {
                Result.success(listOf(fake.sentInvite(publicId = "mine")))
            }
        }
        val vm = viewModel(fake)

        failNextLoad = true
        vm.loadBillSplitSent()
        advanceUntilIdle()

        assertEquals(listOf("mine"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertNotNull(vm.uiState.value.billSplitMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitMessageTone)
        assertFalse(vm.uiState.value.billSplitLoading)
        assertEquals(BillSplitSentLoadState.Failed, vm.uiState.value.billSplitSentLoadState)
    }

    @Test
    fun `send uses member account id and refreshes the fact projection`() = edit { fake ->
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        fake.createBillSplitResult = { _, _, _ -> Result.success(fake.sentInvite(publicId = "new")) }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("4.00")
        val fetchesBeforeSend = fake.fetchBillSplitSentCalls
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        assertEquals(1, fake.createBillSplitCalls)
        assertEquals(Triple(7L, 333L, 400L), fake.lastCreateBillSplitArgs)
        assertFalse(vm.uiState.value.billSplitInviteSheetOpen)
        assertEquals(UiText.res(R.string.expense_edit_bill_split_sent), vm.uiState.value.message)
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
        assertEquals(fetchesBeforeSend + 1, fake.fetchBillSplitSentCalls)
    }

    @Test
    fun `successful send stays visible when refresh fails`() = edit { fake ->
        var failNextLoad = false
        fake.billSplitSentResult = {
            if (failNextLoad) Result.failure(RuntimeException("refresh failed")) else Result.success(emptyList())
        }
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        fake.createBillSplitResult = { _, _, _ -> Result.success(fake.sentInvite(publicId = "new")) }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("4.00")
        failNextLoad = true
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        assertEquals(listOf("new"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertEquals(BillSplitStatusValues.INVITED, vm.uiState.value.billSplitSent.single().status)
        assertNotNull(vm.uiState.value.billSplitMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitMessageTone)
        assertFalse(vm.uiState.value.billSplitInviteSheetOpen)
    }

    @Test
    fun `amount over known remaining never reaches the repository`() = edit { fake ->
        fake.billSplitSentResult = {
            Result.success(listOf(fake.sentInvite(publicId = "active", amountCents = 800L)))
        }
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("5.00")
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        assertEquals(0, fake.createBillSplitCalls)
        assertNotNull(vm.uiState.value.billSplitInviteMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitInviteMessageTone)
        assertTrue(vm.uiState.value.billSplitInviteSheetOpen)
    }

    @Test
    fun `unknown sent projection defers remaining validation to the server`() = edit { fake ->
        fake.billSplitSentResult = { Result.failure(RuntimeException("sent list unavailable")) }
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        fake.createBillSplitResult = { _, _, _ -> Result.success(fake.sentInvite(publicId = "server-checked")) }
        val vm = viewModel(fake)
        assertEquals(BillSplitSentLoadState.Failed, vm.uiState.value.billSplitSentLoadState)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("50.00")
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        assertEquals(1, fake.createBillSplitCalls)
        assertEquals(Triple(7L, 333L, 5000L), fake.lastCreateBillSplitArgs)
    }

    @Test
    fun `online send failure stays in the sheet`() = edit { fake ->
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        fake.createBillSplitResult = { _, _, _ -> Result.failure(RuntimeException("boom")) }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("4.00")
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        assertEquals(1, fake.createBillSplitCalls)
        assertNotNull(vm.uiState.value.billSplitInviteMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitInviteMessageTone)
        assertTrue(vm.uiState.value.billSplitInviteSheetOpen)
        assertNull(vm.uiState.value.message)
    }

    @Test
    fun `invite members exclude self and disabled accounts`() = edit { fake ->
        fake.splitMembersResult = {
            Result.success(
                listOf(
                    fake.member(memberId = 1L, isSelf = true),
                    fake.member(memberId = 2L, disabledAt = "2025-01-01T00:00:00Z"),
                    fake.member(memberId = 3L, displayName = "可选家人"),
                ),
            )
        }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()

        assertEquals(listOf(3L), vm.uiState.value.billSplitInviteMembers.map { it.memberId })
    }

    @Test
    fun `unsupported currency blocks send before the repository`() = edit { fake ->
        fake.baseExpense = fake.baseExpense.copy(homeCurrencyCode = "XXX")
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("4.00")
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        assertEquals(0, fake.createBillSplitCalls)
        assertNotNull(vm.uiState.value.billSplitInviteMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitInviteMessageTone)
    }

    @Test
    fun `cancelled status stays visible when refresh fails`() = edit { fake ->
        var failNextLoad = false
        fake.billSplitSentResult = {
            if (failNextLoad) {
                Result.failure(RuntimeException("refresh failed"))
            } else {
                Result.success(listOf(fake.sentInvite(publicId = "mine")))
            }
        }
        fake.cancelBillSplitResult = { publicId ->
            Result.success(fake.sentInvite(publicId = publicId, status = BillSplitStatusValues.CANCELLED))
        }
        val vm = viewModel(fake)

        failNextLoad = true
        vm.cancelBillSplitInvitation("mine")
        advanceUntilIdle()

        assertEquals(listOf("mine"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertEquals(BillSplitStatusValues.CANCELLED, vm.uiState.value.billSplitSent.single().status)
        assertNotNull(vm.uiState.value.billSplitMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitMessageTone)
        assertFalse(vm.uiState.value.billSplitLoading)
        assertEquals(BillSplitSentLoadState.Failed, vm.uiState.value.billSplitSentLoadState)
    }
}

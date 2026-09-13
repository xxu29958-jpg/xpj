package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.TestScope

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
    fun `save keeps the chosen recipient without claiming server delivery`() = edit { fake ->
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        fake.createBillSplitResult = { _, _, _ -> Result.success(11L) }
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
        assertEquals(UiText.res(R.string.bill_split_submission_saved), vm.uiState.value.message)
        assertEquals(MessageTone.Neutral, vm.uiState.value.messageTone)
        assertEquals(fetchesBeforeSend, fake.fetchBillSplitSentCalls)
    }

    @Test
    fun `durable delivery receipt stays visible when the sent list refresh fails`() = edit { fake ->
        var failNextLoad = false
        fake.billSplitSentResult = {
            if (failNextLoad) Result.failure(RuntimeException("refresh failed")) else Result.success(emptyList())
        }
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 3L, accountId = 333L)))
        }
        fake.createBillSplitResult = { _, _, _ -> Result.success(11L) }
        val vm = viewModel(fake)

        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        vm.selectBillSplitInviteMember(3L)
        vm.updateBillSplitInviteAmount("4.00")
        failNextLoad = true
        vm.sendBillSplitInvite()
        advanceUntilIdle()

        val binding = requireNotNull(vm.uiState.value.correctionAccess).binding
        val row = com.ticketbox.data.repository.OutboxRow(11L, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            com.ticketbox.data.local.PendingMutationType.CreateBillSplitInvitation, "expense:7", "original-payload", 1L,
            PendingMutationStatus.Done, 1, null, "2026-09-06T00:00:00Z", null, "2026-09-06T00:01:00Z", "original-key")
        fake.billSplitSubmissions.value = listOf(com.ticketbox.data.repository.PendingBillSplitCreation(row, null,
            fake.sentInvite(publicId = "new")))
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
        fake.createBillSplitResult = { _, _, _ -> Result.success(11L) }
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
    fun `local publication failure preserves the form`() = edit { fake ->
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
        vm.cancelBillSplitInvitation(requireNotNull(vm.uiState.value.correctionAccess).binding, "mine")
        advanceUntilIdle()

        assertEquals(listOf("mine"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertEquals(BillSplitStatusValues.CANCELLED, vm.uiState.value.billSplitSent.single().status)
        assertNotNull(vm.uiState.value.billSplitMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.billSplitMessageTone)
        assertFalse(vm.uiState.value.billSplitLoading)
        assertEquals(BillSplitSentLoadState.Failed, vm.uiState.value.billSplitSentLoadState)
    }

    @Test
    fun `new invitations wait for correction refresh while existing invitations remain cancellable`() = edit { fake ->
        assertInvitationActionsRespectCorrection(this, fake)
    }

}

@OptIn(ExperimentalCoroutinesApi::class)
private suspend fun assertInvitationActionsRespectCorrection(scope: TestScope, fake: FakeExpenseFactActions) {
    val cancelled = mutableListOf<String>()
    prepareCorrectionInvitations(fake, cancelled)
    val refresh = CompletableDeferred<Result<Expense>>()
    var holdRefresh = false
    val repository = object : ExpenseFactActions by fake {
        override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> = Result.failure(RepositoryException("Cache unavailable"))
        override suspend fun fetchExpense(id: Long): Result<Expense> =
            if (holdRefresh) refresh.await() else fake.fetchExpense(id)
    }
    val vm = ExpenseFactViewModel(expenseId = fake.baseExpense.id, repository = repository)
    scope.advanceUntilIdle()
    vm.openBillSplitInviteSheet()
    scope.advanceUntilIdle()
    vm.selectBillSplitInviteMember(3L)
    vm.updateBillSplitInviteAmount("4.00")
    assertTrue(vm.uiState.value.billSplitInviteSheetOpen)
    submitCorrectionBeforeSharing(scope, vm)
    vm.sendBillSplitInvite()
    scope.advanceUntilIdle()
    val sentWhilePending = fake.createBillSplitCalls
    vm.cancelBillSplitInvitation(requireNotNull(vm.uiState.value.correctionAccess).binding, "existing")
    scope.advanceUntilIdle()
    assertEquals(listOf("existing"), cancelled)
    assertEquals(BillSplitStatusValues.CANCELLED, vm.uiState.value.billSplitSent.single().status)
    vm.closeBillSplitInviteSheet()
    vm.openBillSplitInviteSheet()
    scope.advanceUntilIdle()
    val openedWhilePending = vm.uiState.value.billSplitInviteSheetOpen
    vm.closeBillSplitInviteSheet()

    fake.baseExpense = fake.baseExpense.copy(
        amountCents = 1_400L, homeAmountCents = 1_400L, originalAmountMinor = 1_400L,
        rowVersion = 2L, factRevision = 2L,
    )
    holdRefresh = true
    fake.settleCorrection(PendingMutationStatus.Done)
    scope.advanceUntilIdle()
    assertTrue(vm.uiState.value.corrections.single().delivered)
    assertEquals(ExpenseDetailDataLoadState.Loading, vm.uiState.value.expenseLoadState)
    vm.openBillSplitInviteSheet()
    scope.advanceUntilIdle()
    val openedBeforeRefresh = vm.uiState.value.billSplitInviteSheetOpen
    vm.closeBillSplitInviteSheet()
    refresh.complete(Result.success(fake.baseExpense))
    scope.advanceUntilIdle()
    assertEquals(fake.baseExpense, vm.uiState.value.expense)
    vm.openBillSplitInviteSheet()
    scope.advanceUntilIdle()
    assertTrue(vm.uiState.value.billSplitInviteSheetOpen)
    vm.selectBillSplitInviteMember(3L)
    vm.updateBillSplitInviteAmount("4.00")
    vm.sendBillSplitInvite()
    scope.advanceUntilIdle()

    assertEquals(0, sentWhilePending)
    assertFalse(openedWhilePending)
    assertFalse(openedBeforeRefresh)
    assertEquals(1, fake.createBillSplitCalls)
    assertEquals(Triple(7L, 333L, 400L), fake.lastCreateBillSplitArgs)
    assertFalse(vm.uiState.value.billSplitInviteSheetOpen)
}

@OptIn(ExperimentalCoroutinesApi::class)
private fun submitCorrectionBeforeSharing(scope: TestScope, vm: ExpenseFactViewModel) {
    vm.openCorrectionSheet()
    vm.updateCorrectionField(CorrectionScalarField.Amount, "14.00")
    vm.updateCorrectionField(CorrectionScalarField.Reason, "Correct before sharing this expense")
    vm.submitCorrection()
    scope.advanceUntilIdle()
    assertEquals(PendingMutationStatus.Pending, vm.uiState.value.corrections.single().row.status)
}

private fun prepareCorrectionInvitations(fake: FakeExpenseFactActions, cancelled: MutableList<String>) {
    var existing = fake.sentInvite(publicId = "existing", amountCents = 100L)
    fake.billSplitSentResult = { Result.success(listOf(existing)) }
    fake.splitMembersResult = { Result.success(listOf(fake.member(memberId = 3L, accountId = 333L))) }
    fake.createBillSplitResult = { _, _, _ -> Result.success(11L) }
    fake.cancelBillSplitResult = { publicId ->
        cancelled += publicId
        existing = existing.copy(status = BillSplitStatusValues.CANCELLED)
        Result.success(existing)
    }
}

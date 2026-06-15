package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtDetailViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun loadDebtPopulatesStateAndReflectsRole() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            canModify = false,
            getResult = Result.success(sampleDebt("d1", remaining = 4_200L)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        assertEquals("d1", viewModel.state.value.debt?.publicId)
        assertEquals(4_200L, viewModel.state.value.debt?.remainingAmountCents)
        assertEquals(false, viewModel.state.value.canModify)
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun loadDebtFailureSetsError() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.failure(RuntimeException("offline")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun openActionSetsActiveActionAndClearsInputs() = runTest(dispatcher) {
        val viewModel = DebtDetailViewModel(FakeDebtDetailActions())
        viewModel.updateAmount("99")
        viewModel.openAction(DebtAction.Repayment)

        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals(true, viewModel.state.value.adjustmentIncrease)
    }

    @Test
    fun submitRepaymentSendsOccAmountAndSwapsFold() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 5L, remaining = 50_000L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 6L, remaining = 40_000L)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.repaymentCalls.single()
        assertEquals("d1", call.publicId)
        // OCC carrier = the loaded Debt's row_version.
        assertEquals(5L, call.expectedRowVersion)
        assertEquals(10_000L, call.amountCents)
        // Fold-after Debt swapped in (row_version advanced, remaining dropped); dialog closed + flash.
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        assertEquals(40_000L, viewModel.state.value.debt?.remainingAmountCents)
        assertNull(viewModel.state.value.activeAction)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitRepaymentValidationBlocksNonPositiveWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("0")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.repaymentCalls.isEmpty())
        // Dialog stays open so the user can correct the amount.
        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
    }

    @Test
    fun submitAdjustmentAppliesDecreaseSign() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(getResult = Result.success(sampleDebt("d1", rowVersion = 2L)))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("50")
        viewModel.updateReason("减免")
        viewModel.setAdjustmentSign(increase = false)
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.adjustmentCalls.single()
        // Magnitude 50 with the decrease sign → a negative signed delta.
        assertEquals(-5_000L, call.amountCents)
        assertEquals("减免", call.reason)
        assertEquals(2L, call.expectedRowVersion)
    }

    @Test
    fun submitAdjustmentDefaultsToIncreaseSign() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("50")
        viewModel.updateReason("手续费")
        viewModel.submit()
        advanceUntilIdle()

        // No sign toggle → the default (increase) keeps the delta positive.
        assertEquals(5_000L, repo.adjustmentCalls.single().amountCents)
    }

    @Test
    fun submitAdjustmentValidationRequiresReasonWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("50")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.adjustmentCalls.isEmpty())
    }

    @Test
    fun submitVoidSendsReasonAndSwapsFold() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(
            getResult = Result.success(sampleDebt("d1", rowVersion = 1L)),
            writeResult = Result.success(sampleDebt("d1", rowVersion = 2L, status = DebtLinkStatuses.VOIDED)),
        )
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Void)
        viewModel.updateReason("记错了")
        viewModel.submit()
        advanceUntilIdle()

        val call = repo.voidCalls.single()
        assertEquals("记错了", call.reason)
        assertEquals(1L, call.expectedRowVersion)
        assertEquals(DebtLinkStatuses.VOIDED, viewModel.state.value.debt?.status)
        assertNull(viewModel.state.value.activeAction)
    }

    @Test
    fun submitVoidValidationRequiresReasonWithoutWrite() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Void)
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        assertTrue(repo.voidCalls.isEmpty())
    }

    @Test
    fun submitFailureKeepsDialogOpenWithError() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions(writeResult = Result.failure(RuntimeException("boom")))
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.validationError != null)
        // Dialog stays open for retry; the user's input is not lost.
        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun dismissActionClearsDialog() = runTest(dispatcher) {
        val viewModel = DebtDetailViewModel(FakeDebtDetailActions())
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateAmount("5")
        viewModel.updateReason("x")
        viewModel.dismissAction()

        assertNull(viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals("", viewModel.state.value.reasonInput)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeDebtDetailActions()
        val viewModel = DebtDetailViewModel(repo)
        viewModel.loadDebt("d1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateAmount("100")
        viewModel.submit()
        advanceUntilIdle()
        assertTrue(viewModel.state.value.flashMessage != null)

        viewModel.dismissFlash()

        assertNull(viewModel.state.value.flashMessage)
    }
}

private data class WriteArgs(
    val publicId: String,
    val expectedRowVersion: Long,
    val amountCents: Long?,
    val reason: String?,
)

private class FakeDebtDetailActions(
    private val canModify: Boolean = true,
    var getResult: Result<Debt> = Result.success(sampleDebt()),
    var writeResult: Result<Debt> = Result.success(sampleDebt()),
) : DebtActions {
    val repaymentCalls = mutableListOf<WriteArgs>()
    val adjustmentCalls = mutableListOf<WriteArgs>()
    val voidCalls = mutableListOf<WriteArgs>()

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(): Result<List<Debt>> = Result.success(emptyList())

    override suspend fun getDebt(publicId: String): Result<Debt> = getResult

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> = Result.success(sampleDebt())

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> {
        repaymentCalls += WriteArgs(publicId, expectedRowVersion, amountCents, null)
        return writeResult
    }

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> {
        adjustmentCalls += WriteArgs(publicId, expectedRowVersion, amountCents, reason)
        return writeResult
    }

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> {
        voidCalls += WriteArgs(publicId, expectedRowVersion, null, reason)
        return writeResult
    }
}

private fun sampleDebt(
    publicId: String = "d1",
    rowVersion: Long = 1L,
    remaining: Long = 50_000L,
    status: String = DebtLinkStatuses.OPEN,
): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = remaining,
    paidAmountCents = 50_000 - remaining,
    status = status,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = rowVersion,
)

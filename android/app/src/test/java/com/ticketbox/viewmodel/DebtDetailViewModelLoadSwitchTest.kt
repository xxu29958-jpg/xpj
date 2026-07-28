package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtDetailViewModelLoadSwitchTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun loadingNewDebtClearsPreviousDebtUntilFreshDetailArrives() = runTest(dispatcher) {
        val repository = SwitchingDebtActions(getResult = Result.success(switchDebt("A")))
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("A")
        advanceUntilIdle()
        assertEquals("A", viewModel.state.value.debt?.publicId)

        val gate = CompletableDeferred<Unit>()
        repository.getGate = gate
        repository.getResult = Result.success(switchDebt("B"))
        viewModel.loadDebt("B")
        runCurrent()

        assertNull(viewModel.state.value.debt)
        assertTrue(viewModel.state.value.isLoading)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("B", viewModel.state.value.debt?.publicId)
    }
}

private class SwitchingDebtActions(
    var getResult: Result<Debt>,
) : DebtActions {
    var getGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = true

    override suspend fun listDebts(): Result<DebtListPage> =
        Result.success(DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = null))

    override suspend fun getDebt(publicId: String): Result<Debt> {
        val captured = getResult
        getGate?.await()
        return captured
    }

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> = Result.success(switchDebt("created"))

    override suspend fun parseDebtBillImage(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> = Result.failure(UnsupportedOperationException())

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> = Result.success(switchDebt(publicId))

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> = Result.success(switchDebt(publicId))

    override suspend fun voidDebt(publicId: String, expectedRowVersion: Long, reason: String): Result<Debt> =
        Result.success(switchDebt(publicId))

    override suspend fun setDebtKind(publicId: String, expectedRowVersion: Long, debtKind: String): Result<Debt> =
        Result.success(switchDebt(publicId))
}

private fun switchDebt(publicId: String): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "Counterparty",
    principalAmountCents = 50_000L,
    remainingAmountCents = 40_000L,
    paidAmountCents = 10_000L,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1L,
)

package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanViewModelLoadStateTest {

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
    fun activeFailureMarksFailedWithoutConfirmingEmpty() = runTest(dispatcher) {
        val viewModel = IncomePlanViewModel(
            LoadStateIncomePlanRepository(
                activeResult = Result.failure(RuntimeException("offline")),
            ),
        )
        advanceUntilIdle()

        val state = viewModel.state.value
        assertEquals(IncomePlanLoadState.Failed, state.loadState)
        assertTrue(state.activePlans.isEmpty())
        assertTrue(state.archivedPlans.isEmpty())
        assertNotNull(state.error)
    }

    @Test
    fun loadedEmptyAndArchivedFailureStayExplicit() = runTest(dispatcher) {
        val loadedEmpty = IncomePlanViewModel(LoadStateIncomePlanRepository())
        advanceUntilIdle()
        assertEquals(IncomePlanLoadState.Loaded, loadedEmpty.state.value.loadState)
        assertNull(loadedEmpty.state.value.error)

        val archivedFailure = IncomePlanViewModel(
            LoadStateIncomePlanRepository(
                archivedResult = Result.failure(RuntimeException("archived offline")),
            ),
        )
        advanceUntilIdle()

        assertEquals(IncomePlanLoadState.Loaded, archivedFailure.state.value.loadState)
        assertNotNull(archivedFailure.state.value.error)
    }
}

private class LoadStateIncomePlanRepository(
    private val activeResult: Result<IncomePlanListing> = Result.success(IncomePlanListing(emptyList(), 0L)),
    private val archivedResult: Result<List<IncomePlan>> = Result.success(emptyList()),
) : IncomePlanActions {
    override fun canModifyLedger(): Boolean = true

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        flowOf(LedgerAccessContext(loadStateBinding(), canModify = true))

    override suspend fun listActive(
        expectedBinding: LogicalSessionBinding,
    ): Result<IncomePlanListing> = activeResult

    override suspend fun listIncluding(
        expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus,
    ): Result<List<IncomePlan>> = archivedResult

    override suspend fun create(
        expectedBinding: LogicalSessionBinding,
        draft: IncomePlanDraft,
    ): Result<IncomePlan> = Result.success(plan("created"))

    override suspend fun update(publicId: String, patch: IncomePlanPatch): Result<IncomePlan> =
        Result.success(plan(publicId))

    override suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan> =
        Result.success(plan(publicId, status = IncomePlanStatus.ARCHIVED))

    override suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan> =
        Result.success(plan(publicId))
}

private fun loadStateBinding(): LogicalSessionBinding = LogicalSessionBinding(
    serverUrl = "https://api.example.com",
    ledgerId = "owner",
    ownerKey = "owner",
    sessionGeneration = "session-owner",
    bindingRevision = "binding-owner",
)

private fun plan(
    publicId: String,
    status: IncomePlanStatus = IncomePlanStatus.ACTIVE,
): IncomePlan = IncomePlan(
    publicId = publicId,
    label = publicId,
    sourceType = IncomeSourceType.SALARY,
    frequency = IncomeFrequency.MONTHLY,
    incomeMonth = null,
    amountCents = 100L,
    payDay = 1,
    status = status,
    createdAt = "2026-05-01T00:00:00Z",
    updatedAt = "2026-05-01T00:00:00Z",
    rowVersion = 1L,
    archivedAt = if (status == IncomePlanStatus.ARCHIVED) "2026-05-02T00:00:00Z" else null,
)

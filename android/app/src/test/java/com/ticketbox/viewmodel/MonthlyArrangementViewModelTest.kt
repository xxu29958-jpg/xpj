package com.ticketbox.viewmodel

import com.ticketbox.data.repository.*
import com.ticketbox.data.remote.dto.*
import com.ticketbox.domain.model.BudgetAdvice
import com.ticketbox.domain.model.BudgetAdviceResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.*

class MonthlyArrangementViewModelTest {
    @Test fun changedTrialRefreshPreventsAnOlderInFlightAdviceFromReturning() = budgetTest {
        val base = FakeBudgetActions(budget())
        var income = 10000L
        val response = CompletableDeferred<Result<BudgetAdviceResult>>()
        val repository = object : BudgetActions by base {
            override suspend fun trialAdviceInputs(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest) =
                Result.success(trialInputs(month, request, income))
            override suspend fun requestTrialAdvice(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest) = response.await()
        }
        val vm = BudgetAdviceViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.editArrangement(true, "12")
        vm.trialArrangement()
        advanceUntilIdle()
        val oldBasis = assertNotNull(vm.uiState.value.inputs)
        vm.requestAdvice()
        advanceUntilIdle()
        assertEquals(BudgetAdviceLoadState.Loading, vm.uiState.value.loadState)
        income = 20000
        vm.refreshInputs()
        advanceUntilIdle()
        response.complete(Result.success(BudgetAdviceResult(BudgetAdvice("Old income basis", emptyList(), null), "CNY", "fixture", null, oldBasis)))
        advanceUntilIdle()
        assertEquals(20000L, vm.uiState.value.inputs?.breakdown?.monthlyIncomeCents)
        assertNull(vm.uiState.value.result)
        assertEquals(BudgetAdviceLoadState.Idle, vm.uiState.value.loadState)
    }

    @Test fun viewerCanEditAndTrialButCannotSaveOrRequestAi() = budgetTest {
        val base = FakeBudgetActions(budget(), canModify = false)
        val repository = object : BudgetActions by base {
            override suspend fun trialAdviceInputs(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest) =
                Result.success(trialInputs(month, request, 10000))
            override suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest): Result<Long> =
                error("Viewer must never reach the writer")
            override suspend fun requestTrialAdvice(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest): Result<BudgetAdviceResult> =
                error("Viewer must never reach AI")
        }
        val vm = BudgetAdviceViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.editArrangement(true, "12")
        vm.trialArrangement()
        advanceUntilIdle()
        assertEquals("12", vm.uiState.value.arrangementDraft?.savings)
        assertTrue(vm.uiState.value.arrangementDraft?.edited == true)
        assertTrue(vm.uiState.value.inputs?.isTrial == true)
        assertEquals(1200L, vm.uiState.value.inputs?.breakdown?.savingsTargetCents)
        vm.saveArrangement()
        vm.requestAdvice()
        advanceUntilIdle()
        assertFalse(vm.uiState.value.canRequest)
        assertNull(vm.uiState.value.result)
        assertEquals(BudgetAdviceLoadState.Idle, vm.uiState.value.loadState)
        assertEquals("12", vm.uiState.value.arrangementDraft?.savings)
    }

    @Test fun trialRefreshKeepsSameResponseBasisButRetiresAdviceWhenAnotherDeviceChangesIncome() = budgetTest {
        val base = FakeBudgetActions(budget())
        var income = 10000L
        val repository = object : BudgetActions by base {
            override suspend fun trialAdviceInputs(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest) =
                Result.success(trialInputs(month, request, income))
            override suspend fun requestTrialAdvice(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest) =
                Result.success(BudgetAdviceResult(BudgetAdvice("Based on the returned inputs", emptyList(), null), request.homeCurrencyCode,
                    "fixture", null, trialInputs(month, request, income)))
        }
        val vm = BudgetAdviceViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.editArrangement(true, "12")
        vm.trialArrangement()
        advanceUntilIdle()
        vm.requestAdvice()
        advanceUntilIdle()
        val original = assertNotNull(vm.uiState.value.result)
        assertEquals(original.inputs, vm.uiState.value.inputs)
        vm.refreshInputs()
        advanceUntilIdle()
        assertEquals(original, vm.uiState.value.result)
        income = 20000
        vm.refreshInputs()
        advanceUntilIdle()
        assertEquals(20000L, vm.uiState.value.inputs?.breakdown?.monthlyIncomeCents)
        assertEquals(1200L, vm.uiState.value.inputs?.breakdown?.savingsTargetCents)
        assertTrue(vm.uiState.value.inputs?.isTrial == true)
        assertNull(vm.uiState.value.result)
        assertEquals(BudgetAdviceLoadState.Idle, vm.uiState.value.loadState)
    }

    @Test fun trialIsNotSaveDraftSurvivesBindingAndOnlyExplicitSaveEnqueuesOriginalCurrency() = budgetTest {
        val binding = LogicalSessionBinding("https://example.test", "owner", "identity", "session", "revision")
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding, true))
        val base = FakeBudgetActions(budget(), activeAccessFlow = access)
        val drafts = mutableMapOf<Pair<LogicalSessionBinding, String>, MonthlyArrangementDraft>()
        val queued = mutableListOf<MonthlyArrangementSaveRequest>()
        val trials = mutableListOf<MonthlyArrangementSaveRequest>()
        val repository = object : BudgetActions by base {
            override suspend fun arrangement(binding: LogicalSessionBinding, month: String) = Result.success(MonthlyArrangementRead(
                MonthlyArrangementResponseDto(binding.ledgerId, month, MonthlyArrangementDto(binding.ledgerId, month, "JPY", 1000, 300, 4, "now"))))
            override suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String) = drafts[binding to month]
            override suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft?) {
                if (draft == null) drafts.remove(binding to month) else drafts[binding to month] = draft
            }
            override suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest): Result<Long> {
                queued += request; return Result.success(1L)
            }
            override suspend fun trialAdviceInputs(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest): Result<BudgetAdviceInputsDto> {
                trials += request
                return Result.success(BudgetAdviceInputsDto(month, request.homeCurrencyCode,
                    DiscretionaryResponseDto(10000, 1000, 2000, request.savingsTargetCents, request.reservedBufferCents,
                        7000 - request.savingsTargetCents - request.reservedBufferCents, 0), emptyList(), isTrial = true))
            }
        }
        val vm = BudgetAdviceViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.editArrangement(true, "1200")
        vm.trialArrangement()
        advanceUntilIdle()
        assertEquals(1200L, trials.single().savingsTargetCents)
        assertTrue(queued.isEmpty())
        assertTrue(base.adviceMonths.isEmpty())
        access.value = LedgerAccessContext(binding.copy(ledgerId = "other"), true)
        advanceUntilIdle()
        vm.editArrangement(true, "500")
        advanceUntilIdle()
        access.value = LedgerAccessContext(binding, true)
        advanceUntilIdle()
        assertEquals("1200", vm.uiState.value.arrangementDraft?.savings)
        assertNull(vm.uiState.value.result)
        vm.saveArrangement()
        advanceUntilIdle()
        assertEquals("JPY", queued.single().homeCurrencyCode)
        assertEquals(1200L, queued.single().savingsTargetCents)
        assertEquals(4L, queued.single().expectedRowVersion)
        assertNull(drafts[binding to "2026-09"])
        assertEquals("500", drafts[binding.copy(ledgerId = "other") to "2026-09"]?.savings)
        assertTrue(base.adviceMonths.isEmpty())
    }
}

private fun trialInputs(month: String, request: MonthlyArrangementSaveRequest, income: Long) = BudgetAdviceInputsDto(
    month, request.homeCurrencyCode, DiscretionaryResponseDto(income, 1000, 2000, request.savingsTargetCents,
        request.reservedBufferCents, income - 3000 - request.savingsTargetCents - request.reservedBufferCents, 0),
    emptyList(), isTrial = true)

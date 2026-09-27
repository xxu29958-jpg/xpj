package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.test.runTest
import com.ticketbox.viewmodel.refreshInputs
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import com.ticketbox.viewmodel.*
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BudgetAdviceInputsRepositoryTest {
    @Test fun trialValidationKeepsSameCurrencyAmountsStrictAndRejectsAnotherRateTargetBeforePublishingOrCaching() = runTest {
        val f = AdviceInputsFixture()
        f.inputs = f.inputs.copy(breakdown = DiscretionaryResponseDto(10000, 1000, 2000, 0, 0, 7000), missingRates = emptyList())
        val request = MonthlyArrangementSaveRequest("JPY", 1200, 300)
        f.trialOverride = f.inputs.copy(isTrial = true, breakdown = f.inputs.breakdown.copy(savingsTargetCents = 12, reservedBufferCents = 300))
        assertTrue(f.repository.trialAdviceInputs(f.binding, "2026-09", request).isFailure)
        assertTrue(f.repository.requestTrialAdvice(f.binding, "2026-09", request).isFailure)
        assertNull(f.repository.adviceCallStore.cached(f.binding, "2026-09", "JPY", request))
        f.inputs = f.inputs.copy(homeCurrencyCode = "USD")
        f.trialOverride = f.inputs.copy(isTrial = true, missingRates = listOf(MissingExchangeRateDto("JPY", "CNY", "2026-09-01")))
        assertTrue(f.repository.trialAdviceInputs(f.binding, "2026-09", request, "USD").isFailure)
        assertTrue(f.repository.requestTrialAdvice(f.binding, "2026-09", request, "USD").isFailure)
        assertNull(f.repository.adviceCallStore.cached(f.binding, "2026-09", "USD", request))
    }

    @Test fun yenDraftTrialAndAiStayInDollarReportThroughRateRepairAndFreshBasisWithoutRewritingTheSave() = budgetTest {
        val f = AdviceInputsFixture()
        f.savedArrangement = MonthlyArrangementDto(f.binding.ledgerId, "2026-09", "JPY", 1200, 300, 1, "now")
        f.inputs = f.inputs.copy(homeCurrencyCode = "USD", savedArrangement = f.savedArrangement,
            breakdown = DiscretionaryResponseDto(10000, 1000, 2000, 120, 30, 6850), missingRates = emptyList())
        val vm = BudgetAdviceViewModel(f.repository, initialMonth = "2026-09")
        advanceUntilIdle()
        assertEquals("USD", vm.uiState.value.reportingHomeCurrencyCode)
        assertEquals("JPY", vm.uiState.value.arrangementDraft?.homeCurrencyCode)
        vm.editArrangement(true, "2400")
        vm.trialArrangement()
        advanceUntilIdle()
        val draft = assertNotNull(vm.uiState.value.arrangementDraft)
        val trial = assertNotNull(vm.uiState.value.trialRequest)
        assertEquals("JPY", trial.homeCurrencyCode)
        assertEquals(2400L, trial.savingsTargetCents)
        assertEquals("USD", vm.uiState.value.inputs?.homeCurrencyCode)
        assertEquals(240L, vm.uiState.value.inputs?.breakdown?.savingsTargetCents)
        assertEquals(mapOf("home_currency_code" to "USD", "arrangement_currency_code" to "JPY",
            "savings_target_cents" to "2400", "reserved_buffer_cents" to "300"), f.trialQueries.single())
        assertTrue(f.requests.isEmpty())
        vm.requestAdvice()
        advanceUntilIdle()
        val original = assertNotNull(vm.uiState.value.result)
        assertEquals("USD", original.homeCurrencyCode)
        assertEquals("USD", f.requests.single().homeCurrencyCode)
        assertEquals("JPY", f.requests.single().arrangementCurrencyCode)
        assertEquals(2400L, f.requests.single().savingsTargetCents)
        assertNotNull(f.repository.adviceCallStore.cached(f.binding, "2026-09", "USD", trial))
        assertNull(f.repository.adviceCallStore.cached(f.binding, "2026-09", "JPY", trial))
        f.missingTrialRate = true
        vm.refreshInputs()
        advanceUntilIdle()
        assertEquals("USD", vm.uiState.value.reportingHomeCurrencyCode)
        assertEquals("USD", vm.uiState.value.inputs?.missingRates?.single()?.homeCurrencyCode)
        assertNull(vm.uiState.value.result)
        vm.requestAdvice()
        advanceUntilIdle()
        assertEquals(1, f.requests.size, "A missing arrangement rate must block AI")
        f.missingTrialRate = false
        f.fxDivisor = 20
        vm.refreshInputs()
        advanceUntilIdle()
        assertEquals(120L, vm.uiState.value.inputs?.breakdown?.savingsTargetCents)
        assertNull(f.repository.adviceCallStore.cached(f.binding, "2026-09", "USD", trial))
        assertEquals(1, f.requests.size, "Rate refresh must not call AI")
        assertEquals(draft, vm.uiState.value.arrangementDraft)
        assertEquals(trial, vm.uiState.value.trialRequest)
        vm.requestAdvice()
        advanceUntilIdle()
        assertEquals("USD", vm.uiState.value.result?.homeCurrencyCode)
        assertEquals(120L, vm.uiState.value.result?.inputs?.breakdown?.savingsTargetCents)
        assertEquals(2, f.requests.size)
        vm.saveArrangement()
        advanceUntilIdle()
        val row = f.dao.allRows().single()
        val saved = assertNotNull(com.ticketbox.OutboxAdapterGraph().arrangementSaveAdapter.fromJson(row.payload))
        assertEquals(trial.copy(expectedRowVersion = null), saved.request)
        assertEquals("JPY", saved.request.homeCurrencyCode)
        assertEquals(1L, row.expectedRowVersion)
    }

    @Test fun savedAndDifferentTrialsDoNotShareAdviceBasisOrCacheAndReadNeverCallsAi() = runTest {
        val f = AdviceInputsFixture()
        f.inputs = f.inputs.copy(breakdown = DiscretionaryResponseDto(10000, 1000, 2000, 1000, 500, 5500), missingRates = emptyList())
        val first = MonthlyArrangementSaveRequest("JPY", 1200, 300)
        val second = first.copy(savingsTargetCents = 2400)
        val trial = f.repository.trialAdviceInputs(f.binding, "2026-09", first).getOrThrow()
        assertTrue(trial.isTrial)
        assertEquals(1200L, trial.breakdown.savingsTargetCents)
        assertFalse(f.trialQueries.single().containsKey("arrangement_currency_code"))
        assertTrue(f.requests.isEmpty(), "Trial is a deterministic read, never an AI call or save")
        f.repository.requestBudgetAdvice("2026-09", "JPY", f.binding).getOrThrow()
        f.repository.requestTrialAdvice(f.binding, "2026-09", first).getOrThrow()
        f.repository.requestTrialAdvice(f.binding, "2026-09", second).getOrThrow()
        val cache = f.repository.adviceCallStore
        assertEquals(1000L, cache.cached(f.binding, "2026-09", "JPY")?.inputs?.breakdown?.savingsTargetCents)
        assertEquals(1200L, cache.cached(f.binding, "2026-09", "JPY", first)?.inputs?.breakdown?.savingsTargetCents)
        assertEquals(2400L, cache.cached(f.binding, "2026-09", "JPY", second)?.inputs?.breakdown?.savingsTargetCents)
        f.repository.invalidateBudgetAdvice()
        assertNull(cache.cached(f.binding, "2026-09", "JPY", first))
        assertEquals(3, f.requests.size, "Invalidation never calls AI automatically")
    }

    @Test fun hiddenProviderBasisFingerprintInvalidatesCacheAndVisibleReadyWithoutAnotherProviderCall() =
        com.ticketbox.viewmodel.budgetTest {
            val f = AdviceInputsFixture()
            f.inputs = f.inputs.copy(breakdown = DiscretionaryResponseDto(10000, 1000, 2000, 0, 0, 7000),
                missingRates = emptyList(), inputsFingerprint = "original-history")
            val vm = com.ticketbox.viewmodel.BudgetAdviceViewModel(f.repository, initialMonth = "2026-09")
            vm.uiState.first { it.inputs?.inputsFingerprint == "original-history" }
            vm.requestAdvice()
            vm.uiState.first { it.result != null }
            assertNotNull(f.repository.cachedBudgetAdvice("2026-09", "JPY"))
            f.inputs = f.inputs.copy(inputsFingerprint = "changed-history-same-visible-totals")
            vm.refreshInputs()
            vm.uiState.first { it.inputs?.inputsFingerprint == "changed-history-same-visible-totals" && it.result == null }
            assertNull(f.repository.cachedBudgetAdvice("2026-09", "JPY"))
            assertEquals(1, f.requests.size)
        }
    @Test fun advisorAccessCarriesRoleAndFullBindingInOneProjection() = runTest {
        val f = AdviceInputsFixture()
        val original = requireNotNull(f.session.sessionStore.currentSession())
        f.session.sessionStore.replaceForFixture(original.copy(identity = original.identity.copy(role = "member")))
        val member = requireNotNull(f.repository.observeLedgerAccessState().first())
        f.session.sessionStore.replaceForFixture(original)
        val owner = requireNotNull(f.repository.observeLedgerAccessState().first())
        assertEquals(member.binding, owner.binding)
        assertEquals("member", member.role)
        assertEquals("owner", owner.role)
        f.session.sessionStore.replaceForFixture(original.copy(bindingRevision = "replacement"))
        val replacement = requireNotNull(f.repository.observeLedgerAccessState().first())
        assertEquals(owner.binding.ledgerId, replacement.binding.ledgerId)
        assertTrue(owner.binding != replacement.binding)
    }

    @Test fun projectionReadKeepsOriginalContextAndNeverCallsProvider() = runTest {
        val f = AdviceInputsFixture()
        val result = f.repository.adviceInputs(f.binding, "2026-09", "JPY").getOrThrow()
        assertEquals(listOf<Pair<String, String?>>("2026-09" to "JPY"), f.reads)
        assertNull(result.breakdown.spentAmountCents)
        assertFalse(result.readyForAdvice)
        assertTrue(f.requests.isEmpty())
        f.session.switchLedgerForFixture("other", "Other")
        assertTrue(f.repository.adviceInputs(f.binding, "2026-09", "JPY").isFailure)
        assertTrue(f.repository.requestBudgetAdvice("2026-09", "JPY", f.binding).isFailure)
        assertEquals(1, f.reads.size)
        assertTrue(f.requests.isEmpty())
    }

    @Test fun changedProjectionInvalidatesCacheAndGenerationKeepsTheViewedHome() = runTest {
        val f = AdviceInputsFixture()
        f.inputs = f.inputs.copy(breakdown = DiscretionaryResponseDto(10000, 1000, 2000, 0, 0, 7000), missingRates = emptyList())
        f.repository.adviceInputs(f.binding, "2026-09", "JPY").getOrThrow()
        f.repository.requestBudgetAdvice("2026-09", "JPY", f.binding).getOrThrow()
        assertEquals("JPY", f.requests.single().homeCurrencyCode)
        assertNotNull(f.repository.cachedBudgetAdvice("2026-09", "JPY"))
        assertNull(f.repository.cachedBudgetAdvice("2026-09", "CNY"))
        f.repository.adviceInputs(f.binding, "2026-09", "JPY").getOrThrow()
        assertNotNull(f.repository.cachedBudgetAdvice("2026-09", "JPY"))
        f.inputs = f.inputs.copy(breakdown = DiscretionaryResponseDto(10000, 1000, 3000, 0, 0, 6000))
        f.repository.adviceInputs(f.binding, "2026-09", "JPY").getOrThrow()
        assertNull(f.repository.cachedBudgetAdvice("2026-09", "JPY"))
        assertEquals(1, f.requests.size, "Refreshing projection must not spend another provider call")
    }

    @Test fun wrongMonthOrHomeCannotPublishInputsOrCacheAdvice() = runTest {
        val f = AdviceInputsFixture()
        f.inputs = f.inputs.copy(month = "2026-08")
        val error = f.repository.adviceInputs(f.binding, "2026-09", "JPY").exceptionOrNull()
        assertEquals(LocalRepositoryFailure.BudgetInputsUnverified, (error as? RepositoryException)?.localFailure)
        assertNull((error as? RepositoryException)?.errorCode)
        f.inputs = f.inputs.copy(month = "2026-09", homeCurrencyCode = "CNY")
        assertTrue(f.repository.adviceInputs(f.binding, "2026-09", "JPY").isFailure)
        assertTrue(f.repository.requestBudgetAdvice("2026-09", "JPY", f.binding).isFailure)
        assertNull(f.repository.cachedBudgetAdvice("2026-09", "JPY"))
    }
}

private class AdviceInputsFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-advice-input-session") }
    var inputs = BudgetAdviceInputsDto("2026-09", "JPY", DiscretionaryResponseDto(10000, 1000, null, 0, 0, null),
        listOf(MissingExchangeRateDto("USD", "JPY", "2026-09-01")))
    val reads = mutableListOf<Pair<String, String?>>()
    val requests = mutableListOf<BudgetAdviseRequestDto>()
    val trialQueries = mutableListOf<Map<String, String>>()
    var savedArrangement: MonthlyArrangementDto? = null
    var missingTrialRate = false
    var fxDivisor = 10L
    var trialOverride: BudgetAdviceInputsDto? = null
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun budgetAdviceInputs(month: String, timezone: String?, homeCurrencyCode: String?): BudgetAdviceInputsDto {
            reads += month to homeCurrencyCode
            return inputs
        }
        override suspend fun monthlyArrangement(month: String) = MonthlyArrangementResponseDto(binding.ledgerId, month, savedArrangement)
        override suspend fun exchangeRates(currencyCode: String?, homeCurrencyCode: String?, rateDate: String?, limit: Int) =
            ExchangeRateListDto(emptyList())
        override suspend fun trialBudgetAdviceInputs(month: String, timezone: String?, arrangement: Map<String, String>): BudgetAdviceInputsDto {
            trialQueries += arrangement.toMap()
            return trialBasis(month, arrangement.getValue("home_currency_code"), arrangement.getValue("savings_target_cents").toLong(),
                arrangement.getValue("reserved_buffer_cents").toLong(), arrangement["arrangement_currency_code"])
        }
        override suspend fun budgetAdvise(request: BudgetAdviseRequestDto): BudgetAdviseResponseDto {
            requests += request
            val basis = if (request.savingsTargetCents == null) inputs else trialBasis(request.month,
                requireNotNull(request.homeCurrencyCode), request.savingsTargetCents, requireNotNull(request.reservedBufferCents), request.arrangementCurrencyCode)
            return BudgetAdviseResponseDto(BudgetAdviceDto("Synthetic advice", emptyList(), null), inputs.homeCurrencyCode, "mock", inputs = basis)
        }
    }
    private fun trialBasis(month: String, home: String, savings: Long, buffer: Long, source: String? = null): BudgetAdviceInputsDto {
        trialOverride?.let { return it }
        val divisor = if (source != null && source != home) fxDivisor else 1L
        return inputs.copy(month = month, homeCurrencyCode = home, isTrial = true,
            missingRates = if (missingTrialRate) listOf(MissingExchangeRateDto(source, home, "$month-01")) else inputs.missingRates,
            breakdown = inputs.breakdown.copy(savingsTargetCents = if (missingTrialRate) null else savings / divisor,
                reservedBufferCents = if (missingTrialRate) null else buffer / divisor,
                discretionaryCents = if (missingTrialRate) null else 7000 - savings / divisor - buffer / divisor))
    }
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val dao = FakePendingMutationDao()
    val repository = testBudgetRepository(provider, testOutboxRepository(dao, bindingProvider = { provider.currentSession().toOutboxBinding() }))
}

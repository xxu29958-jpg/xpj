package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.test.runTest
import com.ticketbox.viewmodel.refreshInputs
import kotlinx.coroutines.flow.first
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BudgetAdviceInputsRepositoryTest {
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
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun budgetAdviceInputs(month: String, timezone: String?, homeCurrencyCode: String?): BudgetAdviceInputsDto {
            reads += month to homeCurrencyCode
            return inputs
        }
        override suspend fun budgetAdvise(request: BudgetAdviseRequestDto): BudgetAdviseResponseDto {
            requests += request
            return BudgetAdviseResponseDto(BudgetAdviceDto("Synthetic advice", emptyList(), null), inputs.homeCurrencyCode, "mock")
        }
    }
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val repository = testBudgetRepository(provider)
}

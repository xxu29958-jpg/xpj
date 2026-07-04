package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakeSessionTokenStore
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class CategoryRulesViewModelTest {

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
    fun initShowsIndependentLoadingUntilRulesAndHistoryReturn() = runTest(dispatcher) {
        val rulesGate = CompletableDeferred<Unit>()
        val historyGate = CompletableDeferred<Unit>()
        val vm = harness(
            object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
                override suspend fun categoryRules(): List<CategoryRuleDto> {
                    rulesGate.await()
                    return listOf(categoryRuleDto())
                }

                override suspend fun ruleApplications(limit: Int): RuleApplicationListDto {
                    historyGate.await()
                    return RuleApplicationListDto(listOf(ruleApplicationDto()))
                }
            },
        )

        runCurrent()
        assertTrue(vm.uiState.value.categoryRulesLoading)
        assertTrue(vm.uiState.value.ruleApplicationsLoading)

        rulesGate.complete(Unit)
        vm.uiState.first { !it.categoryRulesLoading }
        assertFalse(vm.uiState.value.categoryRulesLoading)
        assertTrue(vm.uiState.value.ruleApplicationsLoading)
        assertEquals(listOf("OpenAI"), vm.uiState.value.categoryRules.map { it.keyword })

        historyGate.complete(Unit)
        val state = vm.uiState.first { !it.ruleApplicationsLoading }
        assertFalse(state.ruleApplicationsLoading)
        assertEquals(listOf("batch-1"), state.ruleApplications.map { it.publicId })
    }

    @Test
    fun initRuleLoadFailureClearsLoadingAndShowsMessage() = runTest(dispatcher) {
        val vm = harness(
            object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
                override suspend fun categoryRules(): List<CategoryRuleDto> {
                    throw RepositoryException("")
                }
            },
        )

        val state = vm.uiState.first { !it.categoryRulesLoading && it.message != null }

        assertFalse(state.categoryRulesLoading)
        assertEquals(UiText.res(R.string.category_rules_load_failed), state.message)
    }

    private fun harness(api: ApiService): CategoryRulesViewModel {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiFactory = TestApiServiceFactory(api)
        val ruleRepository = RuleRepository(
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )
        val expenseRepository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )
        return CategoryRulesViewModel(
            ruleRepository = ruleRepository,
            repository = expenseRepository,
        )
    }

    private class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private companion object {
        fun categoryRuleDto(): CategoryRuleDto = CategoryRuleDto(
            id = 1L,
            keyword = "OpenAI",
            category = "AI订阅",
            enabled = true,
            priority = 10,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = "2026-05-01T00:05:00Z",
            rowVersion = 1L,
        )

        fun ruleApplicationDto(): RuleApplicationBatchDto = RuleApplicationBatchDto(
            publicId = "batch-1",
            status = "applied",
            pendingScanned = 3,
            changedCount = 1,
            createdAt = "2026-05-01T00:10:00Z",
            rolledBackAt = null,
        )
    }
}

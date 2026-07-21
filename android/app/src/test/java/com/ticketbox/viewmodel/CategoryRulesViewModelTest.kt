package com.ticketbox.viewmodel

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.R
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.TestSessionFixture
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.data.repository.testServerSessionBinding
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
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
        dispatcher.scheduler.advanceUntilIdle()
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
        runCurrent()
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

        val state = awaitInitialLoads(vm)

        assertFalse(state.categoryRulesLoading)
        assertEquals(UiText.res(R.string.category_rules_load_failed), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
    }

    @Test
    fun createRuleSuccessShowsSuccessTone() = runTest(dispatcher) {
        val vm = harness(
            object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
                override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto =
                    categoryRuleDto(
                        keyword = requireNotNull(request.keyword),
                        category = requireNotNull(request.category),
                        priority = requireNotNull(request.priority),
                    )
            },
        )
        awaitInitialLoads(vm)

        vm.createCategoryRule(keyword = "高德", category = "交通", priority = 8)
        val state = vm.uiState.first { it.message == UiText.res(R.string.category_rules_added) }
        runCurrent()

        assertFalse(state.busy)
        assertEquals(MessageTone.Success, state.messageTone)
        assertEquals(listOf("高德"), state.categoryRules.map { it.keyword })
        assertEquals(1, state.changedRevision)
    }

    @Test
    fun previewApplyFailureShowsDangerToneAndClearsBusy() = runTest(dispatcher) {
        val vm = harness(
            object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
                override suspend fun applyConfirmedRules(
                    request: RuleApplyConfirmedRequestDto,
                    limit: Int,
                    maxScan: Int,
                ): RuleApplyConfirmedResponseDto {
                    throw RepositoryException("")
                }
            },
        )
        awaitInitialLoads(vm)

        vm.previewApplyConfirmedRules()
        val state = vm.uiState.first { !it.busy && it.message != null }
        runCurrent()

        assertEquals(UiText.res(R.string.category_rules_apply_preview_failed), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
        assertEquals(0, state.changedRevision)
    }

    @Test
    fun rollbackFailureShowsDangerToneAndClearsBusy() = runTest(dispatcher) {
        val vm = harness(
            object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
                override suspend fun rollbackRuleApplication(publicId: String): RuleApplicationRollbackDto {
                    throw RepositoryException("")
                }
            },
        )
        val application = awaitInitialLoads(vm).ruleApplications.single()

        vm.rollbackRuleApplication(application)
        val state = vm.uiState.first { !it.busy && it.message != null }
        runCurrent()

        assertEquals(UiText.res(R.string.category_rules_rollback_failed), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
        assertEquals(0, state.changedRevision)
    }

    private fun harness(api: ApiService): CategoryRulesViewModel {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "owner",
                    ledgerName = "我的小票夹",
                    deviceName = "Pixel",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val apiFactory = TestApiServiceFactory(api)
        val ruleRepository = RuleRepository(
            binding = testServerSessionBinding(
                apiClient = apiFactory,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
        )
        val expenseRepository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = apiFactory,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
        )
        return CategoryRulesViewModel(
            ruleRepository = ruleRepository,
            repository = expenseRepository,
        )
    }

    private suspend fun TestScope.awaitInitialLoads(vm: CategoryRulesViewModel): CategoryRulesUiState {
        val state = vm.uiState.first { state ->
            !state.categoryRulesLoading &&
                !state.ruleApplicationsLoading &&
                (state.ruleApplications.isNotEmpty() || state.message != null)
        }
        runCurrent()
        return state
    }

    private class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private companion object {
        fun categoryRuleDto(
            keyword: String = "OpenAI",
            category: String = "AI订阅",
            priority: Int = 10,
        ): CategoryRuleDto = CategoryRuleDto(
            id = 1L,
            keyword = keyword,
            category = category,
            enabled = true,
            priority = priority,
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

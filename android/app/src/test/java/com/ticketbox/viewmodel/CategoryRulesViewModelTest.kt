package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.cancel

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
    private val models = mutableListOf<CategoryRulesViewModel>()

    @BeforeTest
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        models.forEach { it.viewModelScope.cancel() }
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
    fun createIsOnlySubmittedAfterDurableSaveAndDoesNotInventConfirmedRule() = runTest(dispatcher) {
        val vm = harness(FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0))
        awaitInitialLoads(vm)
        val confirmed = vm.uiState.value.categoryRules
        vm.createCategoryRule(CategoryRuleRequest("高德", "交通", true, 8, 1200, homeCurrencyCode = "JPY"))
        val state = vm.uiState.first { it.submittedRevision > 0 }
        runCurrent()
        assertFalse(state.busy)
        assertEquals(MessageTone.Info, state.messageTone)
        assertEquals(confirmed, state.categoryRules)
        assertEquals(0, state.changedRevision)
        assertEquals("JPY", vm.uiState.first { it.pendingSubmissions.isNotEmpty() }.pendingSubmissions.single().request?.homeCurrencyCode)
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

    @Test
    fun confirmApplyWithChangesBumpsApplicationRevisionOnly() = runTest(dispatcher) {
        // 应用规则改写确认流水的分类：走 applicationRevision（流水行重同步），
        // 不再 bump changedRevision（字典并未变化）。
        val vm = harness(FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0))
        awaitInitialLoads(vm)

        vm.previewApplyConfirmedRules()
        vm.uiState.first { it.confirmedRulesPreview != null }
        vm.confirmApplyConfirmedRules()
        val state = vm.uiState.first { it.applicationRevision > 0 }
        runCurrent()

        assertEquals(1, state.applicationRevision)
        assertEquals(0, state.changedRevision)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun rollbackWithChangesBumpsApplicationRevisionOnly() = runTest(dispatcher) {
        val vm = harness(FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0))
        val application = awaitInitialLoads(vm).ruleApplications.single()

        vm.rollbackRuleApplication(application)
        val state = vm.uiState.first { it.applicationRevision > 0 }
        runCurrent()

        assertEquals(1, state.applicationRevision)
        assertEquals(0, state.changedRevision)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun delayedPreviewCannotPopulateAnotherLedger() = runTest(dispatcher) {
        val session = TestSessionFixture().apply { saveToken("synthetic-rule-session") }
        val started = CompletableDeferred<Unit>()
        val finish = CompletableDeferred<Unit>()
        val vm = harness(object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int,
                maxScan: Int): RuleApplyConfirmedResponseDto {
                started.complete(Unit)
                finish.await()
                return RuleApplyConfirmedResponseDto(dryRun = true, confirmedScanned = 1, changedCount = 1, previewToken = "original-ledger-preview")
            }
        }, session)
        awaitInitialLoads(vm)
        vm.previewApplyConfirmedRules()
        started.await()
        session.switchLedgerForFixture("other", "其他账本")
        runCurrent()
        finish.complete(Unit)
        advanceUntilIdle()
        assertEquals("other", vm.uiState.value.binding?.ledgerId)
        assertEquals(null, vm.uiState.value.confirmedRulesPreview)
        assertEquals(null, vm.uiState.value.message)
    }

    @Test
    fun historicalAcceptedReceiptCannotResurrectADeletedCanonicalRule() = runTest(dispatcher) {
        val queue = com.ticketbox.data.repository.testOutboxRepository(com.ticketbox.data.repository.FakePendingMutationDao())
        val accepted = categoryRuleDto(keyword = "旅行", category = "交通").copy(amountMinCents = 1200, homeCurrencyCode = "JPY")
        var canonical = listOf(accepted)
        val vm = harness(object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun categoryRules(): List<CategoryRuleDto> = canonical
        }, queue = queue)
        awaitInitialLoads(vm)
        vm.createCategoryRule(CategoryRuleRequest("旅行", "交通", true, 10, 1200, homeCurrencyCode = "JPY"))
        val pending = vm.uiState.first { it.pendingSubmissions.isNotEmpty() }.pendingSubmissions.single()
        queue.markDone(pending.row.id, receiptJson = com.ticketbox.OutboxAdapterGraph().categoryRuleReceiptAdapter.toJson(accepted))
        advanceUntilIdle()
        canonical = emptyList()
        vm.loadCategoryRules()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.categoryRules.isEmpty())
        assertEquals("JPY", vm.uiState.value.pendingSubmissions.single().confirmed?.homeCurrencyCode)
    }

    private fun harness(api: ApiService, tokenStore: TestSessionFixture = TestSessionFixture().apply { saveToken("session-token") },
        queue: com.ticketbox.data.repository.OutboxRepository = com.ticketbox.data.repository.testOutboxRepository(com.ticketbox.data.repository.FakePendingMutationDao())): CategoryRulesViewModel {
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
        val apiFactory = TestApiServiceFactory(api)
        val adapters = com.ticketbox.OutboxAdapterGraph()
        val ruleRepository = RuleRepository(
            binding = testServerSessionBinding(
                apiClient = apiFactory,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
            offlineMutations = com.ticketbox.data.repository.CategoryRuleOfflineMutationWiring(queue,
                adapters.categoryRuleUpdateAdapter, adapters.categoryRuleDeleteAdapter,
                adapters.categoryRuleSubmissionAdapter, adapters.categoryRuleReceiptAdapter),
        )
        val expenseRepository = com.ticketbox.data.repository.expenseRepositoryFixture(
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
        ).also { models += it }
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

package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakeSessionTokenStore
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
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

@OptIn(ExperimentalCoroutinesApi::class)
class MerchantAliasViewModelToneTest {

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
    fun catalogLoadFailureShowsDangerTone() = runTest(dispatcher) {
        val base = fakeApi()
        val service = object : ApiService by base {
            override suspend fun merchantCatalog(includeHidden: Boolean): MerchantCatalogListDto {
                throw RepositoryException("catalog unavailable")
            }
        }

        val vm = harness(service).vm
        val state = awaitSettledState(vm) {
            it.messageTone == MessageTone.Danger && it.merchantAliases.isNotEmpty()
        }

        assertEquals(MessageTone.Danger, state.messageTone)
        assertNotNull(state.message)
    }

    @Test
    fun aliasLoadFailureShowsDangerTone() = runTest(dispatcher) {
        val base = fakeApi()
        val service = object : ApiService by base {
            override suspend fun merchantAliases(): MerchantAliasListDto {
                throw RepositoryException("aliases unavailable")
            }
        }

        val vm = harness(service).vm
        val state = awaitSettledState(vm) {
            it.messageTone == MessageTone.Danger && it.merchantCatalog.isNotEmpty()
        }

        assertEquals(MessageTone.Danger, state.messageTone)
        assertNotNull(state.message)
    }

    @Test
    fun createMerchantAliasSuccessShowsSuccessTone() = runTest(dispatcher) {
        val vm = harness(fakeApi()).vm
        awaitSettledState(vm)

        vm.createMerchantAlias("Starbucks", "Starbucks Local")
        val state = vm.uiState.first { it.message == UiText.res(R.string.merchant_alias_added) }
        advanceUntilIdle()

        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun toggleMerchantAliasSyncedShowsSuccessTone() = runTest(dispatcher) {
        val vm = harness(fakeApi()).vm
        val initial = awaitSettledState(vm)
        val alias = initial.merchantAliases.single()

        vm.toggleMerchantAlias(alias)
        val state = vm.uiState.first { it.message == UiText.res(R.string.merchant_alias_disabled) }
        advanceUntilIdle()

        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun deleteMerchantAliasSyncedShowsSuccessToneAndUndoHandle() = runTest(dispatcher) {
        val vm = harness(fakeApi()).vm
        val initial = awaitSettledState(vm)
        val alias = initial.merchantAliases.single()

        vm.deleteMerchantAlias(alias)
        val state = vm.uiState.first { it.message == UiText.res(R.string.merchant_alias_deleted) }
        advanceUntilIdle()

        assertEquals(MessageTone.Success, state.messageTone)
        assertEquals(alias, state.undoableAlias)
    }

    @Test
    fun undoDeleteSuccessShowsSuccessToneAndClearsUndo() = runTest(dispatcher) {
        val vm = harness(fakeApi()).vm
        val initial = awaitSettledState(vm)
        val alias = initial.merchantAliases.single()

        vm.deleteMerchantAlias(alias)
        vm.uiState.first { it.undoableAlias != null }
        advanceUntilIdle()
        vm.undoDelete()
        val state = vm.uiState.first { it.message == UiText.res(R.string.merchant_alias_restored) }
        advanceUntilIdle()

        assertEquals(MessageTone.Success, state.messageTone)
        assertNull(state.undoableAlias)
    }

    private fun harness(service: ApiService): Harness {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "me",
                ledgerId = "owner",
                ledgerName = "My ledger",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiFactory = FixedApiServiceFactory(service)
        val merchantRepository = MerchantRepository(
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
        return Harness(
            vm = MerchantAliasViewModel(
                merchantRepository = merchantRepository,
                repository = expenseRepository,
            ),
        )
    }

    private data class Harness(
        val vm: MerchantAliasViewModel,
    )

    private suspend fun TestScope.awaitSettledState(
        vm: MerchantAliasViewModel,
        condition: (MerchantAliasUiState) -> Boolean = { state ->
            state.merchantCatalog.isNotEmpty() && state.merchantAliases.isNotEmpty()
        },
    ): MerchantAliasUiState {
        val state = vm.uiState.first(condition)
        advanceUntilIdle()
        return state
    }

    private class FixedApiServiceFactory(
        private val service: ApiService,
    ) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private companion object {
        fun fakeApi(): FakeApiService =
            FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
    }
}

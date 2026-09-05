package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.ledgerSessionFixture
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.testServerSessionBinding
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class MerchantAliasViewModelToneTest {
    private val activeViewModels = mutableListOf<MerchantAliasViewModel>()

    private fun merchantAlias(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            advanceUntilIdle()
            cancelMerchantAliasTestViewModels(activeViewModels)
            advanceUntilIdle()
            activeViewModels.clear()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun teardownWaitsForRealIoBeforeResettingMain() = merchantAlias {
        val aliasStarted = CompletableDeferred<Unit>()
        val releaseAlias = CompletableDeferred<Unit>()
        val base = fakeApi()
        val service = object : ApiService by base {
            override suspend fun merchantAliases(): MerchantAliasListDto {
                // Keep an already-entered real repository IO call alive through
                // cancellation; virtual scheduler idleness cannot finish it.
                withContext(NonCancellable) {
                    aliasStarted.complete(Unit)
                    releaseAlias.await()
                }
                return base.merchantAliases()
            }
        }
        val vm = harness(service).vm
        val viewModelJob = vm.viewModelScope.coroutineContext.job
        aliasStarted.await()
        val cleanup = async { cancelMerchantAliasTestViewModels(activeViewModels) }
        try {
            runCurrent()
            assertTrue(viewModelJob.isCancelled)
            assertFalse(cleanup.isCompleted, "Cleanup must await the real IO child before Main is reset")
        } finally {
            // Also finish every child on the test-first RED path, so the
            // counterexample cannot contaminate the next test itself.
            releaseAlias.complete(Unit)
            cleanup.await()
            viewModelJob.join()
        }
        assertTrue(viewModelJob.isCompleted)
    }

    @Test
    fun catalogLoadFailureShowsDangerTone() = merchantAlias {
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
    fun aliasLoadFailureShowsDangerTone() = merchantAlias {
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
    fun createMerchantAliasSuccessShowsSuccessTone() = merchantAlias {
        val vm = harness(fakeApi()).vm
        awaitSettledState(vm)

        vm.createMerchantAlias("Starbucks", "Starbucks Local")
        val state = vm.uiState.first { it.message == UiText.res(R.string.merchant_alias_added) }
        advanceUntilIdle()

        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun toggleMerchantAliasSyncedShowsSuccessTone() = merchantAlias {
        val vm = harness(fakeApi()).vm
        val initial = awaitSettledState(vm)
        val alias = initial.merchantAliases.single()

        vm.toggleMerchantAlias(alias)
        val state = vm.uiState.first { it.message == UiText.res(R.string.merchant_alias_disabled) }
        advanceUntilIdle()

        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun deleteMerchantAliasSyncedShowsSuccessToneAndUndoHandle() = merchantAlias {
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
    fun undoDeleteSuccessShowsSuccessToneAndClearsUndo() = merchantAlias {
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
                PersistedLedgerIdentity(
                    accountName = "me",
                    ledgerId = "owner",
                    ledgerName = "My ledger",
                    deviceName = "Pixel",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val tokenStore = ledgerSessionFixture("owner", "My ledger")
        val apiFactory = FixedApiServiceFactory(service)
        val merchantRepository = MerchantRepository(
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
        val vm = MerchantAliasViewModel(
            merchantRepository = merchantRepository,
            repository = expenseRepository,
        )
        activeViewModels += vm
        return Harness(vm = vm)
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

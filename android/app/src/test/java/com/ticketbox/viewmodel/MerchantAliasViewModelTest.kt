package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeApiServiceFactory
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakeSessionTokenStore
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class MerchantAliasViewModelTest {

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
    fun createMerchantCatalogAddsCreatedItemAndShowsSuccess() = runTest(dispatcher) {
        val harness = harness()
        harness.vm.uiState.first { it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" } }

        harness.vm.createMerchantCatalog("  蓝瓶咖啡  ")
        val state = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-created" }
        }

        assertEquals("蓝瓶咖啡", harness.api.merchantCatalogCreateRequests.single().displayName)
        assertTrue(state.merchantCatalog.any { it.publicId == "catalog-created" })
        assertEquals(UiText.res(R.string.merchant_catalog_added), state.message)
    }

    @Test
    fun toggleMerchantCatalogUsesRowVersionAndReplacesState() = runTest(dispatcher) {
        val harness = harness()
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.toggleMerchantCatalog(item)
        val state = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" && catalog.status == "hidden" }
        }

        assertEquals(listOf("catalog-1"), harness.api.merchantCatalogPatchTargets)
        assertEquals(1L, harness.api.merchantCatalogUpdateRequests.single().expectedRowVersion)
        assertEquals("hidden", harness.api.merchantCatalogUpdateRequests.single().status)
        assertEquals("hidden", state.merchantCatalog.single().status)
        assertEquals(UiText.res(R.string.merchant_catalog_hidden), state.message)
    }

    @Test
    fun deleteMerchantCatalogUsesRowVersionAndDropsItem() = runTest(dispatcher) {
        val harness = harness()
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.deleteMerchantCatalog(item)
        val state = harness.vm.uiState.first {
            it.message == UiText.res(R.string.merchant_catalog_deleted)
        }

        assertEquals(listOf("catalog-1"), harness.api.merchantCatalogDeleteTargets)
        assertEquals(1L, harness.api.merchantCatalogDeleteRequests.single().expectedRowVersion)
        assertTrue(state.merchantCatalog.none { it.publicId == "catalog-1" })
        assertEquals(UiText.res(R.string.merchant_catalog_deleted), state.message)
    }

    @Test
    fun viewerCannotMutateMerchantCatalog() = runTest(dispatcher) {
        val harness = harness(role = "viewer")
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.createMerchantCatalog("蓝瓶咖啡")
        harness.vm.toggleMerchantCatalog(item)
        harness.vm.deleteMerchantCatalog(item)

        assertTrue(harness.api.merchantCatalogCreateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogDeleteRequests.isEmpty())
        assertEquals(UiText.res(R.string.common_readonly_ledger), harness.vm.uiState.value.message)
    }

    private fun harness(role: String = "owner"): Harness {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = role,
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val api = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val apiFactory = FakeApiServiceFactory(api)
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
            api = api,
            vm = MerchantAliasViewModel(
                merchantRepository = merchantRepository,
                repository = expenseRepository,
            ),
        )
    }

    private data class Harness(
        val api: FakeApiService,
        val vm: MerchantAliasViewModel,
    )
}

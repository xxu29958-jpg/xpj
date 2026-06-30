package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeApiServiceFactory
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakeSessionTokenStore
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.MerchantConflictDetails
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RepositoryConflictDetails
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
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
    fun renameMerchantCatalogConflictSuggestsMergeWithFreshTargetToken() = runTest(dispatcher) {
        val harness = harness {
            merchantCatalogItems = listOf(
                merchantCatalogDto(publicId = "source", displayName = "星巴克", rowVersion = 2L),
                merchantCatalogDto(publicId = "target", displayName = "蓝瓶咖啡", rowVersion = 3L),
            )
            merchantCatalogUpdateFailure = RepositoryException(
                message = "商家名已被占用。",
                errorCode = "state_conflict",
                conflict = RepositoryConflictDetails(
                    merchant = MerchantConflictDetails(
                        publicId = "target",
                        rowVersion = 9L,
                        displayName = "蓝瓶咖啡",
                        status = "active",
                        deleted = false,
                    ),
                ),
            )
        }
        val initial = harness.vm.uiState.first { it.merchantCatalog.size == 2 }
        val source = initial.merchantCatalog.single { it.publicId == "source" }

        harness.vm.renameMerchantCatalog(source, "蓝瓶咖啡")
        val state = harness.vm.uiState.first { it.mergeSuggestion != null }

        assertEquals(UiText.res(R.string.merchant_catalog_rename_conflict_merge_prompt, "蓝瓶咖啡"), state.message)
        val suggestion = requireNotNull(state.mergeSuggestion)
        assertEquals("source", suggestion.source.publicId)
        assertEquals("target", suggestion.target.publicId)
        assertEquals(9L, suggestion.target.rowVersion)
    }

    @Test
    fun mergeMerchantCatalogSendsAliasPolicyAndMarksSourceMerged() = runTest(dispatcher) {
        val harness = harness {
            merchantCatalogItems = listOf(
                merchantCatalogDto(publicId = "catalog-1", displayName = "星巴克", rowVersion = 1L),
                merchantCatalogDto(publicId = "catalog-2", displayName = "蓝瓶咖啡", rowVersion = 4L),
            )
        }
        val initial = harness.vm.uiState.first { it.merchantCatalog.size == 2 }
        val source = initial.merchantCatalog.single { it.publicId == "catalog-1" }
        val target = initial.merchantCatalog.single { it.publicId == "catalog-2" }

        harness.vm.mergeMerchantCatalog(source, target, MerchantCatalogAliasPolicy.CreateSourceAlias)
        val state = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" && catalog.status == "merged" }
        }

        assertEquals(listOf("catalog-1"), harness.api.merchantCatalogMergeTargets)
        val request = harness.api.merchantCatalogMergeRequests.single()
        assertEquals(1L, request.expectedRowVersion)
        assertEquals("catalog-2", request.targetPublicId)
        assertEquals(4L, request.targetRowVersion)
        assertEquals("create_source_alias", request.aliasPolicy)
        assertEquals(
            UiText.res(R.string.merchant_catalog_merged_with_alias, "星巴克", "蓝瓶咖啡"),
            state.message,
        )
    }

    @Test
    fun viewerCannotMutateMerchantCatalog() = runTest(dispatcher) {
        val harness = harness(role = "viewer")
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.createMerchantCatalog("蓝瓶咖啡")
        harness.vm.renameMerchantCatalog(item, "蓝瓶咖啡")
        harness.vm.toggleMerchantCatalog(item)
        harness.vm.mergeMerchantCatalog(item, item, MerchantCatalogAliasPolicy.None)
        harness.vm.deleteMerchantCatalog(item)

        assertTrue(harness.api.merchantCatalogCreateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogMergeRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogDeleteRequests.isEmpty())
        assertEquals(UiText.res(R.string.common_readonly_ledger), harness.vm.uiState.value.message)
    }

    private fun harness(
        role: String = "owner",
        configureApi: FakeApiService.() -> Unit = {},
    ): Harness {
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
        val api = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0).apply(configureApi)
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

    private companion object {
        fun merchantCatalogDto(
            publicId: String,
            displayName: String,
            rowVersion: Long,
        ): MerchantCatalogDto = MerchantCatalogDto(
            publicId = publicId,
            displayName = displayName,
            merchantKey = displayName,
            status = "active",
            mergedIntoPublicId = null,
            usageCount = 0,
            createdAt = "2026-05-13T00:00:00Z",
            updatedAt = "2026-05-13T00:05:00Z",
            rowVersion = rowVersion,
            deletedAt = null,
        )
    }
}

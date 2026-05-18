package com.ticketbox.data.repository

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.RuleApplyPreviewItemDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.TagsDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.data.remote.dto.UserUiPreferencesDto
import com.ticketbox.data.remote.dto.UserUiPreferencesUpdateRequestDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.security.SessionTokenStore
import com.ticketbox.viewmodel.SettingsViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryBindingTest {
    @Test
    fun bindSavesSessionAndIdentityBeforeConfirmedRestoreFailure() = runTest {
        val events = mutableListOf<String>()
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveLastConfirmedSyncAt("2026-05-01T00:00:00Z")
        }
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.bindServer("https://api.example.com/", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertEquals("https://api.example.com", settingsStore.serverUrl())
        assertEquals("session-token", tokenStore.getToken())
        assertEquals("我", settingsStore.accountName())
        assertEquals("我的小票夹", settingsStore.ledgerName())
        assertEquals("Android Test Device", settingsStore.deviceName())
        assertEquals("owner", settingsStore.role())
        assertNull(settingsStore.lastConfirmedSyncAt())
        assertTrue(settingsStore.isBound())
        assertTrue(events.indexOf("saveServerUrl") < events.indexOf("syncConfirmed"))
        assertTrue(events.indexOf("saveToken") < events.indexOf("syncConfirmed"))
        assertTrue(events.indexOf("saveIdentity") < events.indexOf("syncConfirmed"))
    }

    @Test
    fun bindDoesNotSendOldSessionTokenAndClearsStaleTargetLedgerCache() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao()
        dao.insert(
            ExpenseEntity(
                ledgerId = "owner",
                serverId = 99,
                publicId = "old-server-expense",
                amountCents = 1200,
                merchant = "旧服务器缓存",
                category = "餐饮",
                note = null,
                source = "旧绑定",
                thumbnailPath = null,
                imageHash = null,
                rawText = null,
                duplicateStatus = "none",
                duplicateOfId = null,
                duplicateReason = null,
                tags = null,
                valueScore = null,
                regretScore = null,
                status = "confirmed",
                expenseTime = "2026-05-01T00:00:00Z",
                createdAt = "2026-05-01T00:00:00Z",
                confirmedAt = "2026-05-01T00:00:00Z",
                updatedAt = "2026-05-01T00:00:00Z",
            ),
        )
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = FakeSessionTokenStore(events).apply { saveToken("old-session-token") }
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.bindServer("https://new.example.com", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertNull(apiFactory.tokenValues.first())
        assertEquals("session-token", apiFactory.tokenValues.last())
        assertTrue(dao.getConfirmed("owner").isEmpty())
    }

    @Test
    fun manualConfirmedSyncStillWorksAfterBindRestoreFailure() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val bindResult = repository.bindServer("https://api.example.com", "123456").getOrThrow()
        val syncResult = repository.syncConfirmed().getOrThrow()

        assertTrue(bindResult.confirmedRestoreFailed)
        assertEquals(1, syncResult.size)
        assertEquals("高德", dao.getConfirmed("owner").single().merchant)
        assertEquals("session-token", apiFactory.tokenValues.last())
    }

    @Test
    fun confirmedSyncForwardsSelectedTagFilter() = runTest {
        val events = mutableListOf<String>()
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
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
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed(month = "2026-05", category = "餐饮", tag = "AI").getOrThrow()

        assertEquals("2026-05", apiService.lastConfirmedMonth)
        assertEquals("餐饮", apiService.lastConfirmedCategory)
        assertEquals("AI", apiService.lastConfirmedTag)
    }

    @Test
    fun fullConfirmedSyncDeletesRemoteMissingCachedRows() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(serverId = 9, publicId = "remote-kept", merchant = "旧高德"))
        dao.insert(cachedConfirmedEntity(serverId = 99, publicId = "remote-deleted", merchant = "已删除"))
        val settingsStore = boundSettingsStore()
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed().getOrThrow()

        val cached = dao.getConfirmed("owner")
        assertEquals(listOf(9L), cached.map { it.serverId })
        assertEquals("高德", cached.single().merchant)
    }

    @Test
    fun filteredConfirmedSyncDoesNotDeleteUnreturnedCachedRows() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(serverId = 99, publicId = "other-filter-row", merchant = "不在当前筛选"))
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
            settingsStore = boundSettingsStore(),
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed(month = "2026-05", category = "交通", tag = null).getOrThrow()

        assertEquals(listOf(9L, 99L), dao.getConfirmed("owner").map { it.serverId }.sorted())
    }

    @Test
    fun confirmedSyncFailsOnEmptyPageBeforeReportedTotal() = runTest {
        val dao = FakeExpenseDao()
        val settingsStore = boundSettingsStore()
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).apply {
            confirmedResponses[1] = PaginatedExpensesDto(
                items = emptyList(),
                page = 1,
                pageSize = 50,
                total = 2,
            )
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val failure = repository.syncConfirmed().exceptionOrNull()

        assertTrue(failure is RepositoryException)
        assertTrue(failure.message!!.contains("分页异常"))
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun confirmedSyncSkipsCacheWhenLedgerChangesDuringRequest() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveServerUrl("https://api.zen70.cn")
            saveIdentity(
                accountName = "Account",
                ledgerId = "owner",
                ledgerName = "Owner Ledger",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 0).apply {
            onConfirmedRequest = {
                settingsStore.saveIdentity(
                    accountName = "Account",
                    ledgerId = "family",
                    ledgerName = "Family Ledger",
                    deviceName = "Pixel",
                    role = "member",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            }
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.syncConfirmed().getOrThrow()

        assertTrue(result.isEmpty())
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
        assertNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun authCheckRefreshesStoredIdentityAndRole() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "viewer",
                scope = "app",
            ),
        )
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("viewer", settingsStore.role())
        assertTrue(!repository.canModifyLedger())
    }

    @Test
    fun authCheckSlowResponseDoesNotOverwriteNewActiveLedger() = runTest {
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
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-a") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "owner",
                scope = "app",
            ),
        )
        apiService.onCheckAuth = {
            tokenStore.saveToken("session-b")
            settingsStore.saveIdentity(
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:05:00Z",
            )
        }
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("member", settingsStore.role())
        assertEquals("session-b", tokenStore.getToken())
    }

    @Test
    fun settingsRefreshesIdentityChangedByInvitationAccept() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        val viewModelStore = ViewModelStore()
        try {
            val settingsStore = FakeTicketboxSettingsStore().apply {
                saveServerUrl("https://api.example.com")
                saveIdentity(
                    accountName = "我",
                    ledgerId = "old",
                    ledgerName = "旧账本",
                    deviceName = "旧设备",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            }
            val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
            val apiClient = FakeApiServiceFactory(
                FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0),
            )
            val repository = ExpenseRepository(
                expenseDao = FakeExpenseDao(),
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
                deviceNameProvider = { "Android Test Device" },
            )
            val ruleRepository = RuleRepository(
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            )
            val merchantRepository = MerchantRepository(
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            )
            val viewModel = ViewModelProvider(
                viewModelStore,
                object : ViewModelProvider.Factory {
                    @Suppress("UNCHECKED_CAST")
                    override fun <T : ViewModel> create(modelClass: Class<T>): T {
                        return SettingsViewModel(
                            repository,
                            ruleRepository,
                            merchantRepository,
                            settingsStore,
                        ) as T
                    }
                },
            )[SettingsViewModel::class.java]

            settingsStore.saveIdentity(
                accountName = "2468",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "9753",
                role = "viewer",
                boundAt = "2026-05-13T00:00:00Z",
            )

            viewModel.refreshLocalBindingState()

            val state = viewModel.uiState.value
            assertEquals("2468", state.accountName)
            assertEquals("家庭账本", state.ledgerName)
            assertEquals("9753", state.deviceName)
            assertEquals("viewer", state.role)
        } finally {
            viewModelStore.clear()
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun serverSettingsDoesNotPersistMismatchedLedgerSnapshot() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "viewer",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            serverSettingsResult = ServerSettingsDto(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                ledgerIsDefault = true,
                deviceName = "Pixel",
                role = "owner",
                status = "ok",
                storageStatus = "normal",
                pendingCount = 0,
                confirmedCount = 0,
                rejectedCount = 0,
                suspectedDuplicateCount = 0,
                uploadStorageBytes = 0,
                latestUploadAt = null,
            ),
        )
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val settings = repository.serverSettings().getOrThrow()

        assertEquals("owner", settings.ledgerId)
        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("viewer", settingsStore.role())
    }

    @Test
    fun notificationDraftUploadsStructuredFieldsOnlyAndDoesNotCachePending() = runTest {
        val dao = FakeExpenseDao()
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
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.createNotificationDraft(
            NotificationDraft(
                source = NotificationDraftSource.WeChat,
                amountCents = 2680,
                merchant = " 星巴克 ",
                category = "吃饭",
                expenseTime = "2026-05-13T10:05:00Z",
            ),
        ).getOrThrow()

        assertEquals("pending", result.status)
        assertEquals("通知草稿:微信", result.source)
        assertEquals("星巴克", apiService.lastNotificationDraftRequest?.merchant)
        assertEquals("餐饮", apiService.lastNotificationDraftRequest?.category)
        assertEquals("wechat", apiService.lastNotificationDraftRequest?.source)
        assertEquals(emptyList(), dao.getConfirmed("owner"))
    }

    @Test
    fun ruleGovernancePreviewAndConfirmUseConfirmedEndpointAndRefreshCache() = runTest {
        val dao = FakeExpenseDao()
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
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiClient = FakeApiServiceFactory(apiService)
        val expenseRepository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiClient,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )
        val ruleRepository = RuleRepository(
            apiClient = apiClient,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            onConfirmedChanged = { expenseRepository.syncConfirmed() },
        )

        val preview = ruleRepository.previewApplyConfirmedRules().getOrThrow()
        val confirmed = ruleRepository.confirmApplyConfirmedRules(requireNotNull(preview.previewToken)).getOrThrow()

        assertTrue(preview.dryRun)
        assertEquals(1, preview.changedCount)
        assertEquals(listOf(false, true), apiService.applyConfirmedRequests.map { it.confirm })
        assertEquals(listOf(null, "preview-token"), apiService.applyConfirmedRequests.map { it.previewToken })
        assertEquals(1, confirmed.changedCount)
        assertEquals("高德", dao.getConfirmed("owner").single().merchant)
    }

    @Test
    fun ruleApplicationRollbackPostsPublicIdAndRefreshesHistory() = runTest {
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
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val ruleRepository = RuleRepository(
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
        )

        val applications = ruleRepository.ruleApplications().getOrThrow()
        val rollback = ruleRepository.rollbackRuleApplication(" batch-1 ").getOrThrow()

        assertEquals("batch-1", applications.single().publicId)
        assertEquals("batch-1", apiService.rollbackPublicIds.single())
        assertEquals(1, rollback.changed)
    }

    @Test
    fun merchantAliasCrudTrimsInputAndUsesPublicIds() = runTest {
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
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val merchantRepository = MerchantRepository(
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
        )

        val listed = merchantRepository.merchantAliases().getOrThrow()
        val created = merchantRepository.createMerchantAlias(" 星巴克 ", " Starbucks ").getOrThrow()
        val disabled = merchantRepository.updateMerchantAlias(created.publicId, enabled = false).getOrThrow()
        merchantRepository.deleteMerchantAlias(" ${created.publicId} ").getOrThrow()

        assertEquals("alias-1", listed.single().publicId)
        assertEquals("星巴克", apiService.merchantAliasRequests.first().canonicalMerchant)
        assertEquals("Starbucks", apiService.merchantAliasRequests.first().alias)
        assertEquals("alias-created", apiService.merchantAliasPatchTargets.single())
        assertEquals(false, apiService.merchantAliasRequests.last().enabled)
        assertEquals(false, disabled.enabled)
        assertEquals(listOf("alias-created"), apiService.merchantAliasDeleteTargets)
    }

    @Test
    fun expenseItemsAndSplitsUseV1DetailEndpoints() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val items = repository.fetchExpenseItems(9).getOrThrow()
        val replacedItems = repository.replaceExpenseItems(
            9,
            listOf(
                ExpenseItemDraft(
                    name = " 拿铁 ",
                    quantityText = " 1杯 ",
                    unitPriceCents = 500,
                    amountCents = 500,
                    category = "吃饭",
                    rawText = null,
                    confidence = null,
                ),
            ),
        ).getOrThrow()
        val splits = repository.fetchExpenseSplits(9).getOrThrow()
        val replacedSplits = repository.replaceExpenseSplits(
            9,
            listOf(ExpenseSplitDraft(memberId = 12, amountCents = 6000, note = " 一起吃饭 ")),
        ).getOrThrow()

        assertEquals(9L, apiService.itemFetchIds.single())
        assertEquals(9L, apiService.itemReplaceIds.single())
        assertEquals("拿铁", apiService.itemReplaceRequests.single().items.single().name)
        assertEquals("餐饮", apiService.itemReplaceRequests.single().items.single().category)
        assertEquals("item-1", items.items.single().publicId)
        assertEquals("item-1", replacedItems.items.single().publicId)
        assertEquals(9L, apiService.splitFetchIds.single())
        assertEquals(9L, apiService.splitReplaceIds.single())
        assertEquals("一起吃饭", apiService.splitReplaceRequests.single().splits.single().note)
        assertEquals("split-1", splits.splits.single().publicId)
        assertEquals("split-1", replacedSplits.splits.single().publicId)
    }

    @Test
    fun fetchExpenseUsesDetailEndpointAndCachesConfirmedRows() = runTest {
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.zen70.cn")
            saveIdentity(
                accountName = "Account",
                ledgerId = "owner",
                ledgerName = "Family Ledger",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val expense = repository.fetchExpense(9).getOrThrow()

        assertEquals(9L, expense.id)
        assertEquals("confirmed", expense.status)
        assertEquals(listOf(9L), apiService.expenseFetchIds)
        assertEquals(9L, dao.getConfirmed("owner").single().serverId)
    }

    @Test
    fun fetchExpenseSkipsConfirmedCacheWhenLedgerChangesDuringRequest() = runTest {
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.zen70.cn")
            saveIdentity(
                accountName = "Account",
                ledgerId = "owner",
                ledgerName = "Owner Ledger",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0).apply {
            onExpenseFetch = {
                settingsStore.saveIdentity(
                    accountName = "Account",
                    ledgerId = "family",
                    ledgerName = "Family Ledger",
                    deviceName = "Pixel",
                    role = "member",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            }
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val expense = repository.fetchExpense(9).getOrThrow()

        assertEquals("confirmed", expense.status)
        assertEquals(listOf(9L), apiService.expenseFetchIds)
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
    }


    @Test
    fun viewerCannotReplaceExpenseItemsOrSplitsLocally() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "只读",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "viewer",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val itemResult = repository.replaceExpenseItems(
            9,
            listOf(ExpenseItemDraft("拿铁", null, null, 500, "餐饮", null, null)),
        )
        val splitResult = repository.replaceExpenseSplits(
            9,
            listOf(ExpenseSplitDraft(memberId = 12, amountCents = 500, note = null)),
        )

        assertEquals("当前角色为只读，无法修改账本。", itemResult.exceptionOrNull()?.message)
        assertEquals("当前角色为只读，无法修改账本。", splitResult.exceptionOrNull()?.message)
        assertTrue(apiService.itemReplaceRequests.isEmpty())
        assertTrue(apiService.splitReplaceRequests.isEmpty())
    }
}

private class FakeApiServiceFactory(
    private val service: FakeApiService,
) : ApiServiceFactory {
    val tokenValues = mutableListOf<String?>()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        tokenValues += tokenProvider()
        return service
    }
}

private class FakeApiService(
    private val events: MutableList<String>,
    private var confirmedFailuresRemaining: Int,
    private val checkAuthResult: AuthCheckDto? = null,
    private val serverSettingsResult: ServerSettingsDto? = null,
) : ApiService {
    var lastNotificationDraftRequest: NotificationDraftRequestDto? = null
    var lastConfirmedMonth: String? = null
    var lastConfirmedCategory: String? = null
    var lastConfirmedTag: String? = null
    val confirmedResponses = mutableMapOf<Int, PaginatedExpensesDto>()
    val applyConfirmedRequests = mutableListOf<RuleApplyConfirmedRequestDto>()
    val rollbackPublicIds = mutableListOf<String>()
    val merchantAliasRequests = mutableListOf<MerchantAliasRequest>()
    val merchantAliasPatchTargets = mutableListOf<String>()
    val merchantAliasDeleteTargets = mutableListOf<String>()
    val itemFetchIds = mutableListOf<Long>()
    val itemReplaceIds = mutableListOf<Long>()
    val itemReplaceRequests = mutableListOf<ExpenseItemReplaceRequestDto>()
    val splitFetchIds = mutableListOf<Long>()
    val splitReplaceIds = mutableListOf<Long>()
    val splitReplaceRequests = mutableListOf<ExpenseSplitReplaceRequestDto>()
    val expenseFetchIds = mutableListOf<Long>()
    var onConfirmedRequest: (() -> Unit)? = null
    var onExpenseFetch: (() -> Unit)? = null
    var onCheckAuth: (() -> Unit)? = null

    override suspend fun pairDevice(request: PairRequestDto): PairResponseDto {
        return PairResponseDto(
            sessionToken = "session-token",
            accountName = "我",
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            deviceName = request.deviceName,
            role = "owner",
        )
    }

    override suspend fun confirmedExpenses(
        page: Int,
        pageSize: Int,
        month: String?,
        category: String?,
        tag: String?,
        timezone: String?,
    ): PaginatedExpensesDto {
        events += "syncConfirmed"
        lastConfirmedMonth = month
        lastConfirmedCategory = category
        lastConfirmedTag = tag
        onConfirmedRequest?.invoke()
        if (confirmedFailuresRemaining > 0) {
            confirmedFailuresRemaining -= 1
            throw IOException("restore unavailable")
        }
        confirmedResponses[page]?.let { return it }
        return PaginatedExpensesDto(
            items = listOf(confirmedExpenseDto()),
            page = page,
            pageSize = pageSize,
            total = 1,
        )
    }

    override suspend fun checkAuth(): AuthCheckDto {
        onCheckAuth?.invoke()
        return checkAuthResult ?: unsupported()
    }

    override suspend fun pendingExpenses(): List<ExpenseDto> = unsupported()

    override suspend fun categories(): CategoriesDto = unsupported()

    override suspend fun tags(): TagsDto = unsupported()

    override suspend fun months(timezone: String?): MonthsDto = unsupported()

    override suspend fun exportCsv(month: String?, category: String?, tag: String?, timezone: String?): Response<ResponseBody> = unsupported()

    override suspend fun createManualExpense(request: ExpenseUpdateRequest): ExpenseDto = unsupported()

    override suspend fun createNotificationDraft(request: NotificationDraftRequestDto): ExpenseDto {
        lastNotificationDraftRequest = request
        return ExpenseDto(
            id = 12,
            publicId = "8f939f48-e646-4afb-b54f-7bb6b536d9ef",
            amountCents = null,
            originalCurrency = request.originalCurrency,
            originalAmount = request.originalAmount,
            fxStatus = "pending",
            merchant = request.merchant,
            category = request.category ?: "其他",
            note = "",
            source = "通知草稿:微信",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = "",
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "pending",
            expenseTime = request.expenseTime,
            createdAt = "2026-05-13T10:05:00Z",
            updatedAt = "2026-05-13T10:05:00Z",
            confirmedAt = null,
            rejectedAt = null,
        )
    }

    override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?): UploadResponseDto = unsupported()

    override suspend fun expense(id: Long): ExpenseDto {
        expenseFetchIds += id
        onExpenseFetch?.invoke()
        return confirmedExpenseDto()
    }

    override suspend fun updateExpense(id: Long, request: ExpenseUpdateRequest): ExpenseDto = unsupported()

    override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto {
        itemFetchIds += id
        return expenseItemsResponse()
    }

    override suspend fun replaceExpenseItems(
        id: Long,
        request: ExpenseItemReplaceRequestDto,
    ): ExpenseItemsResponseDto {
        itemReplaceIds += id
        itemReplaceRequests += request
        return expenseItemsResponse()
    }

    override suspend fun expenseSplits(id: Long): ExpenseSplitsResponseDto {
        splitFetchIds += id
        return expenseSplitsResponse()
    }

    override suspend fun replaceExpenseSplits(
        id: Long,
        request: ExpenseSplitReplaceRequestDto,
    ): ExpenseSplitsResponseDto {
        splitReplaceIds += id
        splitReplaceRequests += request
        return expenseSplitsResponse()
    }

    override suspend fun confirmExpense(id: Long): ExpenseDto = unsupported()

    override suspend fun rejectExpense(id: Long): ExpenseDto = unsupported()

    override suspend fun retryOcr(id: Long): ExpenseDto = unsupported()

    override suspend fun markNotDuplicate(id: Long): ExpenseDto = unsupported()

    override suspend fun expenseImage(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun expenseThumbnail(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun duplicates(): List<ExpenseDto> = unsupported()

    override suspend fun categoryRules(): List<CategoryRuleDto> = emptyList()

    override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun updateCategoryRule(id: Long, request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun deleteCategoryRule(id: Long): StatusDto = unsupported()

    override suspend fun merchantAliases(): MerchantAliasListDto = MerchantAliasListDto(
        items = listOf(
            merchantAliasDto(
                publicId = "alias-1",
                canonicalMerchant = "星巴克",
                canonicalKey = "星巴克",
                alias = "Starbucks",
                aliasKey = "starbucks",
                enabled = true,
            ),
        ),
    )

    override suspend fun createMerchantAlias(request: MerchantAliasRequest): MerchantAliasDto {
        merchantAliasRequests += request
        return merchantAliasDto(
            publicId = "alias-created",
            canonicalMerchant = requireNotNull(request.canonicalMerchant),
            canonicalKey = requireNotNull(request.canonicalMerchant),
            alias = requireNotNull(request.alias),
            aliasKey = requireNotNull(request.alias).lowercase(),
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun updateMerchantAlias(
        publicId: String,
        request: MerchantAliasRequest,
    ): MerchantAliasDto {
        merchantAliasPatchTargets += publicId
        merchantAliasRequests += request
        return merchantAliasDto(
            publicId = publicId,
            canonicalMerchant = request.canonicalMerchant ?: "星巴克",
            canonicalKey = request.canonicalMerchant ?: "星巴克",
            alias = request.alias ?: "Starbucks",
            aliasKey = request.alias?.lowercase() ?: "starbucks",
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun deleteMerchantAlias(publicId: String): StatusDto {
        merchantAliasDeleteTargets += publicId
        return StatusDto("ok")
    }

    override suspend fun ruleApplications(limit: Int): RuleApplicationListDto = RuleApplicationListDto(
        items = listOf(
            RuleApplicationBatchDto(
                publicId = "batch-1",
                status = "applied",
                pendingScanned = 9,
                changedCount = 1,
                createdAt = "2026-05-13T00:00:00Z",
                rolledBackAt = null,
            ),
        ),
    )

    override suspend fun rollbackRuleApplication(publicId: String): RuleApplicationRollbackDto {
        rollbackPublicIds += publicId
        return RuleApplicationRollbackDto(
            publicId = publicId,
            status = "rolled_back",
            changed = 1,
            skipped = 0,
            rolledBackAt = "2026-05-13T00:05:00Z",
        )
    }

    override suspend fun applyConfirmedRules(
        request: RuleApplyConfirmedRequestDto,
        limit: Int,
        maxScan: Int,
    ): RuleApplyConfirmedResponseDto {
        applyConfirmedRequests += request
        return RuleApplyConfirmedResponseDto(
            dryRun = !request.confirm,
            confirmedScanned = 9,
            changedCount = 1,
            items = if (request.confirm) {
                emptyList()
            } else {
                listOf(
                    RuleApplyPreviewItemDto(
                        id = 9,
                        merchant = "高德",
                        currentCategory = "其他",
                        suggestedCategory = "交通",
                        ruleKeyword = "高德",
                        reason = "merchant matched",
                    ),
                )
            },
            noMatchCount = 8,
            scanLimit = maxScan,
            previewToken = if (request.confirm) null else "preview-token",
        )
    }

    override suspend fun serverSettings(): ServerSettingsDto = serverSettingsResult ?: ServerSettingsDto(
        accountName = "我",
        ledgerId = "old",
        ledgerName = "旧账本",
        ledgerIsDefault = false,
        deviceName = "旧设备",
        role = "owner",
        status = "ok",
        storageStatus = "ok",
        pendingCount = 0,
        confirmedCount = 0,
        rejectedCount = 0,
        suspectedDuplicateCount = 0,
        uploadStorageBytes = 0,
        latestUploadAt = null,
    )

    override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?): MonthlyStatsDto = unsupported()

    override suspend fun lifestyleStats(month: String?, timezone: String?): LifestyleStatsDto = unsupported()
    override suspend fun reportsOverview(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): ReportsOverviewDto = unsupported()
    override suspend fun reportsOverviewCsv(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): Response<ResponseBody> = unsupported()
    override suspend fun goals(
        month: String?,
        includeArchived: Boolean,
        timezone: String?,
    ): GoalListResponseDto = unsupported()
    override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?): GoalDto = unsupported()
    override suspend fun goal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun updateGoal(
        publicId: String,
        request: GoalUpdateRequestDto,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun archiveGoal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun dashboardCards(surface: String): DashboardCardsResponseDto = unsupported()
    override suspend fun updateDashboardCards(
        request: DashboardCardsUpdateRequestDto,
        surface: String,
    ): DashboardCardsResponseDto = unsupported()
    override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto = unsupported()
    override suspend fun updateMonthlyBudget(
        month: String,
        request: BudgetMonthlyUpdateRequestDto,
        timezone: String?,
    ): BudgetMonthlyDto = unsupported()
    override suspend fun recurringCandidates(timezone: String?): com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto = unsupported()
    override suspend fun recurringItems(
        status: String?,
        includeArchived: Boolean,
        month: String?,
        timezone: String?,
    ): RecurringItemListResponseDto = unsupported()
    override suspend fun confirmRecurringCandidate(
        request: RecurringCandidateConfirmRequestDto,
        timezone: String?,
    ): RecurringItemDto = unsupported()
    override suspend fun recurringItem(publicId: String, month: String?, timezone: String?): RecurringItemDto = unsupported()
    override suspend fun pauseRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun resumeRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun archiveRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun dataQualitySummary(): com.ticketbox.data.remote.dto.DataQualitySummaryDto = unsupported()

    override suspend fun getUiPreferences(): Response<UserUiPreferencesDto> = unsupported()

    override suspend fun putUiPreferences(
        request: UserUiPreferencesUpdateRequestDto,
    ): Response<UserUiPreferencesDto> = unsupported()

    override suspend fun listLedgers(): com.ticketbox.data.remote.dto.LedgerListResponseDto = unsupported()

    override suspend fun createLedger(request: com.ticketbox.data.remote.dto.LedgerCreateRequestDto): com.ticketbox.data.remote.dto.LedgerDto = unsupported()

    override suspend fun switchLedger(ledgerId: String): com.ticketbox.data.remote.dto.LedgerSwitchResponseDto = unsupported()

    override suspend fun ledgerMembers(
        ledgerId: String,
    ): com.ticketbox.data.remote.dto.LedgerMemberListResponseDto = unsupported()

    override suspend fun ledgerAudit(
        ledgerId: String,
        limit: Int,
    ): com.ticketbox.data.remote.dto.LedgerAuditListResponseDto = unsupported()

    override suspend fun updateLedgerMemberRole(
        ledgerId: String,
        memberId: Long,
        request: com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto,
    ): com.ticketbox.data.remote.dto.LedgerMemberDto = unsupported()

    override suspend fun disableLedgerMember(
        ledgerId: String,
        memberId: Long,
    ): com.ticketbox.data.remote.dto.LedgerMemberDto = unsupported()

    override suspend fun transferLedgerOwner(
        ledgerId: String,
        memberId: Long,
    ): com.ticketbox.data.remote.dto.OwnerTransferResponseDto = unsupported()

    override suspend fun previewInvitation(
        request: com.ticketbox.data.remote.dto.InvitationPreviewRequestDto,
    ): com.ticketbox.data.remote.dto.InvitationPreviewResponseDto = unsupported()

    override suspend fun acceptInvitation(
        request: com.ticketbox.data.remote.dto.InvitationAcceptRequestDto,
    ): com.ticketbox.data.remote.dto.InvitationAcceptResponseDto = unsupported()

    private fun merchantAliasDto(
        publicId: String,
        canonicalMerchant: String,
        canonicalKey: String,
        alias: String,
        aliasKey: String,
        enabled: Boolean,
    ): MerchantAliasDto = MerchantAliasDto(
        publicId = publicId,
        canonicalMerchant = canonicalMerchant,
        canonicalKey = canonicalKey,
        alias = alias,
        aliasKey = aliasKey,
        enabled = enabled,
        createdAt = "2026-05-13T00:00:00Z",
        updatedAt = "2026-05-13T00:05:00Z",
    )

    private fun expenseItemsResponse(): ExpenseItemsResponseDto = ExpenseItemsResponseDto(
        expenseId = 9,
        parentAmountCents = 1500,
        itemsTotalAmountCents = 500,
        mismatchCents = 1000,
        items = listOf(
            ExpenseItemDto(
                publicId = "item-1",
                position = 0,
                name = "拿铁",
                quantityText = "1杯",
                unitPriceCents = 500,
                amountCents = 500,
                category = "吃饭",
                rawText = null,
                confidence = null,
                isOcrDraft = false,
                createdAt = "2026-05-13T00:00:00Z",
                updatedAt = "2026-05-13T00:05:00Z",
            ),
        ),
    )

    private fun expenseSplitsResponse(): ExpenseSplitsResponseDto = ExpenseSplitsResponseDto(
        expenseId = 9,
        parentAmountCents = 1500,
        splitsTotalAmountCents = 6000,
        mismatchCents = -4500,
        splits = listOf(
            ExpenseSplitDto(
                publicId = "split-1",
                position = 0,
                memberId = 12,
                accountName = "家人",
                role = "member",
                amountCents = 6000,
                note = "一起吃饭",
                disabledAt = null,
                createdAt = "2026-05-13T00:00:00Z",
                updatedAt = "2026-05-13T00:05:00Z",
            ),
        ),
    )

    private fun confirmedExpenseDto(): ExpenseDto {
        return ExpenseDto(
            id = 9,
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            amountCents = 175479,
            merchant = "高德",
            category = "交通",
            note = "",
            source = "Android截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = "2026-05-07T07:29:00Z",
            createdAt = "2026-05-09T08:08:13Z",
            updatedAt = "2026-05-09T08:12:40Z",
            confirmedAt = "2026-05-09T08:12:40Z",
            rejectedAt = null,
        )
    }
}

private fun boundSettingsStore(): FakeTicketboxSettingsStore =
    FakeTicketboxSettingsStore().apply {
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

private fun cachedConfirmedEntity(
    serverId: Long,
    publicId: String,
    merchant: String,
    ledgerId: String = "owner",
): ExpenseEntity =
    ExpenseEntity(
        ledgerId = ledgerId,
        serverId = serverId,
        publicId = publicId,
        amountCents = 1200,
        merchant = merchant,
        category = "交通",
        note = null,
        source = "缓存",
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-05-01T00:00:00Z",
        createdAt = "2026-05-01T00:00:00Z",
        confirmedAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
    )

private class FakeTicketboxSettingsStore(
    private val events: MutableList<String> = mutableListOf(),
) : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var accountName: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    private var ledgerName: String? = null
    private var availableLedgersJson: String? = null
    private var deviceName: String? = null
    private var role: String? = null
    private var boundAt: String? = null
    private var lastConfirmedSyncAt: String? = null
    private var lastUploadAt: String? = null
    private var monthlyBudgetCents: Long? = null
    private var appSkinKey: String? = null

    override fun serverUrl(): String? = serverUrl

    override fun appSkinKey(): String? = appSkinKey

    override fun monthlyBudgetCents(): Long? = monthlyBudgetCents

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        monthlyBudgetCents = amountCents
    }

    override fun lastConfirmedSyncAt(): String? = lastConfirmedSyncAt

    override fun accountName(): String? = accountName

    override fun ledgerName(): String? = ledgerName

    override fun activeLedgerId(): String? = ledgerIdFlow.value

    override fun activeLedgerName(): String? = ledgerName

    override fun availableLedgersJson(): String? = availableLedgersJson

    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        events += "saveActiveLedger"
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }

    override fun saveAvailableLedgersJson(json: String?) {
        availableLedgersJson = json
    }

    override fun deviceName(): String? = deviceName

    override fun role(): String? = role

    override fun boundAt(): String? = boundAt

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        events += "saveIdentity"
        this.accountName = accountName
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
        this.deviceName = deviceName
        this.role = role
        this.boundAt = boundAt
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        lastConfirmedSyncAt = value
    }

    override fun clearLastConfirmedSyncAt() {
        lastConfirmedSyncAt = null
    }

    override fun lastUploadAt(): String? = lastUploadAt

    override fun saveLastUploadAt(value: String) {
        lastUploadAt = value
    }

    override fun saveAppSkinKey(skinKey: String) {
        appSkinKey = skinKey
    }

    override fun currencyCodeKey(): String? = null

    override fun saveCurrencyCodeKey(currencyKey: String) = Unit

    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)

    override fun saveServerUrl(serverUrl: String) {
        events += "saveServerUrl"
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }

    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()

    override fun markUnlocked() = Unit

    override fun markBackgrounded() = Unit

    override fun requiresUnlock(): Boolean = false

    override fun clear() {
        serverUrl = null
        accountName = null
        ledgerIdFlow.value = null
        ledgerName = null
        deviceName = null
        role = null
        boundAt = null
        lastConfirmedSyncAt = null
        lastUploadAt = null
    }
}

private class FakeSessionTokenStore(
    private val events: MutableList<String> = mutableListOf(),
) : SessionTokenStore {
    private var token: String? = null

    override fun saveToken(token: String) {
        events += "saveToken"
        this.token = token
    }

    override fun getToken(): String? = token

    override fun clear() {
        token = null
    }
}

private class FakeExpenseDao : ExpenseDao {
    private val expenses = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    private var nextId = 1L

    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)

    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
    }

    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? {
        return expenses.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    }

    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.ledgerId == ledgerId && it.serverId in wanted }
    }

    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.serverId }
    }

    override suspend fun insert(expense: ExpenseEntity): Long {
        val id = if (expense.id == 0L) nextId++ else expense.id
        expenses[id] = expense.copy(id = id)
        emit(expense.ledgerId)
        return id
    }

    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> {
        return expenses.map { insert(it) }
    }

    override suspend fun update(expense: ExpenseEntity) {
        expenses[expense.id] = expense
        emit(expense.ledgerId)
    }

    override suspend fun updateAll(expenses: List<ExpenseEntity>) {
        expenses.forEach { update(it) }
    }

    override suspend fun clear() {
        val touched = expenses.values.map { it.ledgerId }.toSet()
        expenses.clear()
        touched.forEach { emit(it) }
    }

    override suspend fun clearForLedger(ledgerId: String) {
        expenses.values
            .filter { it.ledgerId == ledgerId }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(snapshot(ledgerId)) }

    private fun snapshot(ledgerId: String): List<ExpenseEntity> =
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }

    private fun emit(ledgerId: String) {
        flowFor(ledgerId).value = snapshot(ledgerId)
    }
}

private fun unsupported(): Nothing = error("Unexpected API call")

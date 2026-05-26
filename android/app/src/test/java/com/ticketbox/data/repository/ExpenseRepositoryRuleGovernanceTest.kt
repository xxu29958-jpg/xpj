package com.ticketbox.data.repository

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryRuleGovernanceTest {
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
        // ADR-0038 PR-2e: PATCH/DELETE require the token; pass the freshly
        // created alias's updatedAt so the fixture sees a real token shape.
        val disabled = merchantRepository.updateMerchantAlias(
            publicId = created.publicId,
            expectedUpdatedAt = created.updatedAt,
            enabled = false,
        ).getOrThrow()
        merchantRepository.deleteMerchantAlias(
            publicId = " ${created.publicId} ",
            expectedUpdatedAt = disabled.updatedAt,
        ).getOrThrow()

        assertEquals("alias-1", listed.single().publicId)
        assertEquals("星巴克", apiService.merchantAliasRequests.first().canonicalMerchant)
        assertEquals("Starbucks", apiService.merchantAliasRequests.first().alias)
        assertEquals("alias-created", apiService.merchantAliasPatchTargets.single())
        assertEquals(false, apiService.merchantAliasUpdateRequests.single().enabled)
        assertEquals(created.updatedAt, apiService.merchantAliasUpdateRequests.single().expectedUpdatedAt)
        assertEquals(false, disabled.enabled)
        assertEquals(listOf("alias-created"), apiService.merchantAliasDeleteTargets)
        assertEquals(disabled.updatedAt, apiService.merchantAliasDeleteRequests.single().expectedUpdatedAt)
    }
}

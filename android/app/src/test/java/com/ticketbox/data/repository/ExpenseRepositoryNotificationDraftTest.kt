package com.ticketbox.data.repository

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryNotificationDraftTest {
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
        val apiClient = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiClient,
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
        assertEquals(listOf<String?>("session-token"), apiClient.tokenValues)
        assertEquals(emptyList(), dao.getConfirmed("owner"))
    }

    @Test
    fun notificationDraftDoesNotPostAfterLedgerSwitch() = runTest {
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
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-owner") }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )
        val ledgerIdAtNotification = repository.currentActiveLedgerId()
        tokenStore.saveToken("session-family")
        settingsStore.saveIdentity(
            accountName = "我",
            ledgerId = "family",
            ledgerName = "家庭账本",
            deviceName = "Pixel",
            role = "member",
            boundAt = "2026-05-01T00:05:00Z",
        )

        val result = repository.createNotificationDraft(
            NotificationDraft(
                source = NotificationDraftSource.WeChat,
                amountCents = 2680,
                merchant = "星巴克",
                category = "餐饮",
                expenseTime = "2026-05-13T10:05:00Z",
            ),
            expectedLedgerId = ledgerIdAtNotification,
        )

        assertEquals("账本已切换，请重新操作。", result.exceptionOrNull()?.message)
        assertNull(apiService.lastNotificationDraftRequest)
    }
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryNotificationDraftTest {
    @Test
    fun notificationDraftUploadsStructuredFieldsOnlyAndDoesNotCachePending() = runTest {
        val dao = FakeExpenseDao()
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
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val apiClient = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            binding = testServerSessionBinding(
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = TestSessionFixture().apply { saveToken("session-token") },
            ),
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
            expectedBinding = assertNotNull(repository.captureDeferredLedgerBinding()),
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
        val tokenStore = TestSessionFixture().apply { saveToken("session-owner") }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(apiService),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
            deviceNameProvider = { "Android Test Device" },
        )
        val bindingAtNotification = assertNotNull(repository.captureDeferredLedgerBinding())
        tokenStore.switchLedgerForFixture("family", "家庭账本", role = "member")

        val result = repository.createNotificationDraft(
            NotificationDraft(
                source = NotificationDraftSource.WeChat,
                amountCents = 2680,
                merchant = "星巴克",
                category = "餐饮",
                expenseTime = "2026-05-13T10:05:00Z",
            ),
            expectedBinding = bindingAtNotification,
        )

        assertEquals("账本已切换，请重新操作。", result.exceptionOrNull()?.message)
        assertNull(apiService.lastNotificationDraftRequest)
    }

    @Test
    fun notificationDraftDoesNotCrossPrincipalWithSameLedgerId() = runTest {
        val tokenStore = TestSessionFixture().apply { saveToken("session-owner") }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(apiService),
                settingsStore = boundSettingsStore(),
                tokenStore = tokenStore,
            ),
            deviceNameProvider = { "Android Test Device" },
        )
        val bindingAtNotification = assertNotNull(repository.captureDeferredLedgerBinding())
        tokenStore.rebindAsDifferentAccountForFixture(
            accountName = "家人",
            ledgerId = "owner",
            ledgerName = "另一个服务器的默认账本",
            deviceName = "Replacement Phone",
            token = "replacement-session",
        )

        val result = repository.createNotificationDraft(
            draft = NotificationDraft(
                source = NotificationDraftSource.WeChat,
                amountCents = 2680,
                merchant = "星巴克",
                category = "餐饮",
                expenseTime = "2026-05-13T10:05:00Z",
            ),
            expectedBinding = bindingAtNotification,
        )

        assertEquals("账本已切换，请重新操作。", result.exceptionOrNull()?.message)
        assertNull(apiService.lastNotificationDraftRequest)
    }
}

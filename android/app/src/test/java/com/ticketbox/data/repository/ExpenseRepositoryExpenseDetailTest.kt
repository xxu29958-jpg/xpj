package com.ticketbox.data.repository

import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseSplitDraft
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryExpenseDetailTest {
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
    fun fetchExpenseRejectsLateLedgerSwitchAndSkipsConfirmedCache() = runTest {
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

        val failure = repository.fetchExpense(9).exceptionOrNull()

        assertEquals("账本已切换，请重新操作。", failure?.message)
        assertEquals(listOf(9L), apiService.expenseFetchIds)
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
    }

    @Test
    fun confirmExpenseUsesFrozenTokenAndRejectsLateLedgerSwitch() = runTest {
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
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-owner") }
        val apiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0).apply {
            onConfirmExpense = {
                tokenStore.saveToken("session-family")
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
        val apiClient = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiClient,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val failure = repository.confirmExpense(9).exceptionOrNull()

        assertEquals("账本已切换，请重新操作。", failure?.message)
        assertEquals(listOf(9L), apiService.confirmExpenseIds)
        assertEquals(listOf<String?>("session-owner"), apiClient.tokenValues)
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
    }

    @Test
    fun markNotDuplicateRefreshesConfirmedCacheForActiveLedger() = runTest {
        val dao = FakeExpenseDao()
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
            settingsStore = boundSettingsStore(),
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.markNotDuplicate(9).getOrThrow()

        assertEquals(9L, result.id)
        assertEquals(listOf(9L), dao.getConfirmed("owner").map { it.serverId })
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

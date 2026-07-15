package com.ticketbox.data.repository

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class LedgerRepositoryRefreshTest {

    @Test
    fun refreshLedgersPersistsJsonAndExposesSummaries() = runTest {
        val ledgers = listOf(
            ledgerDto("L_owner", "我的小票夹", role = "owner", isDefault = true),
            ledgerDto("L_house", "家庭账本", role = "viewer", isDefault = false),
        )
        val api = StubApi(LedgerStubApiState(listLedgersResult = LedgerListResponseDto(ledgers)))
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val dao = LedgerFakeDao()
        val repo = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val refreshed = repo.refreshLedgers().getOrThrow()
        assertEquals(listOf("L_owner", "L_house"), refreshed.map { it.ledgerId })
        // Cached read returns the same list without hitting the network.
        api.listLedgersResult = null
        val cached = repo.cachedLedgers()
        assertEquals(listOf("L_owner", "L_house"), cached.map { it.ledgerId })
    }

    @Test
    fun refreshLedgersPersistsActiveLedgerRoleChange() = runTest {
        val api = StubApi(
            LedgerStubApiState(
                listLedgersResult = LedgerListResponseDto(
                    ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "viewer", isDefault = true)),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    deviceName = "Pixel",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val session = ledgerSessionFixture("L_family", "家庭账本", role = "owner", token = "t")
        val repo = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = session,
            expenseDao = LedgerFakeDao(),
        )

        val ledgers = repo.refreshLedgers().getOrThrow()

        assertEquals("viewer", ledgers.single().role)
        assertEquals("viewer", repo.currentLedgerRole())
        assertEquals("L_family", repo.activeLedgerId())
    }

    @Test
    fun refreshLedgersSlowResponseDoesNotOverwriteCacheAfterBindingChanges() = runTest {
        val oldLedgers = listOf(ledgerDto("L_old", "旧账本", role = "viewer", isDefault = true))
        val api = StubApi(LedgerStubApiState(listLedgersResult = LedgerListResponseDto(oldLedgers)))
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "旧账号",
                    ledgerId = "L_old",
                    ledgerName = "旧账本",
                    deviceName = "Old Pixel",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
            saveAvailableLedgersJson(
                """
                [
                  {
                    "ledger_id": "L_new",
                    "name": "新账本",
                    "role": "owner",
                    "is_default": true,
                    "created_at": "2026-01-01T00:00:00Z",
                    "archived_at": null
                  }
                ]
                """.trimIndent(),
            )
        }
        val tokenStore = existingOwnerSessionFixture(
            ledgerId = "L_old",
            ledgerName = "旧账本",
            accountName = "旧账号",
            deviceName = "Old Pixel",
            token = "old-token",
        )
        api.onListLedgers = {
            tokenStore.rebindAsDifferentAccountForFixture(
                accountName = "新账号",
                ledgerId = "L_new",
                ledgerName = "新账本",
                deviceName = "New Pixel",
                token = "new-token",
            )
        }
        val repo = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.refreshLedgers().exceptionOrNull()

        assertEquals(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE, failure?.message)
        assertEquals("L_new", repo.activeLedgerId())
        assertEquals("owner", repo.currentLedgerRole())
        assertEquals(listOf("L_new"), repo.cachedLedgers().map { it.ledgerId })
    }

    @Test
    fun refreshLedgersWrapsRuntimeExceptions() = runTest {
        val repo = testLedgerRepository(
            apiClient = LedgerStubApiFactory(StubApi(LedgerStubApiState(listLedgersError = RuntimeException("json bad")))),
            settingsStore = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") },
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.refreshLedgers().exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("json bad"))
    }

    private fun ledgerDto(
        id: String,
        name: String,
        role: String = "owner",
        isDefault: Boolean = false,
    ) = LedgerDto(
        ledgerId = id,
        name = name,
        role = role,
        isDefault = isDefault,
        createdAt = "2026-01-01T00:00:00Z",
        archivedAt = null,
    )
}

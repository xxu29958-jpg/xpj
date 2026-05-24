package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LedgerRepositoryMutationTest {

    @Test
    fun createLedgerRejectsBlankNameWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.createLedger("   ").exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("请填写账本名称"))
    }

    @Test
    fun createLedgerRejectsOversizeNameWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.createLedger("帐".repeat(61)).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("最多 60 个字"))
    }

    @Test
    fun switchLedgerRotatesTokenAndClearsTargetCacheFirst() = runTest {
        val newToken = "session-token-new"
        val api = StubApi(
            switchResult = LedgerSwitchResponseDto(
                sessionToken = newToken,
                ledger = ledgerDto("L_house", "家庭账本", role = "viewer"),
                accountName = "我",
                deviceName = "Pixel",
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val dao = LedgerFakeDao().apply {
            // Pre-seed the cache for both ledgers.
            insertEntity(ledgerEntity(id = 1, ledgerId = "L_owner", serverId = 100))
            insertEntity(ledgerEntity(id = 2, ledgerId = "L_house", serverId = 200))
        }
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val summary = repo.switchLedger("L_house").getOrThrow()
        assertEquals("L_house", summary.ledgerId)
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_house", store.activeLedgerId())
        assertEquals("viewer", store.capturedRole)
        // Only the target ledger's rows are wiped; the other ledger keeps its cache.
        assertNull(dao.find(2))
        assertNotNull(dao.find(1))
    }

    @Test
    fun switchLedgerFailurePreservesOldToken() = runTest {
        val errorJson = "{\"error\":\"forbidden\",\"message\":\"无权访问该账本\"}"
        val api = StubApi(
            switchError = HttpException(
                Response.error<Any>(403, errorJson.toResponseBody("application/json".toMediaType())),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.switchLedger("L_house").exceptionOrNull()
        assertNotNull(failure)
        assertEquals("old-token", tokenStore.getToken())
        assertNull(store.activeLedgerId())
        assertFalse(failure.message.isNullOrBlank())
    }

    @Test
    fun concurrentSwitchLedgerRequestsAreSerializedSoLatestCallWins() = runTest {
        val firstStarted = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val api = StubApi(
            switchHandler = { ledgerId ->
                if (ledgerId == "L_first") {
                    firstStarted.complete(Unit)
                    releaseFirst.await()
                }
                LedgerSwitchResponseDto(
                    sessionToken = "token-$ledgerId",
                    ledger = ledgerDto(ledgerId, ledgerId, role = "owner"),
                    accountName = "我",
                    deviceName = "Pixel",
                )
            },
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val first = async { repo.switchLedger("L_first") }
        firstStarted.await()
        val second = async { repo.switchLedger("L_second") }
        yield()

        assertEquals(listOf("L_first"), api.switchRequests)
        releaseFirst.complete(Unit)

        assertEquals("L_first", first.await().getOrThrow().ledgerId)
        assertEquals("L_second", second.await().getOrThrow().ledgerId)
        assertEquals(listOf("L_first", "L_second"), api.switchRequests)
        assertEquals("token-L_second", tokenStore.getToken())
        assertEquals("L_second", store.activeLedgerId())
    }

    @Test
    fun switchLedgerSlowResponseDoesNotOverwriteBindingChangedDuringRequest() = runTest {
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "旧账号",
                ledgerId = "L_old",
                ledgerName = "旧账本",
                deviceName = "Old Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val api = StubApi(
            switchHandler = { ledgerId ->
                tokenStore.saveToken("new-token")
                store.saveIdentity(
                    accountName = "新账号",
                    ledgerId = "L_new",
                    ledgerName = "新账本",
                    deviceName = "New Pixel",
                    role = "owner",
                    boundAt = "2026-05-01T00:05:00Z",
                )
                LedgerSwitchResponseDto(
                    sessionToken = "switched-token",
                    ledger = ledgerDto(ledgerId, "家庭账本", role = "viewer"),
                    accountName = "旧账号",
                    deviceName = "Old Pixel",
                )
            },
        )
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.switchLedger("L_house").exceptionOrNull()

        assertNotNull(failure)
        assertEquals("new-token", tokenStore.getToken())
        assertEquals("L_new", store.activeLedgerId())
        assertEquals("新账号", store.accountName())
    }

    private fun makeRepo(): LedgerRepository {
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("t") }
        return LedgerRepository(
            apiClient = LedgerStubApiFactory(StubApi()),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )
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

package com.ticketbox.viewmodel

import com.ticketbox.data.local.PersistedLedgerIdentity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.MerchantCreationKind
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.fakeMerchantCreationDraftStore
import com.ticketbox.data.repository.ledgerSessionFixture
import com.ticketbox.data.repository.testServerSessionBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class MerchantCreationControllerTest {
    @Test fun recreatedControllerKeepsBothOriginalInputsAndAcceptedReceiptAfterLostReply() = runTest {
        for (kind in MerchantCreationKind.entries) {
            val keys = mutableListOf<String>()
            val bodies = mutableListOf<List<String>>()
            val accepted = mutableMapOf<String, Any>()
            val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
                override suspend fun createMerchantCatalog(request: MerchantCatalogCreateRequest, idempotencyKey: String): MerchantCatalogDto {
                    keys += idempotencyKey; bodies += listOf(request.displayName)
                    val receipt = accepted.getOrPut(idempotencyKey) {
                        MerchantCatalogDto("original-catalog", request.displayName.trim(), "original", "active",
                            usageCount = 0, createdAt = "2026-10-08T00:00:00Z", updatedAt = "2026-10-08T00:00:00Z", rowVersion = 1)
                    } as MerchantCatalogDto
                    if (keys.size == 1) throw IOException("response lost after acceptance")
                    return receipt
                }
                override suspend fun createMerchantAlias(request: MerchantAliasRequest, idempotencyKey: String): MerchantAliasDto {
                    keys += idempotencyKey; bodies += listOf(requireNotNull(request.canonicalMerchant), requireNotNull(request.alias))
                    val receipt = accepted.getOrPut(idempotencyKey) {
                        MerchantAliasDto("original-alias", requireNotNull(request.canonicalMerchant).trim(), "original", requireNotNull(request.alias).trim(), "alias", true,
                            "2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z", 1)
                    } as MerchantAliasDto
                    if (keys.size == 1) throw IOException("response lost after acceptance")
                    return receipt
                }
            }
            val settings = FakeTicketboxSettingsStore().apply {
                saveServerUrl("https://api.example.com")
                saveIdentity(PersistedLedgerIdentity("Owner", "owner", "Ledger", "Device", "owner", "2026-10-08T00:00:00Z"))
            }
            var refuseRemoval = false
            val repository = MerchantRepository(testServerSessionBinding(apiClient = object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
            },
                settingsStore = settings, tokenStore = ledgerSessionFixture("owner", "Ledger")),
                fakeMerchantCreationDraftStore { if (refuseRemoval) throw IOException("Local receipt removal failed") })
            val firstScope = CoroutineScope(coroutineContext + SupervisorJob())
            val first = MerchantCreationController(repository, firstScope) {}
            first.state.first { it.ready && it.canModify }
            first.edit(kind, "  原商家  ", "  标准商家  ", "  原别名  ")
            first.submit(kind)
            first.state.first { it.draft(kind)?.phase == "unconfirmed" && !it.busy }
            val original = requireNotNull(first.state.value.draft(kind))
            assertEquals("unconfirmed", original.phase)
            assertFalse(first.state.value.canEdit(kind))
            first.edit(kind, "不能覆盖未知结果")
            assertEquals(original, first.state.value.draft(kind))
            firstScope.cancel()

            val resumedScope = CoroutineScope(coroutineContext + SupervisorJob())
            var completed = 0
            val resumed = MerchantCreationController(repository, resumedScope) { completed++ }
            resumed.state.first { it.ready && it.canModify }
            assertEquals(original, resumed.state.value.draft(kind))
            resumed.submit(kind)
            resumed.state.first { it.draft(kind)?.phase == "accepted" && !it.busy }
            assertEquals(listOf(original.key, original.key), keys)
            assertEquals(bodies.first(), bodies.last())
            assertEquals(1, accepted.size)
            assertEquals("accepted", resumed.state.value.draft(kind)?.phase)
            resumed.submit(kind); advanceUntilIdle()
            assertEquals(2, keys.size)
            assertEquals(0, completed)
            resumed.acknowledge(kind, "wrong-key"); advanceUntilIdle()
            assertEquals(0, completed)
            refuseRemoval = true
            resumed.acknowledge(kind, original.key)
            resumed.state.first { it.error != null && !it.busy }
            assertEquals("accepted", repository.readCreationDrafts(original.binding).getOrThrow().single().phase)
            assertEquals(0, completed)
            assertEquals(2, keys.size)
            refuseRemoval = false
            resumed.acknowledge(kind, original.key)
            resumed.state.first { it.draft(kind) == null && !it.busy }
            assertEquals(1, completed)
            assertNull(resumed.state.value.draft(kind))
            assertEquals(emptyList(), repository.readCreationDrafts(original.binding).getOrThrow())
            resumedScope.cancel()
        }
    }
}

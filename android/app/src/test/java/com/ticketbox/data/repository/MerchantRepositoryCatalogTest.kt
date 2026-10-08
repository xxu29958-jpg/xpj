package com.ticketbox.data.repository

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDeleteRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeRequest
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class MerchantRepositoryCatalogTest {

    private fun settingsStore(role: String = "owner"): FakeTicketboxSettingsStore =
        FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "owner",
                    ledgerName = "我的小票夹",
                    deviceName = "Pixel",
                    role = role,
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }

    private fun tokenStore(): TestSessionFixture =
        TestSessionFixture().apply { saveToken("session-token") }

    private fun repository(
        api: ApiService,
        outbox: OutboxRepository? = null,
    ): MerchantRepository = MerchantRepository(
        binding = testServerSessionBinding(
            apiClient = TestApiServiceFactory(api),
            settingsStore = settingsStore(),
            tokenStore = tokenStore(),
        ),
        offlineMutations = MerchantAliasOfflineMutationWiring(
            outbox = outbox,
        ),
    )

    @Test
    fun `merchantCatalog forwards includeHidden and maps catalog dto`() = runTest {
        val api = CatalogApiServiceStub().apply {
            catalogItems = listOf(
                merchantCatalogDto(
                    publicId = "catalog-hidden",
                    displayName = "隐藏店",
                    status = "hidden",
                ).copy(deletedAt = "2026-06-30T00:00:00Z"),
            )
        }

        val catalog = repository(api).merchantCatalog(includeHidden = false).getOrThrow()

        assertEquals(listOf(false), api.includeHiddenRequests)
        assertEquals("catalog-hidden", catalog.single().publicId)
        assertEquals("hidden", catalog.single().status)
        assertEquals(false, catalog.single().isActive)
        assertEquals("2026-06-30T00:00:00Z", catalog.single().deletedAt)
    }

    @Test
    fun `creation sends original name and key with default active status`() = runTest {
        val api = CatalogApiServiceStub()

        val merchant = repository(api)
        val created = requireNotNull(merchant.submitDraft(MerchantDraft(
            requireNotNull(merchant.captureBinding()), MerchantDraftKind.Catalog, "catalog-original-key", displayName = "  蓝瓶咖啡  ")).getOrThrow().catalogReceipt)

        assertEquals("  蓝瓶咖啡  ", api.createRequests.single().displayName)
        assertEquals("active", api.createRequests.single().status)
        assertEquals("蓝瓶咖啡", created.displayName)
        assertEquals("active", created.status)
    }

    @Test
    fun `rename and visibility retain distinct original bodies OCC and keys`() = runTest {
        val api = CatalogApiServiceStub()
        val repo = repository(api)
        val source = merchantCatalogDto().copy(rowVersion = 7).toDomain()
        val rename = MerchantDraft(requireNotNull(repo.captureBinding()), MerchantDraftKind.Rename, "original-rename",
            source = source, displayName = "  星巴克臻选  ")
        val updated = repo.submitDraft(rename).getOrThrow()
        assertEquals("catalog-1", api.updateTargets.single())
        assertEquals(7L, api.updateRequests.single().expectedRowVersion)
        assertEquals("  星巴克臻选  ", api.updateRequests.single().displayName)
        assertEquals(null, api.updateRequests.single().status)
        assertEquals("original-rename", api.updateIdempotencyKeys.single())
        assertEquals(8L, updated.catalogReceipt?.rowVersion)
        repo.submitDraft(rename.copy(kind = MerchantDraftKind.Visibility, key = "original-visibility", nextStatus = "hidden")).getOrThrow()
        assertEquals("hidden", api.updateRequests.last().status)
        assertEquals(null, api.updateRequests.last().displayName)
        assertEquals("original-visibility", api.updateIdempotencyKeys.last())
    }

    @Test
    fun `delete network failure keeps its original key without enqueuing another catalog writer`() = runTest {
        val api = CatalogApiServiceStub().apply { deleteFailure = IOException("network down") }
        val dao = FakePendingMutationDao()
        val repo = repository(api, outbox = testOutboxRepository(dao))
        val result = repo.submitDraft(MerchantDraft(requireNotNull(repo.captureBinding()), MerchantDraftKind.Delete, "original-delete",
            source = merchantCatalogDto().copy(rowVersion = 3).toDomain()))
        assertTrue(result.isFailure)
        assertEquals(listOf("catalog-1"), api.deleteTargets)
        assertEquals(3L, api.deleteRequests.single().expectedRowVersion)
        assertEquals("original-delete", api.deleteIdempotencyKeys.single())
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `merge sends original key dual OCC tokens and explicit alias policy`() = runTest {
        val api = CatalogApiServiceStub()
        val repo = repository(api)
        val result = requireNotNull(repo.submitDraft(MerchantDraft(requireNotNull(repo.captureBinding()), MerchantDraftKind.Merge, "original-merge",
            source = merchantCatalogDto("source").copy(rowVersion = 3).toDomain(),
            target = merchantCatalogDto("target").copy(rowVersion = 9).toDomain(),
            aliasPolicy = MerchantCatalogAliasPolicy.CreateSourceAlias)).getOrThrow().mergeReceipt)
        assertEquals(listOf("source"), api.mergeTargets)
        val request = api.mergeRequests.single()
        assertEquals("original-merge", api.mergeKeys.single())
        assertEquals(3L, request.expectedRowVersion)
        assertEquals("target", request.targetPublicId)
        assertEquals(9L, request.targetRowVersion)
        assertEquals("create_source_alias", request.aliasPolicy)
        assertEquals(false, request.rewriteHistoricalExpenses)
        assertEquals("merged", result.source.status)
        assertEquals("target", result.source.mergedIntoPublicId)
        assertEquals("alias-created-by-merge", result.createdAliasPublicId)
    }

    @Test fun originalCatalogBindingCannotReadOrWriteThroughAnotherIdentity() = runTest {
        val api = CatalogApiServiceStub()
        val repository = repository(api)
        val current = requireNotNull(repository.captureBinding())
        val otherBindings = listOf(current.copy(serverUrl = "https://other.example.com"), current.copy(ledgerId = "other-ledger"),
            current.copy(ownerKey = "other-owner"), current.copy(sessionGeneration = "new-session"), current.copy(bindingRevision = "new-binding"))
        val source = merchantCatalogDto().copy(rowVersion = 7).toDomain()
        for (original in otherBindings) {
            assertTrue(repository.merchantCatalog(expectedBinding = original).isFailure)
            for (kind in listOf(MerchantDraftKind.Rename, MerchantDraftKind.Visibility, MerchantDraftKind.Delete, MerchantDraftKind.Merge)) {
                assertTrue(repository.submitDraft(MerchantDraft(original, kind, "original-key", source = source, displayName = "原稿",
                    nextStatus = "hidden", target = source.copy(publicId = "target"), aliasPolicy = MerchantCatalogAliasPolicy.None)).isFailure)
            }
        }
        assertTrue(api.includeHiddenRequests.isEmpty())
        assertTrue(api.updateRequests.isEmpty())
        assertTrue(api.deleteRequests.isEmpty())
        assertTrue(api.mergeRequests.isEmpty())
        assertTrue(repository.merchantCatalog(expectedBinding = current).isSuccess)
        assertEquals(8L, repository.submitDraft(MerchantDraft(current, MerchantDraftKind.Rename, "valid", source = source,
            displayName = "原稿")).getOrThrow().catalogReceipt?.rowVersion)
    }

    private class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private class CatalogApiServiceStub(
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var catalogItems: List<MerchantCatalogDto> = listOf(merchantCatalogDto())
        var deleteFailure: Throwable? = null
        val includeHiddenRequests = mutableListOf<Boolean>()
        val createRequests = mutableListOf<MerchantCatalogCreateRequest>()
        val updateTargets = mutableListOf<String>()
        val updateRequests = mutableListOf<MerchantCatalogUpdateRequest>()
        val updateIdempotencyKeys = mutableListOf<String?>()
        val deleteTargets = mutableListOf<String>()
        val deleteRequests = mutableListOf<MerchantCatalogDeleteRequest>()
        val deleteIdempotencyKeys = mutableListOf<String?>()
        val mergeTargets = mutableListOf<String>()
        val mergeRequests = mutableListOf<MerchantCatalogMergeRequest>()
        val mergeKeys = mutableListOf<String>()

        override suspend fun merchantCatalog(includeHidden: Boolean): MerchantCatalogListDto {
            includeHiddenRequests += includeHidden
            return MerchantCatalogListDto(items = catalogItems)
        }

        override suspend fun createMerchantCatalog(request: MerchantCatalogCreateRequest, idempotencyKey: String): MerchantCatalogDto {
            createRequests += request
            return merchantCatalogDto(
                publicId = "catalog-created",
                displayName = request.displayName.trim(),
                status = request.status,
            )
        }

        override suspend fun updateMerchantCatalog(
            publicId: String,
            request: MerchantCatalogUpdateRequest,
            idempotencyKey: String?,
        ): MerchantCatalogDto {
            updateTargets += publicId
            updateRequests += request
            updateIdempotencyKeys += idempotencyKey
            return merchantCatalogDto(
                publicId = publicId,
                displayName = request.displayName ?: "星巴克",
                status = request.status ?: "active",
            ).copy(rowVersion = request.expectedRowVersion + 1)
        }

        override suspend fun deleteMerchantCatalog(
            publicId: String,
            request: MerchantCatalogDeleteRequest,
            idempotencyKey: String?,
        ): MerchantCatalogDto {
            deleteTargets += publicId
            deleteRequests += request
            deleteIdempotencyKeys += idempotencyKey
            deleteFailure?.let { throw it }
            return merchantCatalogDto(
                publicId = publicId,
                displayName = "星巴克",
                status = "active",
            ).copy(deletedAt = "2026-06-30T00:00:00Z")
        }

        override suspend fun mergeMerchantCatalog(
            sourcePublicId: String,
            request: MerchantCatalogMergeRequest,
            idempotencyKey: String,
        ): MerchantCatalogMergeDto {
            mergeTargets += sourcePublicId
            mergeRequests += request
            mergeKeys += idempotencyKey
            return MerchantCatalogMergeDto(
                source = merchantCatalogDto(
                    publicId = sourcePublicId,
                    displayName = "星巴克",
                    status = "merged",
                ).copy(
                    rowVersion = request.expectedRowVersion + 1,
                    mergedIntoPublicId = request.targetPublicId,
                ),
                target = merchantCatalogDto(
                    publicId = request.targetPublicId,
                    displayName = "蓝瓶咖啡",
                    status = "active",
                ).copy(rowVersion = request.targetRowVersion + 1),
                createdAliasPublicId = "alias-created-by-merge",
            )
        }
    }

    private companion object {
        fun merchantCatalogDto(
            publicId: String = "catalog-1",
            displayName: String = "星巴克",
            status: String = "active",
        ): MerchantCatalogDto = MerchantCatalogDto(
            publicId = publicId,
            displayName = displayName,
            merchantKey = displayName,
            status = status,
            mergedIntoPublicId = null,
            usageCount = 0,
            createdAt = "2026-05-13T00:00:00Z",
            updatedAt = "2026-05-13T00:05:00Z",
            rowVersion = 1L,
            deletedAt = null,
        )
    }
}

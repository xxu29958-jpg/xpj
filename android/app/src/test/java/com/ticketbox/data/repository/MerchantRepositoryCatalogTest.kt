package com.ticketbox.data.repository

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
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = role,
                boundAt = "2026-05-01T00:00:00Z",
            )
        }

    private fun tokenStore(): FakeSessionTokenStore =
        FakeSessionTokenStore().apply { saveToken("session-token") }

    private fun repository(
        api: ApiService,
        outbox: OutboxRepository? = null,
    ): MerchantRepository = MerchantRepository(
        apiClient = TestApiServiceFactory(api),
        settingsStore = settingsStore(),
        tokenStore = tokenStore(),
        outbox = outbox,
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
    fun `createMerchantCatalog trims display name and uses default active status`() = runTest {
        val api = CatalogApiServiceStub()

        val created = repository(api).createMerchantCatalog("  蓝瓶咖啡  ").getOrThrow()

        assertEquals("蓝瓶咖啡", api.createRequests.single().displayName)
        assertEquals("active", api.createRequests.single().status)
        assertEquals("蓝瓶咖啡", created.displayName)
        assertEquals("active", created.status)
    }

    @Test
    fun `updateMerchantCatalog trims payload and sends OCC token with idempotency key`() = runTest {
        val api = CatalogApiServiceStub()

        val updated = repository(api).updateMerchantCatalog(
            publicId = " catalog-1 ",
            expectedRowVersion = 7L,
            displayName = "  星巴克臻选  ",
            status = " hidden ",
        ).getOrThrow()

        assertEquals(listOf("catalog-1"), api.updateTargets)
        assertEquals(7L, api.updateRequests.single().expectedRowVersion)
        assertEquals("星巴克臻选", api.updateRequests.single().displayName)
        assertEquals("hidden", api.updateRequests.single().status)
        assertTrue(api.updateIdempotencyKeys.single().isNotNullOrBlank())
        assertEquals("hidden", updated.status)
    }

    @Test
    fun `deleteMerchantCatalog network failure does not enqueue catalog mutation`() = runTest {
        val api = CatalogApiServiceStub().apply {
            deleteFailure = IOException("network down")
        }
        val dao = FakePendingMutationDao()
        val repo = repository(api, outbox = OutboxRepository(dao))

        val result = repo.deleteMerchantCatalog(publicId = "catalog-1", expectedRowVersion = 3L)

        assertTrue(result.isFailure)
        assertEquals(listOf("catalog-1"), api.deleteTargets)
        assertEquals(3L, api.deleteRequests.single().expectedRowVersion)
        assertTrue(api.deleteIdempotencyKeys.single().isNotNullOrBlank())
        assertEquals(0, dao.rows.size, "catalog mutations remain online-only in this slice")
    }

    @Test
    fun `mergeMerchantCatalog sends dual OCC tokens and explicit alias policy`() = runTest {
        val api = CatalogApiServiceStub()

        val result = repository(api).mergeMerchantCatalog(
            sourcePublicId = " source ",
            sourceRowVersion = 3L,
            targetPublicId = " target ",
            targetRowVersion = 9L,
            aliasPolicy = MerchantCatalogAliasPolicy.CreateSourceAlias,
        ).getOrThrow()

        assertEquals(listOf("source"), api.mergeTargets)
        val request = api.mergeRequests.single()
        assertEquals(3L, request.expectedRowVersion)
        assertEquals("target", request.targetPublicId)
        assertEquals(9L, request.targetRowVersion)
        assertEquals("create_source_alias", request.aliasPolicy)
        assertEquals(false, request.rewriteHistoricalExpenses)
        assertEquals("merged", result.source.status)
        assertEquals("target", result.source.mergedIntoPublicId)
        assertEquals("alias-created-by-merge", result.createdAliasPublicId)
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

        override suspend fun merchantCatalog(includeHidden: Boolean): MerchantCatalogListDto {
            includeHiddenRequests += includeHidden
            return MerchantCatalogListDto(items = catalogItems)
        }

        override suspend fun createMerchantCatalog(request: MerchantCatalogCreateRequest): MerchantCatalogDto {
            createRequests += request
            return merchantCatalogDto(
                publicId = "catalog-created",
                displayName = request.displayName,
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
        ): MerchantCatalogMergeDto {
            mergeTargets += sourcePublicId
            mergeRequests += request
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

private fun String?.isNotNullOrBlank(): Boolean = !isNullOrBlank()

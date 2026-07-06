package com.ticketbox.data.repository

import com.ticketbox.data.remote.api.MerchantApi
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDeleteRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeRequest
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.data.remote.dto.StatusDto

internal class FakeMerchantApi : MerchantApi {
    val merchantAliasRequests = mutableListOf<MerchantAliasRequest>()
    val merchantAliasUpdateRequests = mutableListOf<MerchantAliasUpdateRequest>()
    val merchantAliasDeleteRequests = mutableListOf<MerchantAliasDeleteRequest>()
    val merchantAliasPatchTargets = mutableListOf<String>()
    val merchantAliasDeleteTargets = mutableListOf<String>()
    val merchantAliasUndoTargets = mutableListOf<String>()
    val merchantCatalogCreateRequests = mutableListOf<MerchantCatalogCreateRequest>()
    val merchantCatalogUpdateRequests = mutableListOf<MerchantCatalogUpdateRequest>()
    val merchantCatalogDeleteRequests = mutableListOf<MerchantCatalogDeleteRequest>()
    val merchantCatalogMergeRequests = mutableListOf<MerchantCatalogMergeRequest>()
    val merchantCatalogPatchTargets = mutableListOf<String>()
    val merchantCatalogDeleteTargets = mutableListOf<String>()
    val merchantCatalogMergeTargets = mutableListOf<String>()
    var merchantCatalogItems: List<MerchantCatalogDto> = listOf(
        fakeMerchantCatalogDto(
            publicId = "catalog-1",
            displayName = "星巴克",
            status = "active",
        ),
    )
    var merchantCatalogUpdateFailure: Throwable? = null

    override suspend fun merchantCatalog(includeHidden: Boolean): MerchantCatalogListDto =
        MerchantCatalogListDto(items = merchantCatalogItems)

    override suspend fun createMerchantCatalog(request: MerchantCatalogCreateRequest): MerchantCatalogDto {
        merchantCatalogCreateRequests += request
        return fakeMerchantCatalogDto(
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
        merchantCatalogPatchTargets += publicId
        merchantCatalogUpdateRequests += request
        merchantCatalogUpdateFailure?.let { throw it }
        return fakeMerchantCatalogDto(
            publicId = publicId,
            displayName = request.displayName ?: "星巴克",
            status = request.status ?: "active",
        )
    }

    override suspend fun deleteMerchantCatalog(
        publicId: String,
        request: MerchantCatalogDeleteRequest,
        idempotencyKey: String?,
    ): MerchantCatalogDto {
        merchantCatalogDeleteTargets += publicId
        merchantCatalogDeleteRequests += request
        return fakeMerchantCatalogDto(
            publicId = publicId,
            displayName = "星巴克",
            status = "active",
        ).copy(deletedAt = "2026-05-13T00:10:00Z")
    }

    override suspend fun mergeMerchantCatalog(
        sourcePublicId: String,
        request: MerchantCatalogMergeRequest,
    ): MerchantCatalogMergeDto {
        merchantCatalogMergeTargets += sourcePublicId
        merchantCatalogMergeRequests += request
        return MerchantCatalogMergeDto(
            source = fakeMerchantCatalogDto(
                publicId = sourcePublicId,
                displayName = "星巴克",
                status = "merged",
            ).copy(
                mergedIntoPublicId = request.targetPublicId,
                rowVersion = request.expectedRowVersion + 1,
            ),
            target = fakeMerchantCatalogDto(
                publicId = request.targetPublicId,
                displayName = "蓝瓶咖啡",
                status = "active",
            ).copy(rowVersion = request.targetRowVersion + 1),
            createdAliasPublicId = if (request.aliasPolicy == "create_source_alias") "alias-created-by-merge" else null,
        )
    }

    override suspend fun merchantAliases(): MerchantAliasListDto = MerchantAliasListDto(
        items = listOf(
            fakeMerchantAliasDto(
                publicId = "alias-1",
                canonicalMerchant = "星巴克",
                alias = "Starbucks",
                enabled = true,
            ),
        ),
    )

    override suspend fun createMerchantAlias(request: MerchantAliasRequest): MerchantAliasDto {
        merchantAliasRequests += request
        return fakeMerchantAliasDto(
            publicId = "alias-created",
            canonicalMerchant = requireNotNull(request.canonicalMerchant),
            alias = requireNotNull(request.alias),
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun updateMerchantAlias(
        publicId: String,
        request: MerchantAliasUpdateRequest,
        idempotencyKey: String?,
    ): MerchantAliasDto {
        merchantAliasPatchTargets += publicId
        merchantAliasUpdateRequests += request
        return fakeMerchantAliasDto(
            publicId = publicId,
            canonicalMerchant = request.canonicalMerchant ?: "星巴克",
            alias = request.alias ?: "Starbucks",
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun deleteMerchantAlias(
        publicId: String,
        request: MerchantAliasDeleteRequest,
        idempotencyKey: String?,
    ): StatusDto {
        merchantAliasDeleteTargets += publicId
        merchantAliasDeleteRequests += request
        return StatusDto("ok")
    }

    override suspend fun undoMerchantAlias(publicId: String): MerchantAliasDto {
        merchantAliasUndoTargets += publicId
        return fakeMerchantAliasDto(
            publicId = publicId,
            canonicalMerchant = "星巴克",
            alias = "Starbucks",
            enabled = true,
        )
    }
}

private fun fakeMerchantAliasDto(
    publicId: String,
    canonicalMerchant: String,
    alias: String,
    enabled: Boolean,
): MerchantAliasDto = MerchantAliasDto(
    publicId = publicId,
    canonicalMerchant = canonicalMerchant,
    canonicalKey = canonicalMerchant,
    alias = alias,
    aliasKey = alias.lowercase(),
    enabled = enabled,
    createdAt = "2026-05-13T00:00:00Z",
    updatedAt = "2026-05-13T00:05:00Z",
    rowVersion = 1L,
)

private fun fakeMerchantCatalogDto(
    publicId: String,
    displayName: String,
    status: String,
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

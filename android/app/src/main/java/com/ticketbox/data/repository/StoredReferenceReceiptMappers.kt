package com.ticketbox.data.repository

internal fun com.ticketbox.domain.model.MerchantCatalog.toDto() = com.ticketbox.data.remote.dto.MerchantCatalogDto(
    publicId = publicId,
    displayName = displayName,
    merchantKey = merchantKey,
    status = status,
    mergedIntoPublicId = mergedIntoPublicId,
    usageCount = usageCount,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
    deletedAt = deletedAt,
)

internal fun com.ticketbox.domain.model.MerchantAlias.toDto() = com.ticketbox.data.remote.dto.MerchantAliasDto(
    publicId = publicId,
    canonicalMerchant = canonicalMerchant,
    canonicalKey = canonicalKey,
    alias = alias,
    aliasKey = aliasKey,
    enabled = enabled,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
)

internal fun com.ticketbox.domain.model.MerchantCatalogMergeResult.toDto() = com.ticketbox.data.remote.dto.MerchantCatalogMergeDto(
    source = source.toDto(),
    target = target.toDto(),
    createdAliasPublicId = createdAliasPublicId,
)

internal fun com.ticketbox.domain.model.ReferenceCreated.toDto() = com.ticketbox.data.remote.dto.ReferenceCreatedDto(
    kind = kind,
    publicId = publicId,
    name = name,
    rowVersion = rowVersion,
)

package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore

/**
 * Merchant-alias CRUD. Extracted from ExpenseRepository.
 */
class MerchantRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) {
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Merchant",
        statusMessages = mapOf(404 to "商家别名不存在。"),
    )

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    private fun api() = apiProvider.current()

    suspend fun merchantAliases(): Result<List<MerchantAlias>> = errorHandler.safeCall {
        api().merchantAliases().items.map { it.toDomain() }
    }

    suspend fun createMerchantAlias(
        canonicalMerchant: String,
        alias: String,
    ): Result<MerchantAlias> = errorHandler.safeCall {
        val cleanCanonical = canonicalMerchant.trim()
        val cleanAlias = alias.trim()
        require(cleanCanonical.isNotBlank()) { "请输入标准商家名。" }
        require(cleanAlias.isNotBlank()) { "请输入别名。" }
        api().createMerchantAlias(
            MerchantAliasRequest(
                canonicalMerchant = cleanCanonical,
                alias = cleanAlias,
                enabled = true,
            ),
        ).toDomain()
    }

    suspend fun updateMerchantAlias(
        publicId: String,
        canonicalMerchant: String? = null,
        alias: String? = null,
        enabled: Boolean? = null,
    ): Result<MerchantAlias> = errorHandler.safeCall {
        val cleanPublicId = publicId.trim()
        require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
        api().updateMerchantAlias(
            cleanPublicId,
            MerchantAliasRequest(
                canonicalMerchant = canonicalMerchant?.trim()?.takeIf { it.isNotBlank() },
                alias = alias?.trim()?.takeIf { it.isNotBlank() },
                enabled = enabled,
            ),
        ).toDomain()
    }

    suspend fun deleteMerchantAlias(publicId: String): Result<Unit> = errorHandler.safeCall {
        val cleanPublicId = publicId.trim()
        require(cleanPublicId.isNotBlank()) { "请选择一个商家别名。" }
        api().deleteMerchantAlias(cleanPublicId)
        Unit
    }
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryPreferenceDto
import com.ticketbox.data.remote.dto.CategoryPreferenceTokenRequestDto
import com.ticketbox.domain.model.CategoryPreference
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore

interface CategoryPreferenceActions {
    fun canModifyLedger(): Boolean
    suspend fun categoryPreferences(): Result<List<CategoryPreference>>
    suspend fun deleteCategoryPreference(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Unit>
}

/**
 * Ledger category-directory contract.
 *
 * The backend materializes custom categories after actual use. Removal is
 * online-only and OCC-protected; restoration remains owned by the recycle bin.
 */
class CategoryPreferenceRepository(
    apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    tokenStore: SessionTokenStore,
    apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) : CategoryPreferenceActions {
    private val requestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "CategoryPreference",
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override suspend fun categoryPreferences(): Result<List<CategoryPreference>> =
        errorHandler.safeCall {
            requestGuard.guardedCall { api ->
                api.categoryPreferences().items.map(CategoryPreferenceDto::toDomain)
            }
        }

    override suspend fun deleteCategoryPreference(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Unit> =
        errorHandler.safeCall {
            requestGuard.guardedCall { api ->
                api.deleteCategoryPreference(
                    publicId = publicId,
                    request = CategoryPreferenceTokenRequestDto(expectedRowVersion),
                )
            }
            Unit
        }
}

private fun CategoryPreferenceDto.toDomain(): CategoryPreference = CategoryPreference(
    publicId = publicId,
    name = name,
    kind = kind,
    usageCount = usageCount,
    rowVersion = rowVersion,
)

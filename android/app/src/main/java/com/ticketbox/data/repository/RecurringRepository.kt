package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import java.util.TimeZone

class RecurringRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) {
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Recurring",
        statusMessages = mapOf(404 to "固定支出不存在。"),
    )

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    private fun api() = apiProvider.current()

    suspend fun items(
        status: String? = null,
        includeArchived: Boolean = false,
        month: String? = null,
    ): Result<List<RecurringItem>> =
        errorHandler.safeCall {
            api().recurringItems(
                status = status?.trim()?.ifBlank { null },
                includeArchived = includeArchived,
                month = month?.trim()?.ifBlank { null },
                timezone = currentTimezoneId(),
            ).items.map { it.toDomain() }
        }

    suspend fun candidates(): Result<List<RecurringCandidate>> = errorHandler.safeCall {
        api().recurringCandidates(timezone = currentTimezoneId()).items.map { it.toDomain() }
    }

    suspend fun detail(publicId: String, month: String? = null): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().recurringItem(
            publicId = publicId.trim(),
            month = month?.trim()?.ifBlank { null },
            timezone = currentTimezoneId(),
        ).toDomain()
    }

    suspend fun confirmCandidate(
        candidate: RecurringCandidate,
        nextExpectedDate: String? = null,
    ): Result<RecurringItem> = errorHandler.safeCall {
        api().confirmRecurringCandidate(
            request = candidate.toConfirmRequest(nextExpectedDate = nextExpectedDate?.trim()?.ifBlank { null }),
            timezone = currentTimezoneId(),
        ).toDomain()
    }

    suspend fun pause(publicId: String): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().pauseRecurringItem(publicId.trim()).toDomain()
    }

    suspend fun resume(publicId: String): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().resumeRecurringItem(publicId.trim()).toDomain()
    }

    suspend fun archive(publicId: String): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().archiveRecurringItem(publicId.trim()).toDomain()
    }
}

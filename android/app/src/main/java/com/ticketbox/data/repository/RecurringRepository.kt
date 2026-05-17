package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import java.util.TimeZone

interface RecurringActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    suspend fun items(
        status: String? = null,
        includeArchived: Boolean = false,
        month: String? = null,
    ): Result<List<RecurringItem>>
    suspend fun candidates(): Result<List<RecurringCandidate>>
    suspend fun detail(publicId: String, month: String? = null): Result<RecurringItem>
    suspend fun confirmCandidate(
        candidate: RecurringCandidate,
        nextExpectedDate: String? = null,
    ): Result<RecurringItem>
    suspend fun pause(publicId: String): Result<RecurringItem>
    suspend fun resume(publicId: String): Result<RecurringItem>
    suspend fun archive(publicId: String): Result<RecurringItem>
}

class RecurringRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
) : RecurringActions {
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Recurring",
        statusMessages = mapOf(404 to "固定支出不存在。"),
    )

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override fun observeActiveLedgerId(): Flow<String?> = settingsStore.observeActiveLedgerId()

    private fun api() = apiProvider.current()

    override suspend fun items(
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> =
        errorHandler.safeCall {
            api().recurringItems(
                status = status?.trim()?.ifBlank { null },
                includeArchived = includeArchived,
                month = month?.trim()?.ifBlank { null },
                timezone = currentTimezoneId(),
            ).items.map { it.toDomain() }
        }

    override suspend fun candidates(): Result<List<RecurringCandidate>> = errorHandler.safeCall {
        api().recurringCandidates(timezone = currentTimezoneId()).items.map { it.toDomain() }
    }

    override suspend fun detail(publicId: String, month: String?): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().recurringItem(
            publicId = publicId.trim(),
            month = month?.trim()?.ifBlank { null },
            timezone = currentTimezoneId(),
        ).toDomain()
    }

    override suspend fun confirmCandidate(
        candidate: RecurringCandidate,
        nextExpectedDate: String?,
    ): Result<RecurringItem> = errorHandler.safeCall {
        api().confirmRecurringCandidate(
            request = candidate.toConfirmRequest(nextExpectedDate = nextExpectedDate?.trim()?.ifBlank { null }),
            timezone = currentTimezoneId(),
        ).toDomain()
    }

    override suspend fun pause(publicId: String): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().pauseRecurringItem(publicId.trim()).toDomain()
    }

    override suspend fun resume(publicId: String): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().resumeRecurringItem(publicId.trim()).toDomain()
    }

    override suspend fun archive(publicId: String): Result<RecurringItem> = errorHandler.safeCall {
        require(publicId.isNotBlank()) { "固定支出不存在。" }
        api().archiveRecurringItem(publicId.trim()).toDomain()
    }
}

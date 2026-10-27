package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ReferenceCreateRequestDto
import com.ticketbox.domain.model.ReferenceCreated
import java.util.UUID
import kotlinx.coroutines.flow.Flow

enum class ReferenceKind(val wire: String) { Category("category"), Tag("tag") }

interface ReferenceCreationActions {
    val kind: ReferenceKind
    fun observeAccess(): Flow<LedgerAccessContext?>
    suspend fun create(binding: LogicalSessionBinding, name: String, key: String): Result<com.ticketbox.domain.model.ReferenceCreated>
}

/** Online library creation; retries keep the original body/key and never enter the financial Outbox. */
class ReferenceCreationRepository(
    private val apiProvider: ApiServiceProvider,
    override val kind: ReferenceKind,
) : ReferenceCreationActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "ReferenceCreation")

    override fun observeAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override suspend fun create(binding: LogicalSessionBinding, name: String, key: String): Result<com.ticketbox.domain.model.ReferenceCreated> =
        errors.safeCall {
            guard.bindExact(binding).call { api ->
                val request = ReferenceCreateRequestDto(name)
                val receipt = when (kind) {
                    ReferenceKind.Tag -> api.createTag(key, request)
                    ReferenceKind.Category -> api.createCategoryPreference(key, request)
                }
                check(receipt.kind == kind.wire && receipt.rowVersion > 0) { "返回的添加结果不匹配，请核实原提交。" }
                UUID.fromString(receipt.publicId)
                receipt
            }
        }
}

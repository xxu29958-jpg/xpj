package com.ticketbox.data.repository

import com.ticketbox.data.local.DebtBillInputDao
import com.ticketbox.data.local.DebtBillInputEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto
import com.ticketbox.data.remote.dto.DebtBillParseRequestDto
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import java.util.UUID

data class DebtBillInput(
    val original: DebtBillInputEntity,
    val payload: DebtBillCapturePayload,
    val source: DebtBillCaptureDto?,
    val command: OutboxRow? = null,
    val binding: LogicalSessionBinding = payload.binding,
) {
    val captureKey: String get() = original.captureKey
    val needsAttention: Boolean get() = command?.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)

    fun forBinding(current: LogicalSessionBinding): DebtBillInput {
        require(payload.binding.ownerKey == current.ownerKey && payload.binding.ledgerId == current.ledgerId &&
            payload.binding.serverUrl == current.serverUrl) { "原采集身份或账本已变化。" }
        return copy(binding = current)
    }
}

interface DebtBillActions {
    fun observe(binding: LogicalSessionBinding): Flow<List<DebtBillInput>>
    suspend fun find(binding: LogicalSessionBinding, captureKey: String): Result<DebtBillInput?>
    suspend fun capture(binding: LogicalSessionBinding, creationKey: String, captureKey: String,
        draftJson: String, image: PreparedUploadImage): Result<DebtBillInput>
    suspend fun saveDraft(captureKey: String, draftJson: String)
    suspend fun refresh(input: DebtBillInput): Result<DebtBillInput>
    suspend fun suggest(input: DebtBillInput, retry: Boolean): Result<DebtBillParseOutcomeDto>
    suspend fun recover(input: DebtBillInput, discard: Boolean): Result<Unit>
    suspend fun original(input: DebtBillInput): Result<ByteArray>
    suspend fun forDebt(binding: LogicalSessionBinding, publicId: String): Result<List<DebtBillCaptureDto>>
    suspend fun original(binding: LogicalSessionBinding, publicId: String): Result<ByteArray>
}

/** Original ownership survives session epochs; each operation still requires its current exact binding. */
class DebtBillRepository(
    private val apiProvider: ApiServiceProvider,
    private val inputs: DebtBillInputDao,
    private val outbox: OutboxRepository,
    private val files: UploadIntentFileStore,
) : DebtBillActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { apiProvider.currentSession()?.serverUrl }, context = "Debt bill")

    private fun bind(input: DebtBillInput) = guard.bindExact(input.forBinding(input.binding).binding)

    override suspend fun find(binding: LogicalSessionBinding, captureKey: String): Result<DebtBillInput?> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val original = inputs.input(captureKey)
        bound.requireStillActive()
        original?.let { requireNotNull(decodeBillInput(it)).forBinding(binding) }
    }

    override suspend fun original(input: DebtBillInput): Result<ByteArray> = errors.safeCall {
        val bound = bind(input)
        val bytes = files.read(input.payload.file)
        bound.requireStillActive()
        bytes
    }

    override suspend fun forDebt(binding: LogicalSessionBinding, publicId: String): Result<List<DebtBillCaptureDto>> = errors.safeCall {
        guard.bindExact(binding).call { api ->
            api.debt(publicId) // The displayed Debt retains its own read authority.
            api.debtBills(debtPublicId = publicId).captures
        }
    }

    override suspend fun original(binding: LogicalSessionBinding, publicId: String): Result<ByteArray> = errors.safeCall {
        guard.bindExact(binding).call { it.debtBillOriginal(publicId).use { body -> body.bytes() } }
    }

    override fun observe(binding: LogicalSessionBinding): Flow<List<DebtBillInput>> = combine(
        inputs.observeInputs(binding.ownerKey, binding.ledgerId),
        outbox.observeActiveByTypes(setOf(PendingMutationType.CaptureDebtBill), includeCompleted = true),
    ) { originals, rows -> originals.mapNotNull { original ->
        decodeBillInput(original)?.takeIf { !original.closed && it.payload.binding.serverUrl == binding.serverUrl }
            ?.forBinding(binding)?.let { it.copy(command = rows.singleOrNull { row -> row.idempotencyKey == it.captureKey }) }
    } }

    override suspend fun capture(binding: LogicalSessionBinding, creationKey: String, captureKey: String,
        draftJson: String, image: PreparedUploadImage): Result<DebtBillInput> = errors.safeCall {
        val bound = guard.bindExact(binding)
        require(ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读。" }
        files.acceptBatch(listOf(UploadIntentFileSource(captureKey) { image }),
            beforePrepare = { inputs.input(captureKey)?.let { original ->
                requireNotNull(decodeBillInput(original)).forBinding(binding).also {
                    bound.requireStillActive()
                    check(it.payload.creationKey == creationKey) { "原采集任务已变化。" }
                    // Admission may have committed before its scheduler acknowledgement was lost.
                    outbox.withActiveBinding(bound) { outbox.schedulePending() }
                }
            } },
            persist = { descriptors ->
                val payload = DebtBillCapturePayload(1, binding, creationKey, captureKey, requireNotNull(descriptors.single()))
                val original = DebtBillInputEntity(captureKey, binding.ownerKey, binding.ledgerId,
                    creationKey, DebtBillJson.payload.toJson(payload), draftJson)
                // The original input and delivery intent share the existing file-before-Room transaction.
                outbox.enqueueUploadBatch(bound, listOf(PendingMutationIntent(PendingMutationType.CaptureDebtBill,
                    "debt_bill:$captureKey", original.payloadJson, 0L, captureKey)), afterPersisted = { inputs.insert(original) })
                requireNotNull(decodeBillInput(original))
            })
    }

    override suspend fun saveDraft(captureKey: String, draftJson: String) = inputs.saveDraft(captureKey, draftJson)

    override suspend fun refresh(input: DebtBillInput): Result<DebtBillInput> = errors.safeCall {
        val bound = bind(input)
        val source = bound.call { it.debtBillByKey(input.captureKey) }
        check(source.captureKey == input.captureKey && source.creationKey == input.payload.creationKey &&
            source.inputSha256 == input.payload.file.sha256) { "原账单回执不匹配。" }
        outbox.withActiveBinding(bound) {
            inputs.saveSource(input.captureKey, DebtBillJson.source.toJson(source))
            if (source.status in setOf("confirmed", "rejected")) inputs.close(input.captureKey)
        }
        input.copy(source = source)
    }

    override suspend fun suggest(input: DebtBillInput, retry: Boolean): Result<DebtBillParseOutcomeDto> = errors.safeCall {
        val bound = bind(input)
        require(ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读。" }
        val latest = requireNotNull(inputs.input(input.captureKey))
        val source = requireNotNull(input.source) { "请先保存原账单。" }
        check(source.status == "pending") { "原账单已结束，请核对原记录。" }
        val key = latest.parseAttemptKey?.takeUnless { retry } ?: UUID.randomUUID().toString()
        val version = latest.parseExpectedRowVersion?.takeUnless { retry } ?: source.rowVersion
        outbox.withActiveBinding(bound) { inputs.saveParseAttempt(input.captureKey, key, version) }
        val outcome = bound.call {
            it.parseDebtBillSource(source.publicId, DebtBillParseRequestDto(version), key)
        }
        check(outcome.publicId == source.publicId && outcome.attemptKey == key) { "原解析回执不匹配。" }
        outbox.withActiveBinding(bound) {
            inputs.saveSource(input.captureKey, DebtBillJson.source.toJson(source.copy(
                rowVersion = outcome.rowVersion, parseOutcome = outcome)))
        }
        outcome
    }

    override suspend fun recover(input: DebtBillInput, discard: Boolean): Result<Unit> = errors.safeCall {
        val bound = bind(input)
        require(ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读。" }
        if (discard) {
            val source = refresh(input).getOrThrow().source ?: error("原账单尚未确认，请先重试保存。")
            if (source.status == "pending") {
                // Derive a stable distinct command key from the immutable source; repeated taps retain it.
                val key = UUID.nameUUIDFromBytes("discard:${input.captureKey}".toByteArray()).toString()
                val ended = bound.call { it.discardDebtBill(source.publicId, DebtBillParseRequestDto(source.rowVersion), key) }
                outbox.withActiveBinding(bound) { inputs.saveSource(input.captureKey, DebtBillJson.source.toJson(ended)) }
            }
            outbox.withActiveBinding(bound) { inputs.close(input.captureKey) }
        } else {
            val rows = outbox.observeActiveByTypes(setOf(PendingMutationType.CaptureDebtBill), includeCompleted = true).first()
            val row = rows.singleOrNull { it.idempotencyKey == input.captureKey && it.ownerKey == input.payload.binding.ownerKey }
            if (row == null) {
                outbox.enqueueUploadBatch(bound, listOf(PendingMutationIntent(PendingMutationType.CaptureDebtBill,
                    "debt_bill:${input.captureKey}", input.original.payloadJson, 0L, input.captureKey)))
            } else if (row.status == PendingMutationStatus.Pending) {
                outbox.withActiveBinding(bound) { outbox.schedulePending() }
            } else if (row.status == PendingMutationStatus.Done) {
                refresh(input).getOrThrow()
            } else {
                check(outbox.resolveFailed(row.id, FailedResolution.Retry(), bound)) { "原保存状态已变化，请重新核对。" }
            }
        }
    }
}

internal fun decodeBillInput(original: DebtBillInputEntity): DebtBillInput? {
    val payload = DebtBillJson.readPayload(original.payloadJson) ?: return null
    if (payload.captureKey != original.captureKey || payload.creationKey != original.creationKey ||
        payload.binding.ownerKey != original.ownerKey || payload.binding.ledgerId != original.ledgerId) return null
    val source = original.sourceJson?.let { runCatching { DebtBillJson.source.fromJson(it) }.getOrNull() ?: return null }
    return DebtBillInput(original, payload, source)
}

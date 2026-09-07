package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import java.time.Instant
import java.time.format.DateTimeParseException
import java.util.TimeZone
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import okhttp3.MediaType.Companion.toMediaTypeOrNull

/** Owns acceptance and recovery of original files in the existing Outbox; it never sends HTTP. */
class UploadIntentRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val files: UploadIntentFileStore,
    private val payloadAdapter: JsonAdapter<UploadScreenshotPayload>,
    private val receiptAdapter: JsonAdapter<UploadResponseDto>,
    private val settingsStore: TicketboxSettingsStore,
) : UploadIntentActions {
    private val guard = LedgerRequestGuard(apiProvider)

    override fun currentUploadBinding(): LogicalSessionBinding? = guard.captureLogicalBinding()

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observeUploadIntents(): Flow<UploadIntentObservation> = apiProvider.observeActiveLedgerAccess()
        .flatMapLatest { access ->
            if (access == null) flowOf(UploadIntentObservation(null, emptyList()))
            else outbox.observeActiveByTypes(setOf(PendingMutationType.UploadScreenshot), includeCompleted = true)
                .map { rows ->
                    val current = access.takeIf { guard.captureLogicalBinding() == it.binding }
                    UploadIntentObservation(current, if (current == null) emptyList() else rows
                        .filter { it.belongsToUploadBinding(current.binding) }
                        .sortedWith(compareBy(OutboxRow::createdAt, OutboxRow::id)).map(::describe))
                }.distinctUntilChanged().onEach { observation -> recordLastUpload(observation) }
        }.distinctUntilChanged()

    override suspend fun acceptUploadBatch(request: UploadBatchRequest): Result<UploadAcceptance> = uploadIntentResult {
        val original = request.copy(imageRefs = request.imageRefs.toList())
        require(isUploadIntentFileKey(original.id)) { "无法读取原上传编号，请重新选择截图。" }
        require(original.imageRefs.isNotEmpty()) { "请选择至少一张截图。" }
        val bound = guard.bindExact(original.expectedBinding, LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE)
        requireUploadWriter(apiProvider)
        val keys = original.imageRefs.indices.map { uploadItemKey(original.id, it) }
        var groupId = original.id
        var timezone = ""
        files.acceptBatch(
            sources = original.imageRefs.mapIndexed { index, reference ->
                UploadIntentFileSource(keys[index]) { prepareUploadOriginal(original, reference) }
            },
            beforePrepare = {
                val existing = outbox.originalUploadRows(bound, keys)
                originalUploadAcceptance(original, existing, payloadAdapter) ?: run {
                    groupId = continuationGroup(bound, original.expectedBinding) ?: original.id
                    timezone = TimeZone.getDefault().id
                    null
                }
            },
            persist = { descriptors ->
                requireUploadWriter(apiProvider)
                val intents = descriptors.mapIndexed { index, file ->
                    val payload = UploadScreenshotPayload(1,
                        UploadBatchPosition(original.id, index, descriptors.size, groupId),
                        original.expectedBinding, timezone, file)
                    PendingMutationIntent(type = PendingMutationType.UploadScreenshot, targetId = "upload_batch:$groupId",
                        payloadJson = payloadAdapter.toJson(payload), expectedRowVersion = 0L, idempotencyKey = keys[index])
                }
                UploadAcceptance(groupId, outbox.enqueueUploadBatch(bound, intents))
            },
        )
    }

    override suspend fun recoverUploadGroup(
        expectedBinding: LogicalSessionBinding,
        groupId: String,
        drop: Boolean,
    ): Result<Unit> = uploadIntentResult {
        require(isUploadIntentFileKey(groupId)) { "无法读取原上传批次，请升级后核对。" }
        val bound = guard.bindExact(expectedBinding)
        if (!drop) requireUploadWriter(apiProvider)
        val target = "upload_batch:$groupId"
        val originals = outbox.activeForTarget(bound, target)
            .filter { it.type == PendingMutationType.UploadScreenshot && it.belongsToUploadBinding(expectedBinding) }
        require(originals.isNotEmpty()) { "原上传状态已变化，请重新核对。" }
        val retryIds = if (drop) emptyList() else originals.map(::describe).filter { it.canRetry }
            .filter { uploadOriginalReadable(files, requireNotNull(it.payload?.file)) }.map { it.row.id }
        require(drop || retryIds.isNotEmpty()) { "原上传暂不能重试，请核对原件、版本或到期提示。" }
        if (!drop) requireUploadWriter(apiProvider)
        check(outbox.recoverUploadGroup(bound, target, drop, retryIds)) { "原上传状态已变化，请重新核对。" }
    }

    /** The FileStore holds its lock while ALL bindings and raw types prove the referenced key set. */
    suspend fun collectOrphans(): Int = files.collectOrphans {
        val referenced = mutableSetOf<String>()
        for (row in outbox.allRowsForUploadFileReferences()) {
            when (PendingMutationType.fromWire(row.type)) {
                PendingMutationType.Unknown -> return@collectOrphans null
                PendingMutationType.UploadScreenshot -> {
                    val payload = payloadAdapter.readSupportedUpload(row.toDomain()) ?: return@collectOrphans null
                    payload.file?.let { referenced += it.key }
                }
                else -> Unit
            }
        }
        referenced
    }

    private suspend fun continuationGroup(bound: BoundLedgerRequest, binding: LogicalSessionBinding): String? {
        val rows = outbox.observeActiveByTypes(setOf(PendingMutationType.UploadScreenshot)).first()
        bound.requireStillActive()
        return rows.filter { it.belongsToUploadBinding(binding) }
            .sortedWith(compareBy(OutboxRow::createdAt, OutboxRow::id))
            .firstNotNullOfOrNull { row -> row.targetId.removePrefix("upload_batch:")
                .takeIf { row.targetId == "upload_batch:$it" && isUploadIntentFileKey(it) } }
    }

    private fun describe(row: OutboxRow): PendingUploadIntent = PendingUploadIntent(
        row, payloadAdapter.readSupportedUpload(row), row.receiptJson?.let(receiptAdapter::readUploadJsonOrNull),
    )

    private suspend fun recordLastUpload(observation: UploadIntentObservation) {
        val binding = observation.access?.binding ?: return
        val latest = observation.uploads.filter { it.row.status == PendingMutationStatus.Done && it.receipt != null }
            .mapNotNull { it.row.completedAt?.let(::uploadInstantOrNull) }.maxOrNull() ?: return
        // This derived timestamp is recoverable from DONE. A failed write cannot erase its receipt or resend it.
        uploadIntentResult {
            val bound = guard.bindExact(binding)
            outbox.withActiveBinding(bound) {
                val previous = settingsStore.lastUploadAtForLedger(bound.ledgerId)?.let(::uploadInstantOrNull)
                if (previous == null || previous < latest) {
                    val originalTimestamp = observation.uploads.first { uploadInstantOrNull(it.row.completedAt) == latest }
                        .row.completedAt
                    settingsStore.saveLastUploadAtForLedger(bound.ledgerId, requireNotNull(originalTimestamp))
                }
            }
        }
    }
}

private fun OutboxRow.belongsToUploadBinding(binding: LogicalSessionBinding): Boolean =
    ownerKey == binding.ownerKey && ledgerId == binding.ledgerId

private fun originalUploadAcceptance(
    request: UploadBatchRequest,
    rows: List<OutboxRow>,
    adapter: JsonAdapter<UploadScreenshotPayload>,
): UploadAcceptance? {
    if (rows.isEmpty()) return null
    require(rows.size == request.imageRefs.size) { "原上传只剩部分记录，不能重新创建；请先核对原批次。" }
    val indexed = rows.associateBy { it.idempotencyKey }
    val ordered = request.imageRefs.indices.map { index ->
        requireNotNull(indexed[uploadItemKey(request.id, index)]) { "原上传记录不完整，请先核对。" }
    }
    val payloads = ordered.map { row ->
        requireNotNull(adapter.readSupportedUpload(row)) { "当前版本无法读取原上传，请升级后核对。" }
    }
    val groupId = payloads.first().batch.groupId
    require(payloads.all { it.batch.id == request.id && it.batch.count == rows.size && it.batch.groupId == groupId }) {
        "原上传批次已变化，不能用新的选择替换。"
    }
    return UploadAcceptance(groupId, ordered.map { it.id })
}

private fun requireUploadWriter(provider: ApiServiceProvider) {
    require(ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色为只读，无法上传或重试截图。" }
}

private suspend fun prepareUploadOriginal(request: UploadBatchRequest, reference: String): PreparedUploadImage? {
    val prepared = try {
        request.prepare(reference)
    } catch (error: CancellationException) {
        throw error
    } catch (_: Exception) {
        null
    } ?: return null
    val name = prepared.fileName.trim().ifBlank { "ticketbox-screenshot.jpg" }.replace(Regex("[\\\\/:*?\"<>|]"), "_")
    val type = (prepared.contentType?.takeIf { it.isNotBlank() } ?: "image/jpeg").toMediaTypeOrNull()?.toString()
    return prepared.copy(fileName = name, contentType = type)
}

private suspend fun uploadOriginalReadable(files: UploadIntentFileStore, descriptor: UploadIntentFileDescriptor): Boolean = try {
    files.read(descriptor)
    true
} catch (_: IOException) {
    false
}

private fun <T> JsonAdapter<T>.readUploadJsonOrNull(json: String): T? = try {
    fromJson(json)
} catch (_: JsonDataException) {
    null
} catch (_: IOException) {
    null
} catch (_: IllegalArgumentException) {
    null
}

private fun uploadInstantOrNull(value: String?): Instant? = try {
    value?.let(Instant::parse)
} catch (_: DateTimeParseException) {
    null
}

private suspend fun <T> uploadIntentResult(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (error: CancellationException) {
    throw error
} catch (error: UploadIntentFileException) {
    val message = when (error.failure) {
        UploadIntentFileFailure.BATCH_LIMIT -> "一次最多选择 100 张截图，请减少数量后重试。"
        UploadIntentFileFailure.STAGING_LIMIT -> "待上传原件已达到本机暂存上限，请先处理原批次。"
        UploadIntentFileFailure.DISK_RESERVE -> "本机存储空间不足，截图尚未全部保存，请释放空间后重试。"
        UploadIntentFileFailure.CONTENT_MISMATCH -> "原上传文件与记录不一致，请保留原批次并核对。"
    }
    Result.failure(RepositoryException(message))
} catch (error: Exception) {
    Result.failure(error)
}

package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.local.ExpenseFactInputEntity
import com.ticketbox.upload.PreparedUploadImage

/** A private, unsubmitted input; the descriptor refers to the existing durable file owner. */
class OriginalSelectionDraft internal constructor(internal val row: ExpenseFactInputEntity, val payload: OriginalAttachmentPayload) {
    val key: String get() = row.originalKey
}

private const val ORIGINAL_SELECTION_FORM = "original_attachment"
private val selectionBindingAdapter = Moshi.Builder().build().adapter(LogicalSessionBinding::class.java)

internal fun decodeOriginalSelection(row: ExpenseFactInputEntity): OriginalSelectionDraft {
    val payload = requireNotNull(originalPayloadAdapter.fromJson(row.inputJson))
    require(row.formKey == ORIGINAL_SELECTION_FORM && payload.supported() && payload.file?.key == row.originalKey &&
        payload.expenseId == row.expenseId && payload.origin.ownerKey == row.ownerKey && payload.origin.ledgerId == row.ledgerId &&
        payload.origin == selectionBindingAdapter.fromJson(row.bindingJson))
    return OriginalSelectionDraft(row, payload)
}

/** Unsubmitted attachment input under the existing upload/file owner, separate from delivery. */
class OriginalSelectionRepository internal constructor(
    private val guard: LedgerRequestGuard,
    private val outbox: OutboxRepository,
    private val files: UploadIntentFileStore,
    private val inputs: com.ticketbox.data.local.ExpenseFactInputDao,
) : OriginalSelectionActions {
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "OriginalSelection")

    override suspend fun loadOriginalSelection(binding: LogicalSessionBinding, id: Long) = errors.safeCall {
        outbox.withActiveBinding(guard.bindExact(binding)) {
            val rows = inputs.factInputs(binding.ownerKey, binding.ledgerId, id).filter { it.formKey.startsWith("original_") }
            if (rows.isEmpty()) null else decodeOriginalSelection(rows.single())
        }
    }

    override suspend fun retainOriginalSelection(request: OriginalSubmission) = errors.safeCall {
        // Captured input may finish after an identity change; it stays private to its original scope.
        // Reading and command admission independently require the exact active binding.
        require(isUploadIntentFileKey(request.key) && request.payload.operation in setOf("attach_original", "replenish_original"))
        files.acceptBatch(listOf(UploadIntentFileSource(request.key, request.payload.file) { request.prepare?.invoke() }),
            beforePrepare = {
                val origin = request.payload.origin
                inputs.factInputs(origin.ownerKey, origin.ledgerId, request.payload.expenseId)
                    .singleOrNull { it.formKey == ORIGINAL_SELECTION_FORM }?.let { row ->
                        decodeOriginalSelection(row).also {
                            check(it.key == request.key && it.payload.copy(file = null) == request.payload.copy(file = null))
                        }
                    }
            }, persist = { descriptors ->
                val payload = request.payload.copy(file = requireNotNull(descriptors.single()))
                require(payload.supported())
                val row = ExpenseFactInputEntity(payload.origin.ownerKey, payload.origin.ledgerId, payload.expenseId,
                    ORIGINAL_SELECTION_FORM, selectionBindingAdapter.toJson(payload.origin), request.key, originalPayloadAdapter.toJson(payload))
                // A captured input can finish in its original private scope after navigation/binding changes.
                inputs.replaceFactInput(null, row)
                OriginalSelectionDraft(row, payload)
            })
    }

    override suspend fun readOriginalSelection(selection: OriginalSelectionDraft) = errors.safeCall {
        guard.bindExact(selection.payload.origin)
        val file = requireNotNull(selection.payload.file)
        val bytes = files.read(file)
        guard.bindExact(selection.payload.origin)
        PreparedUploadImage(file.metadata.fileName, file.metadata.contentType, bytes,
            file.metadata.sourceSizeBytes, file.metadata.preparationDurationMs)
    }

    override suspend fun discardOriginalSelection(binding: LogicalSessionBinding, request: OriginalSubmission) = errors.safeCall {
        require(request.payload.origin.ownerKey == binding.ownerKey && request.payload.origin.ledgerId == binding.ledgerId)
        outbox.withActiveBinding(guard.bindExact(binding)) {
            val rows = inputs.factInputs(binding.ownerKey, binding.ledgerId, request.payload.expenseId)
                .filter { it.formKey.startsWith("original_") }
            if (rows.isNotEmpty()) {
                val selection = decodeOriginalSelection(rows.single())
                check(selection.key == request.key && selection.payload.copy(file = null) == request.payload.copy(file = null))
                inputs.consumeFactInput(selection.row)
            }
        }
    }
}

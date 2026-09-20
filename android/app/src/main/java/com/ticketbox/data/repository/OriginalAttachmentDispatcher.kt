package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.OriginalCleanupRequestDto
import com.ticketbox.data.remote.dto.OriginalCommandReceiptDto
import com.ticketbox.data.remote.dto.OriginalVerificationRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

/** Original attachment commands use the existing dispatch lease and immutable receipt settlement. */
class OriginalAttachmentDispatcher(private val apiProvider: (OutboxRow) -> ApiService,
    private val readOriginal: suspend (UploadIntentFileDescriptor) -> ByteArray) : OutboxMutationDispatcher {
    override val type = PendingMutationType.OriginalAttachment
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Original")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = readOriginalPayload(row) ?: return DispatchResult.Failure("original_intent_unsupported")
        return try {
            val receipt = send(apiProvider(row), payload, requireNotNull(row.idempotencyKey))
            if (!receipt.matches(payload)) DispatchResult.Failure("original_receipt_invalid")
            else DispatchResult.Success(receiptJson = originalReceiptAdapter.toJson(receipt))
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            refusal(error)
        } catch (_: UploadIntentFileException) {
            DispatchResult.Failure("upload_original_unavailable")
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("original_connection_failed")
        } catch (_: RepositoryException) {
            DispatchResult.Failure("upload_binding_changed")
        }
    }

    private suspend fun send(api: ApiService, payload: OriginalAttachmentPayload, key: String): OriginalCommandReceiptDto =
        when (payload.operation) {
            "verify_original" -> api.verifyOriginal(payload.expenseId,
                OriginalVerificationRequestDto(payload.expectedRowVersion, requireNotNull(payload.sha256)), key)
            "replenish_original" -> {
                val file = requireNotNull(payload.file)
                val part = MultipartBody.Part.createFormData("file", file.metadata.fileName,
                    readFile(file).toRequestBody(file.metadata.contentType?.toMediaTypeOrNull()))
                api.replenishOriginal(payload.expenseId, part, payload.expectedRowVersion, requireNotNull(payload.sha256), key)
            }
            "retry_original_cleanup" -> api.retryOriginalCleanup(payload.expenseId,
                OriginalCleanupRequestDto(payload.expectedRowVersion, requireNotNull(payload.cleanupRequestId)), key)
            "cancel_original_cleanup" -> api.cancelOriginalCleanup(payload.expenseId,
                OriginalCleanupRequestDto(payload.expectedRowVersion, requireNotNull(payload.cleanupRequestId)), key)
            else -> error("Unsupported original command")
        }

    private suspend fun readFile(file: UploadIntentFileDescriptor): ByteArray = try {
        readOriginal(file)
    } catch (_: IOException) {
        throw UploadIntentFileException(UploadIntentFileFailure.CONTENT_MISMATCH)
    }

    private fun refusal(error: HttpException): DispatchResult {
        val parsed = errors.parseHttpError(error)
        val code = parsed.errorCode ?: "original_request_refused"
        return when {
            code == "state_conflict" -> DispatchResult.Conflict(code)
            code == "idempotency_key_in_progress" || error.code() in setOf(408, 429) || error.code() >= 500 ->
                DispatchResult.RetryableFailure(code)
            else -> DispatchResult.Failure(code)
        }
    }
}

private fun OriginalCommandReceiptDto.matches(payload: OriginalAttachmentPayload): Boolean =
    operation == payload.operation && expenseId == payload.expenseId && publicId == payload.publicId && rowVersion > 0 &&
        (payload.cleanupRequestId == null || cleanupRequestId == payload.cleanupRequestId) &&
        (payload.sha256 == null || sha256 == payload.sha256)

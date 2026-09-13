package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.UploadResponseDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

/** The durable upload command's only HTTP sender; the drain owns receipt/status persistence. */
class UploadScreenshotDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val payloadAdapter: JsonAdapter<UploadScreenshotPayload>,
    private val receiptAdapter: JsonAdapter<UploadResponseDto>,
    private val readOriginal: suspend (UploadIntentFileDescriptor) -> ByteArray,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.UploadScreenshot
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Upload")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = payloadAdapter.readSupportedUpload(row) ?: return DispatchResult.Failure(UPLOAD_UNSUPPORTED)
        val file = payload.file ?: return DispatchResult.Failure(UPLOAD_UNREADABLE, blocksFollowing = false)
        val bytes = try {
            readOriginal(file)
        } catch (error: CancellationException) {
            throw error
        } catch (_: IOException) {
            return DispatchResult.Failure("upload_original_unavailable", blocksFollowing = false)
        }
        val body = bytes.toRequestBody(file.metadata.contentType?.toMediaTypeOrNull())
        val part = MultipartBody.Part.createFormData("file", file.metadata.fileName, body)
        return sendOriginal(row, payload, part)
    }

    private suspend fun sendOriginal(
        row: OutboxRow,
        payload: UploadScreenshotPayload,
        part: MultipartBody.Part,
    ): DispatchResult {
        val response = try {
            apiProvider(row).uploadScreenshot(part, payload.timezone, requireNotNull(row.idempotencyKey))
        } catch (error: CancellationException) {
            throw error
        } catch (error: HttpException) {
            return refusal(error)
        } catch (_: IOException) {
            // Retain this original for explicit Retry while continuing other readable images.
            return DispatchResult.Failure("upload_connection_failed", blocksFollowing = false)
        } catch (_: RepositoryException) {
            return DispatchResult.Failure("upload_binding_changed")
        }
        if (response.id <= 0L || response.publicId.isBlank() || response.enrichmentTaskPublicId.isBlank()) {
            return DispatchResult.Failure("upload_receipt_invalid")
        }
        return DispatchResult.Success(receiptJson = receiptAdapter.serializeNulls().toJson(response))
    }

    private fun refusal(error: HttpException): DispatchResult {
        val parsed = errors.parseHttpError(error)
        val code = parsed.errorCode
        return when {
            code in NON_RETRYABLE_UPLOAD_ERRORS ->
                DispatchResult.Failure(requireNotNull(code), blocksFollowing = code == "idempotency_key_reused")
            code in setOf(UPLOAD_CAPACITY_FULL, "runtime_version_mismatch", "client_upgrade_required") ->
                DispatchResult.Failure(requireNotNull(code))
            code == "idempotency_key_in_progress" -> DispatchResult.RetryableFailure(code)
            else -> DispatchResult.Failure(code ?: parsed.message, blocksFollowing = error.code() in setOf(401, 403, 409))
        }
    }
}

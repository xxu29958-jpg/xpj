package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import kotlinx.coroutines.CancellationException
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException
import java.io.IOException

/** Only this Outbox consumer sends source admission. A 404 never means a completed capture. */
class DebtBillCaptureDispatcher(
    private val apiProvider: (OutboxRow) -> ApiService,
    private val readOriginal: suspend (UploadIntentFileDescriptor) -> ByteArray,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CaptureDebtBill
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Debt bill capture")

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val payload = DebtBillJson.readCommand(row) ?: return DispatchResult.Failure("debt_bill_payload_unsupported")
        return try {
            val file = payload.file
            val body = readOriginal(file).toRequestBody(file.metadata.contentType?.toMediaTypeOrNull())
            val original = MultipartBody.Part.createFormData("file", file.metadata.fileName, body)
            val part = file.metadata.sourceContext?.let { context ->
                MultipartBody.Part.create(requireNotNull(original.headers).newBuilder()
                    .add("X-Ticketbox-Image-Context", context).build(), body)
            } ?: original
            val receipt = apiProvider(row).captureDebtBill(part, payload.creationKey.toRequestBody(), payload.captureKey)
            if (!receipt.matches(payload)) {
                DispatchResult.Failure("debt_bill_receipt_unverified")
            } else DispatchResult.Success(receiptJson = DebtBillJson.receipt.toJson(receipt))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: HttpException) {
            val code = errors.parseHttpError(error).errorCode
            if (code == "idempotency_key_in_progress") DispatchResult.RetryableFailure(code)
            else DispatchResult.Failure(code ?: "debt_bill_capture_refused", credentialRejected = error.code() == 401)
        } catch (_: IOException) {
            DispatchResult.Failure("debt_bill_original_or_reply_unavailable", blocksFollowing = false)
        } catch (_: RepositoryException) {
            DispatchResult.Failure("debt_bill_binding_changed")
        }
    }
}

private fun com.ticketbox.data.remote.dto.DebtBillCaptureReceiptDto.matches(payload: DebtBillCapturePayload): Boolean =
    publicId.isNotBlank() && captureKey == payload.captureKey && creationKey == payload.creationKey &&
        inputSha256 == payload.file.sha256 && rowVersion > 0L

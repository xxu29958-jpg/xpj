package com.ticketbox.viewmodel

import com.ticketbox.data.local.DebtBillInputEntity
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto
import com.ticketbox.data.remote.dto.DebtBillParseResponseDto
import com.ticketbox.data.repository.DebtBillActions
import com.ticketbox.data.repository.DebtBillCapturePayload
import com.ticketbox.data.repository.DebtBillInput
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.UploadIntentFileDescriptor
import com.ticketbox.data.repository.UploadIntentFileMetadata
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.flow.MutableStateFlow

/** The source command boundary, leaving the actual launcher and ViewModel intact. */
internal class FakeDebtBillActions(private val parse: suspend (String) -> Result<DebtBillSuggestion>) : DebtBillActions {
    val inputs = MutableStateFlow<List<DebtBillInput>>(emptyList())
    var captureGate: kotlinx.coroutines.CompletableDeferred<Unit>? = null
    var captureFailure: Exception? = null
    var loseCaptureReply = false
    val captureKeys = mutableListOf<String>()
    val discardedKeys = mutableListOf<String>()
    var draftWriteFailure: Exception? = null
    var findFailure: Exception? = null
    override fun observe(binding: LogicalSessionBinding) = inputs
    override suspend fun find(binding: LogicalSessionBinding, captureKey: String): Result<DebtBillInput?> =
        findFailure?.let { Result.failure(it) } ?: Result.success(inputs.value.singleOrNull { it.captureKey == captureKey }?.forBinding(binding))
    override suspend fun capture(binding: LogicalSessionBinding, creationKey: String, captureKey: String,
        draftJson: String, image: PreparedUploadImage): Result<DebtBillInput> {
        captureKeys += captureKey
        captureGate?.await()
        captureFailure?.let { return Result.failure(it) }
        val digest = "a".repeat(64)
        val file = UploadIntentFileDescriptor(captureKey, image.bytes.size.toLong(), digest,
            UploadIntentFileMetadata(image.fileName, image.contentType, 0, image.bytes.size.toLong()))
        val payload = DebtBillCapturePayload(1, binding, creationKey, captureKey, file)
        val source = DebtBillCaptureDto("source-$captureKey", creationKey, captureKey, 1, "pending", digest, digest,
            image.fileName, "verified")
        val input = DebtBillInput(DebtBillInputEntity(captureKey, binding.ownerKey, binding.ledgerId, creationKey, "{}", draftJson), payload, source)
        inputs.value += input
        if (loseCaptureReply) return Result.failure(java.io.IOException("Room accepted but reply lost"))
        return Result.success(input)
    }
    override suspend fun saveDraft(captureKey: String, draftJson: String) {
        draftWriteFailure?.let { throw it }
        inputs.value = inputs.value.map { if (it.captureKey == captureKey) it.copy(original = it.original.copy(draftJson = draftJson)) else it }
    }
    override suspend fun refresh(input: DebtBillInput) = Result.success(input)
    override suspend fun suggest(input: DebtBillInput, retry: Boolean): Result<DebtBillParseOutcomeDto> =
        parse(input.payload.file.metadata.fileName).map { value ->
            DebtBillParseOutcomeDto(requireNotNull(input.source).publicId, "parse-original", 2, "succeeded", "test-provider",
                DebtBillParseResponseDto(merchant = value.merchant, principalAmountCents = value.principalAmountCents,
                    installmentCount = value.installmentCount, installmentPeriodMonths = value.installmentPeriodMonths,
                    perPeriodAmountCents = value.perPeriodAmountCents, repaymentDay = value.repaymentDay,
                    sourceText = value.sourceText, confidence = value.confidence))
        }
    override suspend fun recover(input: DebtBillInput, discard: Boolean): Result<Unit> {
        if (discard) discardedKeys += input.captureKey
        return Result.success(Unit)
    }
    override suspend fun original(input: DebtBillInput) = Result.success(byteArrayOf(1))
    override suspend fun original(binding: LogicalSessionBinding, publicId: String) = Result.success(byteArrayOf(1))
    override suspend fun forDebt(binding: LogicalSessionBinding, publicId: String) = Result.success(emptyList<DebtBillCaptureDto>())
}

package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto

// Each repository receives only the codecs for its own commands. The composition
// root supplies the same lazily configured Moshi to writers and dispatchers.
internal class BudgetMutationAdapters(private val moshi: () -> Moshi) {
    val arrangementSaveAdapter: JsonAdapter<com.ticketbox.data.repository.MonthlyArrangementSubmission> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.MonthlyArrangementSubmission::class.java)
    }

    val arrangementReceiptAdapter: JsonAdapter<com.ticketbox.domain.model.MonthlyArrangement> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.domain.model.MonthlyArrangement::class.java)
    }

    val budgetSaveAdapter: JsonAdapter<com.ticketbox.data.repository.BudgetSavePayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.BudgetSavePayload::class.java)
    }

    val budgetReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.BudgetMonthlyDto> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.remote.dto.BudgetMonthlyDto::class.java)
    }

    val manualRateAdapter: JsonAdapter<com.ticketbox.data.repository.ManualRateSubmission> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.ManualRateSubmission::class.java)
    }

    val manualRateReceiptAdapter: JsonAdapter<com.ticketbox.domain.model.ExchangeRate> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.domain.model.ExchangeRate::class.java)
    }
}

internal class RecurringMutationAdapters(private val moshi: () -> Moshi) {
    val recurringCandidateAdapter: JsonAdapter<com.ticketbox.data.repository.RecurringCandidatePayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.RecurringCandidatePayload::class.java)
    }

    val recurringCreateAdapter: JsonAdapter<RecurringItemCreateRequestDto> = lazyJsonAdapter {
        moshi().adapter(RecurringItemCreateRequestDto::class.java)
    }

    val recurringUpdateAdapter: JsonAdapter<RecurringItemUpdateRequestDto> = lazyJsonAdapter {
        moshi().adapter(RecurringItemUpdateRequestDto::class.java)
    }

    val recurringOccurrenceAdapter: JsonAdapter<com.ticketbox.data.repository.RecurringOccurrenceSubmission> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.RecurringOccurrenceSubmission::class.java)
    }
}

internal class DebtMutationAdapters(private val moshi: () -> Moshi) {
    val debtAdjustmentAdapter: JsonAdapter<com.ticketbox.data.repository.DebtAdjustmentPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.DebtAdjustmentPayload::class.java)
    }

    val debtRepaymentAdapter: JsonAdapter<com.ticketbox.data.repository.DebtRepaymentPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.DebtRepaymentPayload::class.java)
    }

    val debtRepaymentReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto::class.java)
    }

    val repaymentReviewAdapter: JsonAdapter<com.ticketbox.data.repository.RepaymentReviewPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.RepaymentReviewPayload::class.java)
    }

    val repaymentDismissAdapter: JsonAdapter<com.ticketbox.data.repository.RepaymentDismissPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.RepaymentDismissPayload::class.java)
    }

    val repaymentDraftReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.RepaymentDraftDto> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.remote.dto.RepaymentDraftDto::class.java)
    }

    val debtVoidAdapter: JsonAdapter<com.ticketbox.data.repository.DebtVoidPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.DebtVoidPayload::class.java)
    }

    val debtRepaymentVoidAdapter: JsonAdapter<com.ticketbox.data.repository.DebtRepaymentVoidPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.DebtRepaymentVoidPayload::class.java)
    }

    val debtVoidReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.DebtDto> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.remote.dto.DebtDto::class.java).serializeNulls()
    }

    val debtKindAdapter: JsonAdapter<com.ticketbox.data.repository.DebtKindPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.DebtKindPayload::class.java)
    }

    val debtCreateAdapter: JsonAdapter<DebtCreateOutboxPayload> = lazyJsonAdapter {
        moshi().adapter(DebtCreateOutboxPayload::class.java)
    }
}

internal class UploadMutationAdapters(private val moshi: () -> Moshi) {
    val uploadPayloadAdapter: JsonAdapter<com.ticketbox.data.repository.UploadScreenshotPayload> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.repository.UploadScreenshotPayload::class.java).serializeNulls()
    }

    val uploadReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.UploadResponseDto> = lazyJsonAdapter {
        moshi().adapter(com.ticketbox.data.remote.dto.UploadResponseDto::class.java).serializeNulls()
    }
}

internal fun <T> lazyJsonAdapter(factory: () -> JsonAdapter<T>): JsonAdapter<T> =
    object : JsonAdapter<T>() {
        private val delegate: JsonAdapter<T> by lazy(factory)

        override fun fromJson(reader: JsonReader): T? = delegate.fromJson(reader)

        override fun toJson(writer: JsonWriter, value: T?) {
            delegate.toJson(writer, value)
        }

        override fun toString(): String = "LazyJsonAdapter"
    }

package com.ticketbox.viewmodel

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.StreamOffsetKind

/** Only raw human values and their original fact basis are serialized; presentation/busy/errors are not. */
@JsonClass(generateAdapter = true)
internal data class FactCorrectionInput(
    val reason: String, val merchant: String, val category: String, val tags: String, val note: String,
    val amountText: String, val currency: CurrencyCode, val currencyTouched: Boolean,
    val expenseTimeText: String, val timeFormJson: String?, val expenseTimeZoneId: String?,
    val valueScore: Int?, val regretScore: Int?,
    val itemDrafts: List<EditableItem>, val itemsTouched: Boolean,
    val splitDrafts: List<EditableSplit>, val splitsTouched: Boolean,
    val itemDraftsInitialized: Boolean, val splitDraftsInitialized: Boolean,
) {
    fun form(basis: Expense): CorrectionFormState = initialCorrectionFormState(basis,
        java.time.ZoneId.of(expenseTimeZoneId ?: "UTC")).copy(open = false, reason = reason, merchant = merchant,
        category = category, tags = tags, note = note, amountText = amountText, currency = currency,
        currencyTouched = currencyTouched, expenseTimeText = expenseTimeText, timeFormJson = timeFormJson,
        expenseTimeZoneId = expenseTimeZoneId, valueScore = valueScore, regretScore = regretScore,
        itemDrafts = itemDrafts, itemsTouched = itemsTouched, splitDrafts = splitDrafts, splitsTouched = splitsTouched,
        itemDraftsInitialized = itemDraftsInitialized, splitDraftsInitialized = splitDraftsInitialized)
}

internal fun CorrectionFormState.originalValues() = FactCorrectionInput(reason, merchant, category, tags, note,
    amountText, currency, currencyTouched, expenseTimeText, timeFormJson, expenseTimeZoneId, valueScore, regretScore,
    itemDrafts, itemsTouched, splitDrafts, splitsTouched, itemDraftsInitialized, splitDraftsInitialized)

@JsonClass(generateAdapter = true)
internal data class ExpenseFactInputDraft(
    val baseline: Expense,
    val correction: FactCorrectionInput? = null,
    val originalItems: ExpenseItems? = null,
    val originalSplits: ExpenseSplits? = null,
    val offsetKind: StreamOffsetKind? = null,
    val amountText: String = "",
    val accountingDate: String = "",
    val reason: String = "",
    val voidTarget: ExpenseOffsetFact? = null,
    val pendingReview: PendingReviewValues? = null,
    val version: Int = 1,
) {
    fun offsetForm() = OffsetFormState(sourceExpense = baseline, kind = requireNotNull(offsetKind),
        amountText = amountText, accountingDate = accountingDate, reason = reason)
    fun voidForm() = VoidOffsetFormState(target = requireNotNull(voidTarget), reason = reason)
}

/** Raw quick-review input; parsing and command construction still belong to the existing review actions. */
@JsonClass(generateAdapter = true)
data class PendingReviewValues(val value: String? = null, val custom: String = "", val confirmed: Boolean = false)

internal object ExpenseFactInputCodec {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(ExpenseFactInputDraft::class.java)
    fun encode(draft: ExpenseFactInputDraft): String = adapter.toJson(draft.copy(baseline = draft.baseline.copy(
        imagePath = null, thumbnailPath = null, fxTask = null)))
    fun decode(json: String, expenseId: Long): ExpenseFactInputDraft = requireNotNull(adapter.fromJson(json)).also {
        require(it.version == 1 && it.baseline.id == expenseId) { "Unrecognized financial input version or target" }
    }
}

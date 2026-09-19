package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.addExpenseCorrectionWireAdapters
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseTimeInput
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

class ExpenseAccountingTimeContractTest {
    private val moshi = Moshi.Builder().addExpenseCorrectionWireAdapters().add(KotlinJsonAdapterFactory()).build()
    private val expenseAdapter = moshi.adapter(ExpenseDto::class.java)
    private val createAdapter = moshi.adapter(ExpenseManualCreateRequestDto::class.java)
    private val jsonAdapter = moshi.adapter(Any::class.java)

    @Test fun originalExpenseReceiptWithoutTimeEvidenceStillDecodes() {
        val receipt = requireNotNull(expenseAdapter.fromJson(OLD_EXPENSE_JSON))
        assertEquals(7L, receipt.rowVersion)
        assertFalse(expenseAdapter.toJson(receipt).contains("accounting_time"))
    }

    @Test fun oldNestedAcceptedExpenseStillSuppliesTheOriginalVersion() {
        val original = """{"expenseId":9,"acceptedExpense":$OLD_EXPENSE_JSON}"""
        val receipt = requireNotNull(moshi.adapter(ExpenseAcceptanceReceipt::class.java).fromJson(original))
        assertEquals(9L, receipt.expenseId)
        assertEquals(7L, receipt.acceptedExpense?.rowVersion)
        assertFalse(expenseAdapter.toJson(receipt.acceptedExpense).contains("accounting_time"))
    }

    @Test fun serverTimeEvidenceSurvivesTheRealDto() {
        val precise = """{"precision":"instant","instant_utc":"2026-04-30T16:30:00Z","user_local_date":"2026-05-01",
            "source_timezone":"Asia/Shanghai","source_utc_offset_seconds":28800,"accounting_date":"2026-05-01",
            "calendar_revision":3,"basis":"user_input"}"""
        for (time in listOf(TIME_JSON, precise)) {
            val receipt = requireNotNull(expenseAdapter.fromJson(withTime(OLD_EXPENSE_JSON, time)))
            assertEquals(jsonAdapter.fromJson(time), (jsonAdapter.fromJson(expenseAdapter.toJson(receipt)) as Map<*, *>)["accounting_time"])
            assertEquals(receipt.accountingTime?.toDomain(), receipt.toEntity("owner").toDomain().accountingTime)
        }
    }

    @Test fun flatAndRecurringCreateKeepOldAbsentFieldsAndNewFrozenInput() {
        val wrappedAdapter = moshi.adapter(RecurringPaymentCreatePayload::class.java)
        for (body in listOf(OLD_CREATE_JSON, OLD_CREATE_JSON.dropLast(1) + ",\"time_input\":$INPUT_JSON}")) {
            val wrapped = """{"request":$body,"seriesPublicId":"series-1","period":"2026-05","retired":false}"""
            for (json in listOf(body, wrapped)) {
                val request = requireNotNull(decodeManualCreateRequest(createAdapter, wrappedAdapter, json))
                assertEquals(jsonAdapter.fromJson(body), jsonAdapter.fromJson(createAdapter.toJson(request)))
            }
        }
    }

    @Test fun correctionTimeInputPreservesAbsentNullAndValue() {
        val adapter = moshi.adapter(ExpenseCorrectionRequestDto::class.java)
        for (suffix in listOf("", ",\"time_input\":null", ",\"time_input\":$INPUT_JSON")) {
            val original = """{"expected_row_version":7,"reason":"Correct the recorded day"$suffix}"""
            assertEquals(jsonAdapter.fromJson(original), jsonAdapter.fromJson(adapter.toJson(requireNotNull(adapter.fromJson(original)))))
        }
    }

    @Test fun dateOnlyDraftUsesOneFrozenInputWithoutLegacyInstantAliases() {
        val selected = ExpenseTimeInput("date_only", 3, "2026-05-01")
        val draft = ExpenseDraft(amountCents = 100, merchant = "Original", category = "其他", note = null,
            expenseTime = "2026-05-02T12:00:00Z", tags = null, valueScore = null, regretScore = null,
            ledgerHomeCurrency = CurrencyCode.CNY, timeInput = selected)
        val request = draft.toManualCreateRequest("original-ref")
        assertEquals(selected.toRequest(), request.timeInput)
        assertNull(request.expenseTime)
        assertNull(request.spentAt)
        val cached = draft.toLocalCreateEntity("owner", "original-ref").toDomain()
        assertNull(cached.expenseTime)
        assertEquals(selected.userLocalDate, cached.accountingTime?.userLocalDate)
        assertEquals(selected.calendarRevision, cached.accountingTime?.calendarRevision)
    }

    @Test fun timeOnlyCorrectionIsAdmittedAndAbsenceStillMeansNoChange() {
        val selected = ExpenseTimeInput("date_only", 3, "2026-05-01")
        val changed = ExpenseCorrectionDraft("Correct recorded day", timeInput = selected, timeInputChanged = true).toRequest(7)
        assertEquals(selected.toRequest(), changed.timeInput.value)
        assertEquals(true, changed.timeInput.changed)
        assertNull(changed.correctionAdmissionError())
        assertEquals(true, ExpenseCorrectionDraft("Correct day", timeInput = selected, timeInputChanged = true)
            .changesAdvisorPayloadAgainst(requireNotNull(expenseAdapter.fromJson(OLD_EXPENSE_JSON)).toDomain()))
        val unchanged = ExpenseCorrectionDraft("Correct note", note = "New note").toRequest(7)
        assertFalse(unchanged.timeInput.changed)
    }

    @Test fun noteOnlyEditDoesNotReplaceCapturedTimeOrAddCalendarToLegacyRequest() {
        val selected = ExpenseTimeInput("date_only", 3, "2026-05-01")
        val baseline = requireNotNull(expenseAdapter.fromJson(OLD_EXPENSE_JSON)).toDomain().copy(
            expenseTime = null, accountingTime = selected.toCapturedTime().copy(accountingDate = "2026-05-01"))
        val draft = ExpenseDraft(amountCents = 100, merchant = "Original", category = "其他", note = "New note",
            expenseTime = null, tags = null, valueScore = null, regretScore = null, timeInput = selected)
        val request = draft.toRequest(baseline)
        assertNull(request.timeInput)
        assertNull(request.spentAt)
        assertNull(request.expenseTime)
        assertNull(draft.copy(timeInput = null).toRequest(baseline).timeInput)
    }

    @Test fun sameVersionOldReceiptCannotEraseKnownTimeButNewVersionCanReplaceIt() = runTest {
        val dao = FakeExpenseDao()
        val adopted = requireNotNull(expenseAdapter.fromJson(withTime(OLD_EXPENSE_JSON)))
        val old = requireNotNull(expenseAdapter.fromJson(OLD_EXPENSE_JSON))
        dao.applyServerExpense("owner", adopted.toEntity("owner"))
        dao.applyServerExpense("owner", old.toEntity("owner"))
        val stored = requireNotNull(dao.findByServerId("owner", 9)).toDomain()
        val projection = moshi.adapter(com.ticketbox.domain.model.Expense::class.java).toJsonValue(stored) as Map<*, *>
        assertEquals("2026-05-01", (projection["accountingTime"] as? Map<*, *>)?.get("accountingDate"))
        dao.applyServerExpense("owner", old.copy(rowVersion = 8).toEntity("owner"))
        val next = moshi.adapter(com.ticketbox.domain.model.Expense::class.java)
            .toJsonValue(requireNotNull(dao.findByServerId("owner", 9)).toDomain()) as Map<*, *>
        assertFalse(next.containsKey("accountingTime"))
    }

    private fun withTime(body: String, time: String = TIME_JSON): String = body.dropLast(1) + ",\"accounting_time\":$time}"

    companion object {
        private const val OLD_EXPENSE_JSON = """{"id":9,"public_id":"expense-9","amount_cents":100,"home_currency":"CNY","original_currency":"CNY","category":"其他","source":"手动记账","duplicate_status":"none","status":"confirmed","expense_time":"2026-04-30T16:30:00Z","created_at":"2026-05-01T00:00:00Z","updated_at":"2026-05-01T00:00:00Z","row_version":7}"""
        private const val OLD_CREATE_JSON = """{"original_currency":"CNY","original_amount":"1.00","spent_at":"2026-04-30T16:30:00Z","merchant":"Original","category":"其他","expense_time":"2026-04-30T16:30:00Z","client_ref":"original-ref","home_currency_code":"CNY"}"""
        private const val TIME_JSON = """{"precision":"unknown","accounting_date":"2026-05-01","calendar_revision":1,"basis":"legacy_expense_time"}"""
        private const val INPUT_JSON = """{"precision":"date_only","calendar_revision":1,"user_local_date":"2026-05-01"}"""
    }
}

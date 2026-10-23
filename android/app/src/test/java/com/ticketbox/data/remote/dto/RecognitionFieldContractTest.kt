package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.ticketbox.domain.model.RecognitionFieldCandidate
import com.ticketbox.ui.screens.expense.readFieldChoices
import com.ticketbox.ui.screens.expense.updateFieldChoice
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class RecognitionFieldContractTest {
    @Test fun originalNumericTokenAndChoiceSurviveDraftAndWireWithoutRelabelingLegacy() {
        val moshi = Moshi.Builder().build()
        val candidate = moshi.adapter(RecognitionFieldCandidate::class.java).fromJson("""
            {"field":"amount_cents","id":"candidate","value":9007199254740991,"label":"支付金额",
             "original_text":"支付金额","explanation":"原件","role":"payment","can_apply":true,
             "evidence_public_id":"source","parser_version":"parser","currency_code":"CNY","minor_unit_exponent":2}
        """.trimIndent())!!
        assertEquals("9007199254740991", candidate.value)
        val saved = updateFieldChoice(null, candidate.field, candidate.choice())
        val legacy = ExpenseUpdateRequest(expectedRowVersion = 8, merchant = null, category = null, note = null,
            expenseTime = null, tags = null, valueScore = null, regretScore = null)
        val request = legacy.copy(recognitionFieldChoices = readFieldChoices(saved))
        val adapter = moshi.adapter(ExpenseUpdateRequest::class.java)
        assertEquals(request, adapter.fromJson(adapter.toJson(request)))
        assertEquals(listOf(candidate.choice()), readFieldChoices(saved))
        assertEquals(emptyList(), readFieldChoices(updateFieldChoice(saved, candidate.field)))
        assertFalse(adapter.toJson(legacy).contains("recognition_field_choices"))
        val learned = candidate.copy(selectionIntent = "bookkeeping")
        assertEquals("bookkeeping", readFieldChoices(updateFieldChoice(null, learned.field, learned.choice())).single().intent)
        val corrected = candidate.choice().copy(intent = "original_correction")
        val correctedRequest = legacy.copy(recognitionFieldChoices = readFieldChoices(updateFieldChoice(null, candidate.field, corrected)))
        assertEquals(correctedRequest, adapter.fromJson(adapter.toJson(correctedRequest)))
        assertEquals("original_correction", correctedRequest.recognitionFieldChoices?.single()?.intent)
    }
}

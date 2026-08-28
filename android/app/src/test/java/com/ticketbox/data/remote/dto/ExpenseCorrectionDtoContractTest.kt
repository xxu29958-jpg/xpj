package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private val serverExpenseJson =
    """
    {
      "id":42,
      "public_id":"expense-public",
      "amount_cents":1880,
      "merchant":"咖啡店",
      "category":"餐饮",
      "note":"",
      "source":"Android截图",
      "image_path":null,
      "thumbnail_path":null,
      "image_hash":null,
      "raw_text":null,
      "confidence":null,
      "duplicate_status":"none",
      "duplicate_of_id":null,
      "duplicate_reason":null,
      "tags":null,
      "value_score":null,
      "regret_score":null,
      "status":"confirmed",
      "expense_time":"2026-05-13T00:00:00Z",
      "created_at":"2026-05-13T00:00:00Z",
      "updated_at":"2026-05-13T00:05:00Z",
      "row_version":8,
      "fact_revision":2,
      "confirmed_at":"2026-05-13T00:01:00Z",
      "rejected_at":null
    }
    """.trimIndent()

private val serverRevisionJson =
    """
    {
      "public_id":"revision-public",
      "revision_number":2,
      "change_kind":"correction",
      "reason":"金额和拆账录错了",
      "changed_fields":["amount_cents","items","splits"],
      "before":{"amount_cents":1280},
      "after":{"amount_cents":1880},
      "actor_account_name":"我",
      "actor_device_name":"Pixel",
      "created_at":"2026-05-13T00:05:00Z"
    }
    """.trimIndent()

class ExpenseCorrectionDtoContractTest {
    private val moshi = Moshi.Builder()
        .addExpenseCorrectionWireAdapters()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun correctionRequestSerializesOneCompositeIntent() {
        val json = moshi.adapter(ExpenseCorrectionRequestDto::class.java).toJson(
            ExpenseCorrectionRequestDto(
                expectedRowVersion = 7L,
                reason = "金额和拆账录错了",
                amountCents = 1880L,
                merchant = "",
                items = listOf(
                    ExpenseItemRequestDto(
                        name = "咖啡",
                        amountCents = 1880L,
                    ),
                ),
                splits = emptyList(),
            ),
        )

        assertTrue(json.contains("\"expected_row_version\":7"))
        assertTrue(json.contains("\"reason\":\"金额和拆账录错了\""))
        assertTrue(json.contains("\"amount_cents\":1880"))
        assertTrue(json.contains("\"merchant\":\"\""), "blank is the explicit clear value")
        assertTrue(json.contains("\"items\":["))
        assertTrue(json.contains("\"splits\":[]"), "an empty list explicitly clears splits")
        assertFalse(json.contains("\"category\""), "unchanged null fields must stay absent")
    }

    @Test
    fun correctionRequestPreservesExplicitNullAcrossOutboxRoundTrip() {
        val adapter = moshi.adapter(ExpenseCorrectionRequestDto::class.java)
        val firstJson = adapter.toJson(
            ExpenseCorrectionRequestDto(
                expectedRowVersion = 0L,
                reason = "清除误填信息",
                expenseTime = CorrectionOptionalString.changed(null),
                valueScore = CorrectionOptionalInt.changed(null),
            ),
        )

        assertTrue(firstJson.contains("\"expense_time\":null"), firstJson)
        assertTrue(firstJson.contains("\"value_score\":null"), firstJson)
        assertFalse(firstJson.contains("\"regret_score\""), firstJson)

        val replay = requireNotNull(adapter.fromJson(firstJson)).copy(expectedRowVersion = 9L)
        val replayJson = adapter.toJson(replay)
        assertTrue(replayJson.contains("\"expected_row_version\":9"), replayJson)
        assertTrue(replayJson.contains("\"expense_time\":null"), replayJson)
        assertTrue(replayJson.contains("\"value_score\":null"), replayJson)
        assertFalse(replayJson.contains("\"regret_score\""), replayJson)
    }

    @Test
    fun correctionResponseAndRevisionPageParseCurrentServerShape() {
        val response = requireNotNull(
            moshi.adapter(ExpenseCorrectionResponseDto::class.java).fromJson(
                """{"expense":$serverExpenseJson,"revision":$serverRevisionJson}""",
            ),
        )
        val page = requireNotNull(
            moshi.adapter(ExpenseRevisionPageDto::class.java).fromJson(
                """{"items":[$serverRevisionJson],"page":1,"page_size":50,"total":2}""",
            ),
        )

        assertEquals(2L, response.expense.factRevision)
        assertEquals(8L, response.expense.rowVersion)
        assertEquals(listOf("amount_cents", "items", "splits"), response.revision.changedFields)
        assertEquals("我", response.revision.actorAccountName)
        assertEquals(2, page.total)
        assertEquals(50, page.pageSize)
    }

    @Test
    fun confirmedBatchSerializesEveryLongOccTokenAsAJsonObjectKey() {
        val json = moshi.adapter(ConfirmedExpenseBatchUpdateRequestDto::class.java).toJson(
            ConfirmedExpenseBatchUpdateRequestDto(
                expenseIds = listOf(7L, 42L),
                expectedRowVersionById = mapOf(7L to 3L, 42L to 9L),
                category = "购物",
                reason = "统一修正历史分类",
            ),
        )

        assertTrue(json.contains("\"expense_ids\":[7,42]"), json)
        assertTrue(
            json.contains("\"expected_row_version_by_id\":{\"7\":3,\"42\":9}"),
            json,
        )
        assertTrue(json.contains("\"reason\":\"统一修正历史分类\""), json)
        assertFalse(json.contains("\"tags\""), "an untouched batch field must remain absent")
    }
}

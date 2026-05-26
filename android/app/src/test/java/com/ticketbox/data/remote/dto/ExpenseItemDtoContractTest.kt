package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseItemDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun expenseItemsParsesCurrentServerShapeAndSerializesReplace() {
        val dto = requireNotNull(
            moshi.adapter(ExpenseItemsResponseDto::class.java).fromJson(
                """
                {
                  "expense_id": 1,
                  "parent_amount_cents": 1500,
                  "items_total_amount_cents": 1250,
                  "mismatch_cents": 250,
                  "items": [
                    {
                      "public_id": "item-1",
                      "position": 0,
                      "name": "拿铁",
                      "quantity_text": "1杯",
                      "unit_price_cents": 500,
                      "amount_cents": 500,
                      "category": "餐饮",
                      "raw_text": "拿铁 1杯 5.00",
                      "confidence": 0.92,
                      "is_ocr_draft": true,
                      "created_at": "2026-05-03T04:20:00Z",
                      "updated_at": "2026-05-03T04:20:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(ExpenseItemReplaceRequestDto::class.java).toJson(
            ExpenseItemReplaceRequestDto(
                expectedUpdatedAt = "2026-05-03T04:20:00Z",
                items = listOf(
                    ExpenseItemRequestDto(
                        name = "拿铁",
                        quantityText = "1杯",
                        unitPriceCents = 500,
                        amountCents = 500,
                        category = "餐饮",
                        rawText = "拿铁 1杯 5.00",
                        confidence = 0.92,
                    ),
                ),
            ),
        )

        val item = dto.items.single()
        assertEquals("item-1", item.publicId)
        assertEquals(250L, dto.mismatchCents)
        assertEquals(true, item.isOcrDraft)
        // ADR-0035: kind 默认 'product'；老服务端响应不含字段时 DTO 用默认值
        assertEquals("product", item.kind)
        assertEquals("no_items", dto.itemsSumStatus)
        assertEquals(
            """{"expected_updated_at":"2026-05-03T04:20:00Z","items":[{"name":"拿铁","kind":"product","quantity_text":"1杯","unit_price_cents":500,"amount_cents":500,"category":"餐饮","raw_text":"拿铁 1杯 5.00","confidence":0.92}]}""",
            requestJson,
        )
    }
}

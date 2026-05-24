package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class DashboardCardsDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun dashboardCardsParseCurrentServerShapeAndSerializeUpdate() {
        val dto = requireNotNull(
            moshi.adapter(DashboardCardsResponseDto::class.java).fromJson(
                """
                {
                  "surface": "web",
                  "items": [
                    {"key": "goals", "title": "目标", "visible": true, "position": 0},
                    {"key": "reports", "title": "报表", "visible": false, "position": 1}
                  ]
                }
                """.trimIndent(),
            ),
        )
        val requestJson = moshi.adapter(DashboardCardsUpdateRequestDto::class.java).toJson(
            DashboardCardsUpdateRequestDto(
                cards = listOf(
                    DashboardCardUpdateRequestDto("goals", visible = true, position = 0),
                    DashboardCardUpdateRequestDto("reports", visible = false, position = 1),
                ),
            ),
        )

        assertEquals("web", dto.surface)
        assertEquals("goals", dto.items.first().key)
        assertEquals(false, dto.items[1].visible)
        assertEquals(
            """{"cards":[{"key":"goals","visible":true,"position":0},{"key":"reports","visible":false,"position":1}]}""",
            requestJson,
        )
    }
}

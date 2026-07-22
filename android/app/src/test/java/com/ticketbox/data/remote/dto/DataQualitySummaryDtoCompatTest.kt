package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.repository.toDomain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * N-1 compatibility: the split/caliber fields were added after the summary
 * endpoint first shipped, so an old backend's payload omits them. The DTO
 * must still decode (nullable with defaults), mapping to nulls the UI reads
 * as "unknown composition — fall back to the aggregate caliber".
 */
class DataQualitySummaryDtoCompatTest {

    private val moshi: Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    @Test
    fun legacyPayloadWithoutSplitFieldsDecodesToNullComposition() {
        val dto = moshi.adapter(DataQualitySummaryDto::class.java).fromJson(LEGACY_PAYLOAD)

        assertEquals(9, dto?.pendingTotal)
        assertEquals(3, dto?.missingCategory)
        assertEquals(6, dto?.readyToConfirm)
        assertNull(dto?.missingCategoryPending)
        assertNull(dto?.missingCategoryConfirmed)
        assertNull(dto?.readyToConfirmCategorized)

        val domain = dto?.toDomain()
        assertNull(domain?.missingCategoryPending)
        assertNull(domain?.missingCategoryConfirmed)
        assertNull(domain?.readyToConfirmCategorized)
    }

    @Test
    fun currentPayloadDecodesSplitFields() {
        val dto = moshi.adapter(DataQualitySummaryDto::class.java).fromJson(CURRENT_PAYLOAD)

        assertEquals(2, dto?.missingCategoryPending)
        assertEquals(1, dto?.missingCategoryConfirmed)
        assertEquals(4, dto?.readyToConfirmCategorized)
    }

    private companion object {
        // Shape the endpoint returned before the split fields existed.
        const val LEGACY_PAYLOAD = """
            {
              "pending_total": 9,
              "missing_amount": 1,
              "missing_merchant": 2,
              "missing_category": 3,
              "suspected_duplicates": 4,
              "confirmed_without_image": 5,
              "ready_to_confirm": 6,
              "oldest_pending_age_days": 2,
              "generated_at": "2026-07-18T00:00:00Z"
            }
        """

        const val CURRENT_PAYLOAD = """
            {
              "pending_total": 9,
              "missing_amount": 1,
              "missing_merchant": 2,
              "missing_category": 3,
              "missing_category_pending": 2,
              "missing_category_confirmed": 1,
              "suspected_duplicates": 4,
              "confirmed_without_image": 5,
              "ready_to_confirm": 6,
              "ready_to_confirm_categorized": 4,
              "oldest_pending_age_days": 2,
              "generated_at": "2026-07-18T00:00:00Z"
            }
        """
    }
}

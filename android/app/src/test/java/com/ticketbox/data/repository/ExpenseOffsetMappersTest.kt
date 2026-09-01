package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseOffsetStatusDto
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.StreamOffsetKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class ExpenseOffsetMappersTest {
    @Test
    fun bundleUsesServerPublishedStreamProjectionWithoutRecomputingIt() {
        val dto = expenseFactBundleDtoFixture()

        val cache = dto.toCacheProjection("owner")
        val domain = dto.toDomain()

        assertNull(cache.root.streamDate)
        assertEquals(1_200L, cache.root.streamAmountCents)
        assertEquals(-300L, cache.activeOffsets.single().streamAmountCents)
        assertEquals(ExpenseLineageStatus.PartiallyRefunded, domain.financialSummary.status)
        assertEquals(StreamOffsetKind.Refund, domain.activeOffsets.single().kind)
    }

    @Test
    fun activeOffsetProjectionRejectsVoidedRows() {
        val voided = expenseOffsetResponseDtoFixture().copy(status = ExpenseOffsetStatusDto.Voided)

        assertFailsWith<RepositoryException> {
            expenseFactBundleDtoFixture(activeOffsets = listOf(voided)).toCacheProjection("owner")
        }
    }
}

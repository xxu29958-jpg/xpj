package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class IncomePlanMappersTest {

    @Test
    fun dtoMapsToDomainAcrossKnownSourceTypes() {
        val dto = IncomePlanDto(
            publicId = "abc-123",
            label = "我的工资",
            sourceType = "salary",
            amountCents = 1_000_000,
            payDay = 10,
            status = "active",
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = "2026-05-15T08:00:00Z",
            rowVersion = 1L,
            archivedAt = null,
        )

        val plan = dto.toDomain()

        assertEquals("abc-123", plan.publicId)
        assertEquals("我的工资", plan.label)
        assertEquals(IncomeSourceType.SALARY, plan.sourceType)
        assertEquals(1_000_000L, plan.amountCents)
        assertEquals(10, plan.payDay)
        assertEquals(IncomePlanStatus.ACTIVE, plan.status)
        assertNull(plan.archivedAt)
    }

    @Test
    fun unknownSourceTypeFallsBackToOther() {
        val dto = baseDto().copy(sourceType = "lottery_winnings")
        val plan = dto.toDomain()
        assertEquals(IncomeSourceType.OTHER, plan.sourceType)
    }

    @Test
    fun nullishStatusFallsBackToActive() {
        val plan = baseDto().copy(status = "").toDomain()
        assertEquals(IncomePlanStatus.ACTIVE, plan.status)
    }

    @Test
    fun draftSerialisesToCreateRequestUsingWireValues() {
        val draft = IncomePlanDraft(
            label = "  我的副业  ",
            sourceType = IncomeSourceType.FREELANCE,
            amountCents = 300_000,
            payDay = 20,
        )
        val request = draft.toCreateRequest()
        assertEquals("我的副业", request.label) // whitespace trimmed
        assertEquals("freelance", request.sourceType)
        assertEquals(300_000L, request.amountCents)
        assertEquals(20, request.payDay)
    }

    @Test
    fun patchSerialisesOnlyProvidedFields() {
        val patch = IncomePlanPatch(
            expectedRowVersion = 1L,
            amountCents = 555_000,
            payDay = 15,
        )
        val request = patch.toUpdateRequest()
        assertEquals(1L, request.expectedRowVersion)
        assertNull(request.label)
        assertNull(request.sourceType)
        assertEquals(555_000L, request.amountCents)
        assertEquals(15, request.payDay)
    }

    @Test
    fun patchTrimsLabelWhenProvided() {
        val patch = IncomePlanPatch(
            expectedRowVersion = 1L,
            label = "  重命名  ",
        )
        val request = patch.toUpdateRequest()
        assertEquals("重命名", request.label)
        assertEquals(1L, request.expectedRowVersion)
    }

    private fun baseDto() = IncomePlanDto(
        publicId = "x",
        label = "y",
        sourceType = "salary",
        amountCents = 100,
        payDay = 1,
        status = "active",
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
        archivedAt = null,
    )
}

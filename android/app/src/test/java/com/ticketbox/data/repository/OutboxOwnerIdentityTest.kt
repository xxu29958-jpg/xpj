package com.ticketbox.data.repository

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class OutboxOwnerIdentityTest {
    @Test
    fun storageKeyRoundTripsTheFourServerIssuedIds() {
        val owner = owner()

        assertEquals(owner, OutboxOwnerIdentity.parseOrNull(owner.storageKey))
        assertEquals(
            "v1:60000000-0000-0000-0000-000000000001:" +
                "60000000-0000-0000-0000-000000000002:" +
                "60000000-0000-0000-0000-000000000003:" +
                "60000000-0000-0000-0000-000000000004",
            owner.storageKey,
        )
    }

    @Test
    fun malformedOrNonCanonicalIdsCannotBecomeDurableOwners() {
        assertNull(
            OutboxOwnerIdentity.fromOrNull(
                serverId = "SERVER",
                dataGeneration = "60000000-0000-0000-0000-000000000002",
                accountPublicId = "60000000-0000-0000-0000-000000000003",
                devicePublicId = "60000000-0000-0000-0000-000000000004",
            ),
        )
        assertNull(OutboxOwnerIdentity.parseOrNull("v1:too:few:parts"))
        assertNull(OutboxOwnerIdentity.parseOrNull(owner().storageKey.uppercase()))
    }

    private fun owner(): OutboxOwnerIdentity = requireNotNull(
        OutboxOwnerIdentity.fromOrNull(
            serverId = "60000000-0000-0000-0000-000000000001",
            dataGeneration = "60000000-0000-0000-0000-000000000002",
            accountPublicId = "60000000-0000-0000-0000-000000000003",
            devicePublicId = "60000000-0000-0000-0000-000000000004",
        ),
    )
}

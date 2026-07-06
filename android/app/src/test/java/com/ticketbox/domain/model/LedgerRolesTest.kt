package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LedgerRolesTest {
    @Test
    fun onlyKnownWriterRolesCanModify() {
        assertTrue(ledgerRoleCanModify("owner"))
        assertTrue(ledgerRoleCanModify("member"))
        assertFalse(ledgerRoleCanModify("viewer"))
        assertFalse(ledgerRoleCanModify(null))
        assertFalse(ledgerRoleCanModify(""))
        assertFalse(ledgerRoleCanModify("admin"))
    }
}

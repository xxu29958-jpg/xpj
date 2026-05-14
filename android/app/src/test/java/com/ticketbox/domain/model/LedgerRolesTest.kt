package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LedgerRolesTest {
    @Test
    fun roleLabelsUseUnifiedV05Words() {
        assertEquals("拥有者", ledgerRoleLabel("owner"))
        assertEquals("成员", ledgerRoleLabel("member"))
        assertEquals("只读", ledgerRoleLabel("viewer"))
        assertEquals("未知", ledgerRoleLabel(null))
    }

    @Test
    fun scopeLabelsUsePersonalAndSharedLedgerWords() {
        assertEquals("个人账本", ledgerScopeLabel(isDefault = true))
        assertEquals("共享账本", ledgerScopeLabel(isDefault = false))
    }

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

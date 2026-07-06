package com.ticketbox.ui.components

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class LedgerLabelsTest {
    @Test
    fun roleLabelsUseSharedResourceIds() {
        assertEquals(R.string.settings_account_role_owner, ledgerRoleLabelRes("owner"))
        assertEquals(R.string.settings_account_role_member, ledgerRoleLabelRes("member"))
        assertEquals(R.string.settings_account_role_viewer, ledgerRoleLabelRes("viewer"))
        assertEquals(R.string.settings_account_role_unknown, ledgerRoleLabelRes(null))
        assertNull(ledgerRoleLabelRes("auditor"))
    }

    @Test
    fun scopeLabelsUsePersonalAndSharedLedgerResourceIds() {
        assertEquals(R.string.settings_account_scope_personal, ledgerScopeLabelRes(isDefault = true))
        assertEquals(R.string.settings_account_scope_shared, ledgerScopeLabelRes(isDefault = false))
    }
}

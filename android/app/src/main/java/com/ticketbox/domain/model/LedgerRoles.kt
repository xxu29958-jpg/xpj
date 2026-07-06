package com.ticketbox.domain.model

const val LEDGER_ROLE_OWNER = "owner"
const val LEDGER_ROLE_MEMBER = "member"
const val LEDGER_ROLE_VIEWER = "viewer"

fun ledgerRoleCanModify(role: String?): Boolean = when (role?.trim()) {
    LEDGER_ROLE_OWNER, LEDGER_ROLE_MEMBER -> true
    else -> false
}

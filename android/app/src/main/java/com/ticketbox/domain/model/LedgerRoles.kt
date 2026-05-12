package com.ticketbox.domain.model

const val LEDGER_ROLE_OWNER = "owner"
const val LEDGER_ROLE_MEMBER = "member"
const val LEDGER_ROLE_VIEWER = "viewer"

fun ledgerRoleCanModify(role: String?): Boolean = role?.trim() != LEDGER_ROLE_VIEWER

fun ledgerRoleLabel(role: String?): String = when (role?.trim()) {
    LEDGER_ROLE_OWNER -> "拥有者"
    LEDGER_ROLE_MEMBER -> "成员"
    LEDGER_ROLE_VIEWER -> "只读"
    null, "" -> "未知"
    else -> role
}

fun ledgerScopeLabel(isDefault: Boolean): String =
    if (isDefault) "个人账本" else "共享账本"

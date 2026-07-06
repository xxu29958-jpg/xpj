package com.ticketbox.ui.components

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER

@Composable
internal fun ledgerRoleLabelText(role: String?): String {
    val labelRes = ledgerRoleLabelRes(role)
    return if (labelRes != null) {
        stringResource(labelRes)
    } else {
        role.orEmpty()
    }
}

@StringRes
internal fun ledgerRoleLabelRes(role: String?): Int? = when (role?.trim()) {
    LEDGER_ROLE_OWNER -> R.string.settings_account_role_owner
    LEDGER_ROLE_MEMBER -> R.string.settings_account_role_member
    LEDGER_ROLE_VIEWER -> R.string.settings_account_role_viewer
    null, "" -> R.string.settings_account_role_unknown
    else -> null
}

@Composable
internal fun ledgerScopeLabelText(isDefault: Boolean): String =
    stringResource(ledgerScopeLabelRes(isDefault))

@StringRes
internal fun ledgerScopeLabelRes(isDefault: Boolean): Int =
    if (isDefault) {
        R.string.settings_account_scope_personal
    } else {
        R.string.settings_account_scope_shared
    }

package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun SettingsRoleChip(
    role: String,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    val cleanRole = role.trim()
    val container = when (cleanRole) {
        LEDGER_ROLE_OWNER -> visuals.chipSelected
        LEDGER_ROLE_MEMBER -> MaterialTheme.colorScheme.surfaceVariant
        LEDGER_ROLE_VIEWER -> visuals.chipUnselected
        else -> visuals.chipUnselected
    }
    val content = when (cleanRole) {
        LEDGER_ROLE_OWNER -> visuals.primary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    SettingsInlineChip(
        text = settingsLedgerRoleLabel(role),
        container = container,
        content = content,
        modifier = modifier,
    )
}

@Composable
internal fun SettingsLedgerScopeChip(
    isDefault: Boolean,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    SettingsInlineChip(
        text = settingsLedgerScopeLabel(isDefault),
        container = if (isDefault) visuals.chipSelected else visuals.chipUnselected,
        content = if (isDefault) visuals.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

@Composable
internal fun SettingsCurrentChip(
    text: String,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    SettingsInlineChip(
        text = text,
        container = visuals.chipSelected,
        content = visuals.primary,
        modifier = modifier,
    )
}

@Composable
internal fun settingsLedgerRoleLabel(role: String?): String = when (role?.trim()) {
    LEDGER_ROLE_OWNER -> stringResource(R.string.settings_account_role_owner)
    LEDGER_ROLE_MEMBER -> stringResource(R.string.settings_account_role_member)
    LEDGER_ROLE_VIEWER -> stringResource(R.string.settings_account_role_viewer)
    null, "" -> stringResource(R.string.settings_account_role_unknown)
    else -> role.trim()
}

@Composable
private fun settingsLedgerScopeLabel(isDefault: Boolean): String =
    stringResource(
        if (isDefault) {
            R.string.settings_account_scope_personal
        } else {
            R.string.settings_account_scope_shared
        },
    )

@Composable
private fun SettingsInlineChip(
    text: String,
    container: androidx.compose.ui.graphics.Color,
    content: androidx.compose.ui.graphics.Color,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    Box(
        modifier = modifier
            .background(container.copy(alpha = 0.86f), shape)
            .border(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.34f), shape)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = content,
            maxLines = 1,
        )
    }
}

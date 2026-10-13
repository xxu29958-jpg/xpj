package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Group
import androidx.compose.material.icons.outlined.MailOutline
import androidx.compose.material.icons.outlined.PersonOutline
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material.icons.outlined.VpnKey
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.SettingsColors

internal data class SettingsDataAction(val label: String, val confirmed: Boolean? = null)

@Composable
internal fun SettingsDataRow(
    title: String,
    subtitle: String,
    icon: ImageVector,
    action: SettingsDataAction,
    onClick: (() -> Unit)?,
) {
    val badge = when (icon) {
        Icons.Outlined.Sync, Icons.Outlined.VpnKey, Icons.Outlined.MailOutline,
        Icons.Outlined.PersonOutline -> SettingsColors.appearanceEntry
        Icons.Outlined.Storage, Icons.AutoMirrored.Outlined.Send, Icons.Outlined.Group -> SettingsColors.householdEntry
        Icons.Outlined.Inventory2 -> SettingsColors.connectionEntry
        else -> SettingsColors.generalEntry
    }
    Column {
        Row(
            Modifier.fillMaxWidth().clickable(enabled = onClick != null, role = Role.Button) { onClick?.invoke() }
                .alpha(if (onClick != null) 1f else AppAlpha.strong)
                .heightIn(min = 80.dp).padding(vertical = AppSpacing.contentGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SettingsEntryIcon(icon, Modifier.size(40.dp), background = badge,
                shape = RoundedCornerShape(14.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = AppTextHierarchy.heading.weight)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (action.label.isNotBlank()) Text(action.label, style = MaterialTheme.typography.labelLarge,
                color = if (action.confirmed == true) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                modifier = if (action.confirmed != null) Modifier.clip(RoundedCornerShape(10.dp))
                    .background(if (action.confirmed) SettingsColors.generalEntry else SettingsColors.connectionEntry)
                    .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap) else Modifier)
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(20.dp))
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
    }
}

@Composable
internal fun SettingsDataNote(title: String, body: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), verticalAlignment = Alignment.Top) {
        Icon(Icons.Outlined.Info, contentDescription = null, tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(20.dp))
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.heading.weight)
            Text(body, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

package com.ticketbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppSpacing

/**
 * Optional fields folded under one line, like the web form's options: the line says what is inside
 * and what has been filled, and the section starts open whenever it already holds a value.
 */
@Composable
internal fun FundsOptions(title: String, filled: String?, empty: String, content: @Composable ColumnScope.() -> Unit) {
    var expanded by rememberSaveable(title) { mutableStateOf(filled != null) }
    val state = stringResource(if (expanded) R.string.expense_edit_details_row_expanded else R.string.expense_edit_details_row_collapsed)
    Column(Modifier.fillMaxWidth()) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Row(
            modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = AppSpacing.controlMinHeight)
                .clickable(role = Role.Button) { expanded = !expanded }.semantics { stateDescription = state },
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                Text(filled ?: empty, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Icon(ImageVector.vectorResource(if (expanded) R.drawable.ic_lucide_chevron_up else R.drawable.ic_lucide_chevron_down),
                contentDescription = null, modifier = Modifier.size(AppIconSize.compact))
        }
        if (expanded) Column(Modifier.padding(bottom = AppSpacing.smallGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap), content = content)
    }
}

/** What the folded line shows once something inside is filled: the values themselves, joined. */
internal fun filledSummary(vararg values: String): String? = values.map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" · ").ifEmpty { null }

/** A yes/no choice in a funds form: the statement reads first and the whole row toggles, as the envelope sources do. */
@Composable
internal fun FundsSwitchRow(label: String, checked: Boolean, enabled: Boolean, change: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = AppSpacing.controlMinHeight)
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = change),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, modifier = Modifier.weight(1f))
        AppSwitch(checked = checked, onCheckedChange = null, enabled = enabled)
    }
}

/** A chosen account keeps its role above it like a field label, so a bare account name never has to explain itself. */
@Composable
internal fun FundsAccountChoice(label: String, chosen: String, placeholder: String, enabled: Boolean, choose: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.body.weight)
        AppSecondaryButton(chosen.ifBlank { placeholder }, enabled = enabled, onClick = choose)
    }
}

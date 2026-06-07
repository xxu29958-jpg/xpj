package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DashboardCustomize
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.DraggableReorderColumn
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppSpacing
import com.valentinilk.shimmer.shimmer
import kotlinx.coroutines.launch

@Composable
fun DashboardCardsScreen(
    repository: ReportsActions,
    readOnly: Boolean,
    onBack: () -> Unit,
    onSaved: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    var cards by remember { mutableStateOf<List<DashboardCard>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    // ADR-0044: stringResource is @Composable-only, but the status messages below
    // are assigned inside non-composable local functions. Hoist the resolved strings here.
    val loadFailedMessage = stringResource(R.string.dashboard_cards_load_failed)
    val savedMessage = stringResource(R.string.dashboard_cards_saved)
    val saveFailedMessage = stringResource(R.string.dashboard_cards_save_failed)
    val resetDoneMessage = stringResource(R.string.dashboard_cards_reset_done)
    val resetFailedMessage = stringResource(R.string.dashboard_cards_reset_failed)

    suspend fun refresh() {
        loading = true
        message = null
        repository.dashboardCards(DashboardSurface.Android)
            .onSuccess { cards = it.items.normalizedDashboardPositions() }
            .onFailure { message = it.message ?: loadFailedMessage }
        loading = false
    }

    fun updateCards(updated: List<DashboardCard>) {
        cards = updated.normalizedDashboardPositions()
    }

    fun moveCard(index: Int, delta: Int) {
        val target = index + delta
        if (target !in cards.indices) return
        val mutable = cards.toMutableList()
        val item = mutable.removeAt(index)
        mutable.add(target, item)
        updateCards(mutable)
    }

    fun saveCards() {
        if (readOnly || saving) return
        scope.launch {
            saving = true
            message = null
            repository.updateDashboardCards(
                updates = cards.mapIndexed { index, card ->
                    DashboardCardUpdate(
                        key = card.key,
                        visible = card.visible,
                        position = index,
                    )
                },
                surface = DashboardSurface.Android,
            )
                .onSuccess {
                    cards = it.items.normalizedDashboardPositions()
                    message = savedMessage
                    onSaved()
                }
                .onFailure { message = it.message ?: saveFailedMessage }
            saving = false
        }
    }

    fun resetCards() {
        if (readOnly || saving) return
        scope.launch {
            saving = true
            message = null
            repository.updateDashboardCards(emptyList(), DashboardSurface.Android)
                .onSuccess {
                    cards = it.items.normalizedDashboardPositions()
                    message = resetDoneMessage
                    onSaved()
                }
                .onFailure { message = it.message ?: resetFailedMessage }
            saving = false
        }
    }

    LaunchedEffect(Unit) {
        refresh()
    }

    SettingsPageFrame(
        title = stringResource(R.string.dashboard_cards_page_title),
        subtitle = if (readOnly) {
            stringResource(R.string.dashboard_cards_page_subtitle_readonly)
        } else {
            stringResource(R.string.dashboard_cards_page_subtitle_default)
        },
        onBack = onBack,
    ) {
        SettingsSection(title = stringResource(R.string.dashboard_cards_section_order), icon = Icons.Filled.DashboardCustomize) {
            when {
                loading && cards.isEmpty() -> AppGlassCard(containerAlpha = 0.96f) {
                    Column(
                        modifier = Modifier
                            .padding(AppSpacing.cardPaddingTight)
                            .shimmer(),
                    ) {
                        repeat(4) { ListItemSkeleton(horizontalPadding = 0.dp) }
                    }
                }
                cards.isEmpty() -> AppEmptyStateCard {
                    Column(
                        modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
                    ) {
                        Text(
                            text = stringResource(R.string.dashboard_cards_empty_title),
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = AppTextHierarchy.heading.weight,
                        )
                        Text(
                            text = stringResource(R.string.dashboard_cards_empty_body),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                else -> AppGlassCard(containerAlpha = 0.96f) {
                    Column(
                        modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                    ) {
                        // v0.10：长按拾起 + 拖动排序。上下箭头作为可达性回退保留在 DashboardCardRow 内部。
                        DraggableReorderColumn(
                            items = cards,
                            key = { it.key },
                            spacing = AppSpacing.compactGap,
                            estimatedItemHeight = 56.dp,
                            enabled = !readOnly && !saving,
                            onMove = { from, to ->
                                val mutable = cards.toMutableList()
                                val item = mutable.removeAt(from)
                                mutable.add(to, item)
                                updateCards(mutable)
                            },
                        ) { index, card, _ ->
                            DashboardCardRow(
                                card = card,
                                canMoveUp = index > 0,
                                canMoveDown = index < cards.lastIndex,
                                enabled = !readOnly && !saving,
                                onMoveUp = { moveCard(index, -1) },
                                onMoveDown = { moveCard(index, 1) },
                                onVisibleChange = { visible ->
                                    updateCards(cards.map { item ->
                                        if (item.key == card.key) item.copy(visible = visible) else item
                                    })
                                },
                            )
                        }
                        if (readOnly) {
                            Text(
                                text = stringResource(R.string.dashboard_cards_readonly_hint),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        } else {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                            ) {
                                OutlinedButton(
                                    onClick = ::resetCards,
                                    enabled = !saving,
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Icon(Icons.Filled.RestartAlt, contentDescription = stringResource(R.string.dashboard_cards_reset_content_description))
                                    Spacer(Modifier.width(AppSpacing.smallGap))
                                    Text(stringResource(R.string.dashboard_cards_reset_button))
                                }
                                Button(
                                    onClick = ::saveCards,
                                    enabled = !saving && cards.isNotEmpty(),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Icon(Icons.Filled.Save, contentDescription = stringResource(R.string.dashboard_cards_save_content_description))
                                    Spacer(Modifier.width(AppSpacing.smallGap))
                                    Text(
                                        if (saving) {
                                            stringResource(R.string.dashboard_cards_save_busy)
                                        } else {
                                            stringResource(R.string.dashboard_cards_save_button)
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
        message?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
    }
}

@Composable
private fun DashboardCardRow(
    card: DashboardCard,
    canMoveUp: Boolean,
    canMoveDown: Boolean,
    enabled: Boolean,
    onMoveUp: () -> Unit,
    onMoveDown: () -> Unit,
    onVisibleChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = card.title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = card.key,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        IconButton(
            enabled = enabled && canMoveUp,
            onClick = onMoveUp,
        ) {
            Icon(Icons.Filled.KeyboardArrowUp, contentDescription = stringResource(R.string.dashboard_cards_move_up_content_description, card.title))
        }
        IconButton(
            enabled = enabled && canMoveDown,
            onClick = onMoveDown,
        ) {
            Icon(Icons.Filled.KeyboardArrowDown, contentDescription = stringResource(R.string.dashboard_cards_move_down_content_description, card.title))
        }
        AppSwitch(
            checked = card.visible,
            enabled = enabled,
            onCheckedChange = onVisibleChange,
        )
    }
}

private fun List<DashboardCard>.normalizedDashboardPositions(): List<DashboardCard> =
    sortedWith(compareBy<DashboardCard> { it.position }.thenBy { it.key })
        .mapIndexed { index, card -> card.copy(position = index) }

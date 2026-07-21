package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SecondaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePanePurpose
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.appAdaptiveSupportingPaneContent
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.screens.RelationsListChrome

internal enum class ObligationsView {
    I_OWE,
    OWED_TO_ME,
}

internal data class ObligationsNavigationActions(
    val onOpenBillSplits: () -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDebtGoals: () -> Unit,
)

@Composable
internal fun RelationsRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    var selectedView by rememberSaveable { mutableStateOf(ObligationsView.I_OWE) }
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    val navigationActions = ObligationsNavigationActions(
        onOpenBillSplits = { shellState.openSecondaryPage(ProductSecondaryPage.BillSplits) },
        onOpenRepaymentReview = { shellState.openRepaymentDrafts() },
        onOpenDebtGoals = { shellState.openSecondaryPage(ProductSecondaryPage.DebtGoals) },
    )
    val onSelectView: (ObligationsView) -> Unit = { selectedView = it }
    val chrome = relationsChrome(
        selectedView = selectedView,
        onSelectView = onSelectView,
        actions = navigationActions,
    )
    val primaryChrome = if (adaptivePolicy.showsSupportingPane) {
        chrome.copy(domainNavigation = null)
    } else {
        chrome
    }

    RelationsAdaptivePaneConsumer(
        selectedView = selectedView,
        onSelectView = onSelectView,
        actions = navigationActions,
        primaryPane = {
            RelationsPrimaryPane(
                selectedView = selectedView,
                screenFactory = screenFactory,
                chrome = primaryChrome,
            )
        },
    )
}

/**
 * Production adaptive assembly for the obligations domain.
 *
 * Kept independently mountable so adaptive tests exercise this real consumer (including its
 * navigation pane) without constructing network-backed route repositories.
 */
@Composable
internal fun RelationsAdaptivePaneConsumer(
    selectedView: ObligationsView,
    onSelectView: (ObligationsView) -> Unit,
    actions: ObligationsNavigationActions,
    primaryPane: @Composable () -> Unit,
) {
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Obligations,
        policy = adaptivePolicy,
        primaryPane = primaryPane,
        supportingPane = appAdaptiveSupportingPaneContent(
            purpose = AppAdaptivePanePurpose.ObligationNavigation,
        ) {
            AppAdaptiveSupportingPane(role = AppPageRole.Ledger) {
                ObligationsNavigation(
                    selectedView = selectedView,
                    onSelectView = onSelectView,
                    actions = actions,
                )
            }
        },
    )
}

@Composable
private fun RelationsPrimaryPane(
    selectedView: ObligationsView,
    screenFactory: MainScreenFactory,
    chrome: RelationsListChrome,
) {
    when (selectedView) {
        ObligationsView.I_OWE -> DebtRoute(
            screenFactory = screenFactory,
            onBack = {},
            chromeOverride = chrome,
        )

        ObligationsView.OWED_TO_ME -> ReceivablesRoute(
            screenFactory = screenFactory,
            onBack = {},
            chromeOverride = chrome,
        )
    }
}

@Composable
private fun relationsChrome(
    selectedView: ObligationsView,
    onSelectView: (ObligationsView) -> Unit,
    actions: ObligationsNavigationActions,
): RelationsListChrome = RelationsListChrome(
    title = stringResource(R.string.relations_title),
    subtitle = stringResource(
        when (selectedView) {
            ObligationsView.I_OWE -> R.string.relations_i_owe_subtitle
            ObligationsView.OWED_TO_ME -> R.string.relations_owed_to_me_subtitle
        },
    ),
    backText = "",
    onBack = null,
    domainNavigation = {
        ObligationsNavigation(
            selectedView = selectedView,
            onSelectView = onSelectView,
            actions = actions,
        )
    },
)

@Composable
private fun ObligationsNavigation(
    selectedView: ObligationsView,
    onSelectView: (ObligationsView) -> Unit,
    actions: ObligationsNavigationActions,
) {
    val views = listOf(
        ObligationsView.I_OWE to stringResource(R.string.relations_i_owe_tab),
        ObligationsView.OWED_TO_ME to stringResource(R.string.relations_owed_to_me_tab),
    )
    Column {
        SecondaryTabRow(
            selectedTabIndex = views.indexOfFirst { it.first == selectedView },
            containerColor = MaterialTheme.colorScheme.surface,
        ) {
            views.forEach { (view, label) ->
                Tab(
                    selected = selectedView == view,
                    onClick = { onSelectView(view) },
                    text = { Text(label) },
                )
            }
        }
        Text(
            text = stringResource(R.string.relations_task_section_title),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.fillMaxWidth(),
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_bill_splits),
            onClick = actions.onOpenBillSplits,
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_repayment_review),
            onClick = actions.onOpenRepaymentReview,
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_debt_goals),
            onClick = actions.onOpenDebtGoals,
            showDivider = false,
        )
    }
}

@Composable
private fun ObligationsTaskRow(
    title: String,
    onClick: () -> Unit,
    showDivider: Boolean = true,
) {
    AppListRow(
        onClick = onClick,
        showDivider = showDivider,
    ) {
        Text(
            text = title,
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.bodyLarge,
        )
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
